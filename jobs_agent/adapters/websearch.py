"""PhD web search, part 2 of 2: check Claude's results without an LLM.

Reads data/websearch/results/*.json (written by jobs_agent/scripts/phd_websearch.sh,
see jobs_agent/websearch/files.py) from the last `read_days` days. Claude's output
is treated as unverified. For every result:

  dropped when  the URL is invalid or on an `original_only` domain (LinkedIn, Indeed, ...),
                robots.txt disallows it, the fetch fails / hits a bot check,
                or the page text does not contain the claimed title (>= 80 % of its words);
  skipped when  the URL is already in data/seen.db (no request).

Only url, title and institution come from Claude. Description and summary are the
fetched page text; location and deadline are kept only when they appear on the
page. published= is the search date (for close_stale's 60-day rule).
"""
import io
import json
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser
import httpx
from bs4 import BeautifulSoup
from jobs_agent.adapters._http import HEADERS, PoliteClient
from jobs_agent.core.dedup import SeenUrls, normalise
from jobs_agent.core.models import JobPosting
from jobs_agent.core.logging import get_logger
from jobs_agent.websearch.files import RESULTS, load_config

log = get_logger("adapters.websearch")

SUMMARY_MAX = 500
DESCRIPTION_MAX = 30_000
TITLE_MIN_RATIO = 0.8
USER_AGENT = HEADERS["User-Agent"]
_TRACKING = re.compile(r"^(utm_\w+|gclid|fbclid|mc_[ce]id|trk|trackingId|refId)$", re.I)
_STOP = {"the", "of", "in", "for", "and", "an", "at", "on", "to", "with", "der", "die", "das",
         "und", "im", "fur", "zur", "zum", "des", "von", "de", "la", "le", "et", "en", "du"}
_BOT_MARKERS = ("just a moment...", "attention required! | cloudflare", "verify you are human")


def normalise_url(url: str) -> str:
    """Drop the fragment and tracking parameters; keep everything else."""
    parts = urlsplit(url.strip())
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                       if not _TRACKING.match(k)])
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def on_domain(host: str, domains: list[str]) -> str | None:
    host = host.lower().removeprefix("www.")
    for d in domains:
        d = d.lower().removeprefix("www.")
        if host == d or host.endswith("." + d):
            return d
    return None


def _words(text: str) -> list[str]:
    return [w for w in normalise(text).split() if len(w) >= 3 and w not in _STOP]


def title_ratio(title: str, page_text: str) -> float:
    """Share of the title's significant words that occur on the page."""
    words = _words(title)
    if not words:
        return 0.0
    page = set(normalise(page_text).split())
    return sum(w in page for w in words) / len(words)


def page_text(resp: httpx.Response) -> str:
    ctype = resp.headers.get("content-type", "").lower()
    if "pdf" in ctype or resp.content[:5] == b"%PDF-":
        from pypdf import PdfReader  # Dockerfile; only needed for PDF postings
        reader = PdfReader(io.BytesIO(resp.content))
        return "\n".join((pg.extract_text() or "") for pg in reader.pages)
    soup = BeautifulSoup(resp.text, "lxml")
    for t in soup(["script", "style", "noscript", "nav", "header", "footer", "form", "svg"]):
        t.decompose()
    lines = [ln.strip() for ln in soup.get_text("\n").splitlines()]
    return "\n".join(ln for ln in lines if ln)


def is_bot_check(resp: httpx.Response) -> bool:
    if resp.headers.get("cf-mitigated"):
        return True
    head = resp.text[:3000].lower() if "html" in resp.headers.get("content-type", "") else ""
    return any(m in head for m in _BOT_MARKERS)


def date_on_page(iso: str, text: str) -> date | None:
    """The date if the page shows it in a common format (ISO, 25.11.2026, 25 November 2026, ...)."""
    try:
        d = date.fromisoformat((iso or "").strip()[:10])
    except ValueError:
        return None
    variants = {
        d.isoformat(), f"{d.day:02d}.{d.month:02d}.{d.year}", f"{d.day}.{d.month}.{d.year}",
        f"{d.day:02d}/{d.month:02d}/{d.year}", f"{d.day}/{d.month}/{d.year}",
        f"{d.day} {d:%B %Y}", f"{d.day:02d} {d:%B %Y}", f"{d:%B} {d.day}, {d.year}",
        f"{d.day} {d:%b %Y}", f"{d.day}. {d:%B %Y}",
        f"{d.day:02d}.{d:%b}.{d.year}", f"{d.day}.{d:%b}.{d.year}",      # Varbi: 29.Nov.2026
        f"{d.day:02d}-{d:%b}-{d.year}", f"{d:%b} {d.day}, {d.year}", f"{d.day} {d:%b}. {d.year}",
    }
    low = text.lower()
    return d if any(v.lower() in low for v in variants) else None


def _summary(text: str, title: str) -> str:
    """500 chars starting at the line that best matches the title (skips menus above it)."""
    lines = text.splitlines()
    best, best_i = 0.0, 0
    for i, ln in enumerate(lines[:400]):
        r = title_ratio(title, ln)
        if r > best:
            best, best_i = r, i
    return "\n".join(lines[best_i:])[:SUMMARY_MAX]


