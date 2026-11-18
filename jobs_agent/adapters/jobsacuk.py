"""jobs.ac.uk PhD postings, HTML search + JSON-LD detail pages.

jobs.ac.uk no longer has RSS feeds (the /feeds/ index is 404 since 2026), but its
search pages are server-rendered and allowed by robots.txt. For each keyword in
data/profile/jobsacuk.yaml the adapter reads up to max_pages result pages
(/search/?keywords=..&jobTypeFacet[]=phds, newest first), then fetches the detail
page of every result not yet in data/seen.db. The detail page carries a
schema.org JobPosting (JSON-LD): title, description, datePosted, validThrough,
hiringOrganization, jobLocation.
"""
import json
import re
from datetime import date
from pathlib import Path
from typing import Iterable
import httpx
import yaml
from bs4 import BeautifulSoup
from jobs_agent.adapters._http import PoliteClient
from jobs_agent.core.dedup import SeenUrls
from jobs_agent.core.models import JobPosting
from jobs_agent.core.logging import get_logger

log = get_logger("adapters.jobsacuk")

BASE = "https://www.jobs.ac.uk"
SEARCH_URL = f"{BASE}/search/"
CONFIG_PATH = Path("data/profile/jobsacuk.yaml")
PAGE_SIZE = 25
SUMMARY_MAX = 500


def load_config(path: Path = CONFIG_PATH) -> dict:
    data = (yaml.safe_load(path.read_text()) or {}) if path.exists() else {}
    return {
        "job_type": str(data.get("job_type") or "phds"),
        "max_pages": int(data.get("max_pages") or 2),
        "searches": [str(s) for s in (data.get("searches") or [])],
    }


def parse_results(html: str) -> list[dict]:
    """Search results: path, title, employer, department."""
    soup = BeautifulSoup(html or "", "lxml")
    out = []
    for card in soup.select("div.j-search-result__result"):
        a = card.select_one("div.j-search-result__text > a[href^='/job/']")
        if a is None:
            continue
        emp = card.select_one(".j-search-result__employer")
        dept = card.select_one(".j-search-result__department")
        out.append({
            "path": a["href"],
            "title": a.get_text(" ", strip=True),
            "employer": emp.get_text(" ", strip=True) if emp else "",
            "department": dept.get_text(" ", strip=True) if dept else "",
        })
    return out


def parse_detail(html: str) -> dict:
    """The JSON-LD JobPosting of a detail page ({} if missing), plus page text fallback."""
    soup = BeautifulSoup(html or "", "lxml")
    data: dict = {}
    for tag in soup.select('script[type="application/ld+json"]'):
        try:
            obj = json.loads(tag.string or "")
        except ValueError:
            continue
        if isinstance(obj, dict) and obj.get("@type") == "JobPosting":
            data = obj
            break
    jd = soup.select_one("#job-description")
    data["_page_text"] = jd.get_text("\n", strip=True) if jd else ""
    return data


def _text(html_fragment: str) -> str:
    return BeautifulSoup(html_fragment or "", "lxml").get_text("\n", strip=True)


def _date(iso: str) -> date | None:
    try:
        return date.fromisoformat((iso or "")[:10])
    except ValueError:
        return None


def _location(ld: dict) -> str:
    locs = ld.get("jobLocation") or []
    if isinstance(locs, dict):
        locs = [locs]
    for loc in locs:
        addr = (loc or {}).get("address") or {}
        parts = [addr.get("addressLocality"), addr.get("addressCountry")]
        text = ", ".join(p for p in parts if p)
        if text:
            return text
    return ""


def to_posting(result: dict, ld: dict, url: str) -> JobPosting | None:
    try:
        desc = _text(ld.get("description", "")) or ld.get("_page_text", "")
        published = _date(ld.get("datePosted", ""))
        m = re.match(r"/job/([A-Z0-9]+)/", result["path"])
        notes_bits = [
            f"id={m.group(1)}" if m else "",
            f"published={published.isoformat()}" if published else "",
            f"department={result['department']}" if result["department"] else "",
        ]
        return JobPosting(
            role=ld.get("title") or result["title"],
            company=((ld.get("hiringOrganization") or {}).get("name") or result["employer"]
                     or "jobs.ac.uk"),
            url=url,
            source="jobsacuk",
            location=_location(ld) or "United Kingdom",
            deadline=_date(ld.get("validThrough", "")),
            summary=desc[:SUMMARY_MAX],
            description=desc,
            notes=" | ".join(b for b in notes_bits if b),
            status="not_started",
        )
    except Exception as e:
        log.warning(f"skipping malformed posting ({e}): {url}")
        return None


class JobsAcUkAdapter:
    name = "jobsacuk"

    def __init__(self, config: dict | None = None, seen: SeenUrls | None = None,
                 transport: httpx.BaseTransport | None = None, min_interval: float = 1.0):
        self.cfg = config if config is not None else load_config()
        self.seen = seen if seen is not None else SeenUrls()
        self.transport = transport
        self.min_interval = min_interval

    def _search(self, http: PoliteClient, keywords: str) -> list[dict]:
        found: list[dict] = []
        for page in range(self.cfg["max_pages"]):
            params = {
                "keywords": keywords, "jobTypeFacet[]": self.cfg["job_type"],
                "sortOrder": 1, "pageSize": PAGE_SIZE, "startIndex": 1 + page * PAGE_SIZE,
            }
            try:
                results = parse_results(http.get(SEARCH_URL, params=params).text)
            except Exception as e:
                log.exception(f"search failed '{keywords}' page {page + 1}: {e}")
                break
            found += results
            if len(results) < PAGE_SIZE:
                break
        log.info(f"  search '{keywords}': {len(found)} results")
        return found

    def fetch(self) -> Iterable[JobPosting]:
        if not self.cfg["searches"]:
            log.warning(f"no searches in {CONFIG_PATH}")
            return
        with PoliteClient(min_interval=self.min_interval, transport=self.transport) as http:
            results: dict[str, dict] = {}
            for kw in self.cfg["searches"]:
                for r in self._search(http, kw):
                    results.setdefault(r["path"], r)
            new = {p: r for p, r in results.items() if not self.seen.is_seen(BASE + p)}
            log.info(f"  {len(results)} unique results, {len(new)} not in seen.db -> detail pages")
            for path, r in new.items():
                url = BASE + path
                try:
                    ld = parse_detail(http.get(url).text)
                except Exception as e:
                    log.warning(f"  detail failed {url}: {e}")
                    continue
                p = to_posting(r, ld, url)
                if p is not None:
                    yield p
