"""NA-Digest (numerical analysis mailing list), web archive, HTML.

https://na-digest.coecis.cornell.edu/na-digest-html/ lists one index per year
(26/index.html = 2026), each with weekly issues (26/v26n45.html). The adapter
reads the newest `issues` issues and splits each into its items: every item
starts with <a name="N"></a> and has a From: / Date: / Subject: header.
Only items about doctoral positions are kept (see is_phd_item).

url = issue URL + "#N" (the archive's own anchor), published = the item's Date:
(falls back to the issue date). No credentials; robots.txt does not exist (404).
"""
import re
from datetime import datetime
from typing import Iterable
import httpx
from bs4 import BeautifulSoup
from jobs_agent.adapters._http import PoliteClient
from jobs_agent.core.models import JobPosting
from jobs_agent.core.logging import get_logger

log = get_logger("adapters.nadigest")

ARCHIVE = "https://na-digest.coecis.cornell.edu/na-digest-html/"
SUMMARY_MAX = 500

_ITEM_ANCHOR = re.compile(r'<a name="(\d+)"></a>')
_END = re.compile(r"End of Digest|</article>", re.IGNORECASE)
# footer: "NA Digest  Friday, November 06, 2026  Volume 26 : Issue 45"
_ISSUE_DATE = re.compile(r"NA Digest\s+(?:for\s+)?\w+,\s*(\w+ \d{1,2}, \d{4})")

# Subject says it is a PhD offer.
_PHD_SUBJECT = re.compile(r"\bph\.?\s?d\b|\bdoctoral\b|\bdoctorate\b|\bstudentships?\b|\bdoktorand", re.I)
# Subject says it is something else (a postdoc / faculty body often mentions "PhD").
_OTHER_SUBJECT = re.compile(
    r"post-?doc|professor|faculty|lecturer|tenure|\bchair\b|conference|workshop|\bschool\b|"
    r"symposium|prize|award|call for (papers|submissions|nominations)|minisymposi|seminar|"
    r"webinar|editor|special issue|journal|software|release|scientist|engineer\b|\bcall\b|"
    r"deadline|course|meeting|registration|abstracts?\b|\b(19|20)\d\d\b",
    re.I,
)
# Body offers a doctoral position (not just "applicants must hold a PhD").
_PHD_BODY = re.compile(
    r"\bph\.?\s?d\.?\s*(students?|positions?|candidates?|studentships?|scholarships?|"
    r"fellowships?|opportunit\w*|projects?|researchers?)\b|"
    r"\bdoctoral (students?|candidates?|researchers?|positions?|fellowships?)\b|\bstudentships?\b",
    re.I,
)


def is_phd_item(subject: str, body: str) -> bool:
    if _PHD_SUBJECT.search(subject):
        return True
    return not _OTHER_SUBJECT.search(subject) and bool(_PHD_BODY.search(body))


def _iso(text: str) -> str:
    try:
        return datetime.strptime(text.strip(), "%B %d, %Y").date().isoformat()
    except ValueError:
        return ""


def _hrefs(html: str) -> list[str]:
    # BeautifulSoup, not a regex: the year indexes use unquoted href=v26n45.html
    return [a["href"] for a in BeautifulSoup(html or "", "lxml").select("a[href]")]


def latest_year_indexes(archive_html: str) -> list[str]:
    """Year index URLs, newest first ("26/index.html", "25/index.html", ...)."""
    years = {int(m.group(1)) for h in _hrefs(archive_html)
             if (m := re.fullmatch(r"(?:/na-digest-html/)?(\d+)/index\.html", h))}
    # two-digit years: 26 = 2026, 97 = 1997
    years_sorted = sorted(years, key=lambda y: y + (2000 if y < 87 else 1900), reverse=True)
    return [f"{ARCHIVE}{y:02d}/index.html" for y in years_sorted]


