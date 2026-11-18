"""Greenhouse Job Board adapter.

Endpoint: https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
Docs: https://developers.greenhouse.io/job-board
No auth for GET. content=true includes full HTML description.

Reads confirmed company slugs from data/profile/companies.yaml. Populate that list
with `python3 -m jobs_agent.scripts.probe_greenhouse`.
"""
from typing import Iterable
import html
import httpx
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception
from jobs_agent.core.models import JobPosting
from jobs_agent.core.logging import get_logger
from jobs_agent.core.profile_loader import load_companies

log = get_logger("adapters.greenhouse")

BASE = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
SUMMARY_MAX = 500


def _is_retriable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.RequestError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500 or exc.response.status_code == 429
    return False


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception(_is_retriable),
    reraise=True,
)
def _get(client: httpx.Client, url: str, params: dict) -> httpx.Response:
    r = client.get(url, params=params)
    r.raise_for_status()
    return r


def _strip_html(raw: str) -> str:
    return BeautifulSoup(html.unescape(raw or ""), "lxml").get_text(" ", strip=True)


def _to_posting(item: dict, slug: str) -> JobPosting | None:
    try:
        job_id = item.get("id")
        title = item.get("title", "") or ""
        url = item.get("absolute_url", "") or ""
        if not url or not job_id:
            return None
        location = (item.get("location") or {}).get("name", "") or ""
        desc = _strip_html(item.get("content", ""))
        summary = desc[:SUMMARY_MAX]
        notes_bits = [
            f"slug={slug}",
            f"id={job_id}",
            f"updated={item.get('updated_at', '')}",
        ]
        return JobPosting(
            role=title,
            company=slug,   # slug is a reasonable proxy; user can override in Notion
            url=url,
            source="career_page",
            location=location,
            summary=summary,
            description=desc,
            notes=" | ".join(b for b in notes_bits if b),
            status="not_started",
        )
    except Exception as e:
        log.warning(f"skipping malformed item ({e}): id={item.get('id', '?')}")
        return None


class GreenhouseAdapter:
    name = "greenhouse"

    def __init__(self, companies: list[str] | None = None, timeout: float = 20.0):
        self.companies = companies if companies is not None else load_companies()["confirmed"]
        self.timeout = timeout

    def fetch(self) -> Iterable[JobPosting]:
        if not self.companies:
            log.warning("no confirmed companies; run scripts.probe_greenhouse")
            return
        with httpx.Client(timeout=self.timeout) as client:
            for slug in self.companies:
                url = BASE.format(slug=slug)
                log.info(f"company: {slug}")
                try:
                    r = _get(client, url, {"content": "true"})
                except Exception as e:
                    log.exception(f"fetch failed for {slug}: {e}")
                    continue
                items = r.json().get("jobs", []) or []
                log.info(f"  → {len(items)} jobs")
                for item in items:
                    p = _to_posting(item, slug)
                    if p is not None:
                        yield p