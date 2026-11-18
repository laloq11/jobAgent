"""Ashby public Job Board adapter.

Endpoint: https://api.ashbyhq.com/posting-api/job-board/{slug}
Docs: https://developers.ashbyhq.com/docs/public-job-posting-api
No auth. Response: {"apiVersion", "jobs": [{title, location, descriptionPlain,
jobUrl, publishedAt, department, employmentType, isRemote, workplaceType, ...}]}

Reads confirmed_ashby slugs from data/profile/companies.yaml.
Populate via: python3 -m jobs_agent.scripts.probe_ashby
"""
from typing import Iterable
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception
from jobs_agent.core.models import JobPosting
from jobs_agent.core.logging import get_logger
from jobs_agent.core.profile_loader import load_companies

log = get_logger("adapters.ashby")

BASE = "https://api.ashbyhq.com/posting-api/job-board/{slug}"
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
def _get(client: httpx.Client, url: str) -> httpx.Response:
    r = client.get(url)
    r.raise_for_status()
    return r


def _to_posting(item: dict, slug: str) -> JobPosting | None:
    try:
        title = item.get("title", "") or ""
        url = item.get("jobUrl") or item.get("applyUrl") or ""
        if not title or not url:
            return None
        location = item.get("location", "") or ""
        desc = item.get("descriptionPlain", "") or ""
        summary = desc[:SUMMARY_MAX]
        notes_bits = [
            f"slug={slug}",
            f"dept={item.get('department', '')}" if item.get("department") else "",
            f"team={item.get('team', '')}" if item.get("team") else "",
            f"employment={item.get('employmentType', '')}" if item.get("employmentType") else "",
            f"remote={item.get('isRemote', False)}",
            f"published={item.get('publishedAt', '')}",
        ]
        return JobPosting(
            role=title,
            company=slug,
            url=url,
            source="career_page",
            location=location,
            summary=summary,
            description=desc,
            notes=" | ".join(b for b in notes_bits if b),
            status="not_started",
        )
    except Exception as e:
        log.warning(f"skipping malformed item ({e}): title={item.get('title', '?')}")
        return None


class AshbyAdapter:
    name = "ashby"

    def __init__(self, companies: list[str] | None = None, timeout: float = 20.0):
        self.companies = companies if companies is not None else load_companies()["confirmed_ashby"]
        self.timeout = timeout

    def fetch(self) -> Iterable[JobPosting]:
        if not self.companies:
            log.warning("no confirmed ashby companies; run scripts.probe_ashby")
            return
        with httpx.Client(timeout=self.timeout) as client:
            for slug in self.companies:
                url = BASE.format(slug=slug)
                log.info(f"company: {slug}")
                try:
                    r = _get(client, url)
                except Exception as e:
                    log.exception(f"fetch failed for {slug}: {e}")
                    continue
                items = r.json().get("jobs", []) or []
                log.info(f"  → {len(items)} jobs")
                for item in items:
                    p = _to_posting(item, slug)
                    if p is not None:
                        yield p