def load_results(results: Path, read_days: int, now: datetime) -> list[tuple[str, dict]]:
    """(search date, posting) for every posting in result files from the last read_days days."""
    out = []
    cutoff = now - timedelta(days=read_days)
    for f in sorted(results.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            created = datetime.fromisoformat(data["created"].replace("Z", "+00:00"))
        except (ValueError, KeyError, OSError) as e:
            log.warning(f"  unreadable result file {f}: {e}")
            continue
        if created < cutoff:
            continue
        for p in data.get("postings") or []:
            if isinstance(p, dict):
                out.append((created.date().isoformat(), p))
    return out


class WebsearchAdapter:
    name = "websearch"

    def __init__(self, config: dict | None = None, results: Path = RESULTS,
                 seen: SeenUrls | None = None, transport: httpx.BaseTransport | None = None,
                 min_interval: float = 1.0, now: datetime | None = None):
        self.cfg = config if config is not None else load_config()
        self.results = results
        self.seen = seen if seen is not None else SeenUrls()
        self.transport = transport
        self.min_interval = min_interval
        self.now = now or datetime.now(timezone.utc)
        self._robots: dict[str, RobotFileParser] = {}

    def _robots_allow(self, http: PoliteClient, url: str) -> bool:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        rp = self._robots.get(base)
        if rp is None:
            rp = RobotFileParser()
            try:
                r = http.fetch(base + "/robots.txt")
                if r.status_code in (401, 403):
                    rp.disallow_all = True
                elif r.status_code >= 400:
                    rp.allow_all = True        # no robots.txt = no rules
                else:
                    rp.parse(r.text.splitlines())
            except httpx.HTTPError:
                rp.allow_all = True            # the page fetch will fail anyway if the host is down
            rp.modified()                      # can_fetch() returns False until this is set
            self._robots[base] = rp
        return rp.can_fetch(USER_AGENT, url)

    def _check(self, http: PoliteClient, found: str, rec: dict, drops: Counter) -> JobPosting | None:
        title = str(rec.get("title") or "").strip()
        institution = str(rec.get("institution") or "").strip()
        raw_url = str(rec.get("url") or "").strip()

        def drop(reason: str, detail: str = "") -> None:
            drops[reason] += 1
            log.info(f"  drop ({reason}{': ' + detail if detail else ''}): {title[:80]} | {raw_url}")

        if not title or not institution or not raw_url.startswith(("http://", "https://")):
            drop("invalid")
            return None
        url = normalise_url(raw_url)
        host = urlsplit(url).netloc
        blocked = on_domain(host, self.cfg["original_only"])
        if blocked:
            drop("original_only", blocked)
            return None
        if self.seen.is_seen(url):
            drops["seen"] += 1
            return None
        if not self._robots_allow(http, url):
            drop("robots")
            return None
        try:
            resp = http.get(url)
        except httpx.HTTPStatusError as e:
            drop("http", str(e.response.status_code))
            return None
        except httpx.HTTPError as e:
            drop("http", type(e).__name__)
            return None
        if is_bot_check(resp):
            drop("bot_check")
            return None
        try:
            text = page_text(resp)
        except Exception as e:  # broken PDF etc.
            drop("unreadable", type(e).__name__)
            return None
        ratio = title_ratio(title, text)
        if ratio < TITLE_MIN_RATIO:
            drop("title_not_on_page", f"{ratio:.0%}")
            return None

        location = str(rec.get("location") or "").strip()
        city = location.split(",")[0].strip()
        if not city or city.lower() not in text.lower():
            location = ""
        deadline = date_on_page(str(rec.get("deadline") or ""), text)
        if deadline and deadline < self.now.date():
            drop("deadline_passed", deadline.isoformat())
            return None
        found_via = str(rec.get("found_via") or "web search").strip()
        notes_bits = [
            f"found_via={found_via}",
            f"site={host.removeprefix('www.')}",
            f"published={found}",          # search date: the page date is not checked
        ]
        try:
            return JobPosting(
                role=title,
                company=institution,
                url=url,
                source="websearch",
                location=location,
                deadline=deadline,
                summary=_summary(text, title),
                description=f"Source: {url}\n\n{text}"[:DESCRIPTION_MAX],
                notes=" | ".join(notes_bits),
                status="not_started",
            )
        except Exception as e:
            drop("invalid", str(e)[:60])
            return None

    def fetch(self) -> Iterable[JobPosting]:
        records = load_results(self.results, int(self.cfg["read_days"]), self.now)
        if not records:
            log.info(f"  no result files from the last {self.cfg['read_days']} days in {self.results}")
            return
        drops: Counter = Counter()
        kept = 0
        urls_this_run: set[str] = set()
        with PoliteClient(min_interval=self.min_interval, transport=self.transport) as http:
            for found, rec in records:
                key = normalise_url(str(rec.get("url") or ""))
                if key in urls_this_run:   # same URL in two result files
                    continue
                urls_this_run.add(key)
                p = self._check(http, found, rec, drops)
                if p is not None:
                    kept += 1
                    yield p
        log.info(f"  {len(urls_this_run)} results: {kept} verified, dropped/skipped {dict(drops)}")