def issue_urls(year_index_html: str, year_index_url: str) -> list[str]:
    """Issue URLs of one year, newest first."""
    names = {m.group(1) for h in _hrefs(year_index_html)
             if (m := re.search(r"(?:^|/)(v\d+n\d+\.html)$", h))}
    base = year_index_url.rsplit("/", 1)[0] + "/"
    num = lambda h: int(re.search(r"n(\d+)", h).group(1))  # noqa: E731
    return [base + h for h in sorted(names, key=num, reverse=True)]


def parse_issue(html: str) -> tuple[str, list[dict]]:
    """(issue date ISO, items) — item: number, sender, domain, date, subject, body."""
    m = _ISSUE_DATE.search(BeautifulSoup(html, "lxml").get_text(" "))
    issue_date = _iso(m.group(1)) if m else ""
    parts = _ITEM_ANCHOR.split(html)
    items = []
    # parts = [preamble, n1, chunk1, n2, chunk2, ...]
    for n, chunk in zip(parts[1::2], parts[2::2]):
        end = _END.search(chunk)
        chunk = chunk[: end.start()] if end else chunk
        lines = BeautifulSoup(chunk, "lxml").get_text("\n").splitlines()
        lines = [ln.strip() for ln in lines]
        head: dict[str, str] = {}
        body_start = len(lines)
        for i, ln in enumerate(lines):
            hm = re.match(r"(From|Date|Subject):\s*(.*)$", ln)
            if hm and hm.group(1).lower() not in head:
                head[hm.group(1).lower()] = hm.group(2).strip()
                if hm.group(1) == "Subject":
                    body_start = i + 1
                    break
        body = "\n".join(ln for ln in lines[body_start:] if not re.fullmatch(r"-{10,}", ln))
        body = re.sub(r"\n{3,}", "\n\n", body).strip()
        email = re.search(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)", chunk)
        items.append({
            "number": n,
            "sender": re.sub(r"\s+\S+@\S+$", "", head.get("from", "")).strip(),
            "domain": email.group(1).lower() if email else "",
            "date": _iso(head.get("date", "")),
            "subject": head.get("subject", ""),
            "body": body,
        })
    return issue_date, items


def to_posting(item: dict, issue_url: str, issue_date: str) -> JobPosting | None:
    try:
        published = item["date"] or issue_date
        notes_bits = [
            f"issue={issue_url.rsplit('/', 1)[-1].removesuffix('.html')}",
            f"id={item['number']}",
            f"from={item['domain']}" if item["domain"] else "",
            f"published={published}" if published else "",
        ]
        return JobPosting(
            role=item["subject"],
            company=item["domain"] or "NA-Digest",
            url=f"{issue_url}#{item['number']}",
            source="nadigest",
            summary=item["body"][:SUMMARY_MAX],
            description=f"Subject: {item['subject']}\nFrom: {item['sender']}\n\n{item['body']}",
            notes=" | ".join(b for b in notes_bits if b),
            status="not_started",
        )
    except Exception as e:
        log.warning(f"skipping malformed item ({e}): {issue_url}#{item.get('number')}")
        return None


class NaDigestAdapter:
    name = "nadigest"

    def __init__(self, issues: int = 3, transport: httpx.BaseTransport | None = None,
                 min_interval: float = 1.0):
        self.issues = issues
        self.transport = transport
        self.min_interval = min_interval

    def fetch(self) -> Iterable[JobPosting]:
        with PoliteClient(min_interval=self.min_interval, transport=self.transport) as http:
            years = latest_year_indexes(http.get(ARCHIVE).text)
            urls: list[str] = []
            for year_url in years[:2]:  # previous year too, for the first weeks of January
                urls += issue_urls(http.get(year_url).text, year_url)
                if len(urls) >= self.issues:
                    break
            for url in urls[: self.issues]:
                try:
                    issue_date, items = parse_issue(http.get(url).text)
                except Exception as e:
                    log.exception(f"issue failed {url}: {e}")
                    continue
                kept = [it for it in items if is_phd_item(it["subject"], it["body"])]
                log.info(f"  {url.rsplit('/', 1)[-1]} ({issue_date}): {len(items)} items, {len(kept)} PhD")
                for it in kept:
                    p = to_posting(it, url, issue_date)
                    if p is not None:
                        yield p
