"""Arbeitnow public job board adapter.

Endpoint: https://www.arbeitnow.com/api/job-board-api
Docs: https://www.arbeitnow.com/blog/job-board-api
No auth. 100 results/page. Pagination via ?page=N.
"""
from typing import Iterable
import httpx
from bs4 import BeautifulSoup
from jobs_agent.core.models import JobPosting
from jobs_agent.core.logging import get_logger

log = get_logger("adapters.arbeitnow")

BASE_URL = "https://www.arbeitnow.com/api/job-board-api"
SUMMARY_MAX = 500


def _strip_html(html: str) -> str:
    return BeautifulSoup(html or "", "lxml").get_text(" ", strip=True)


def _to_posting(item: dict) -> JobPosting | None:
    try:
        desc_text = _strip_html(item.get("description", ""))
        summary = desc_text[:SUMMARY_MAX]
        tags = ", ".join(item.get("tags", []) or [])
        job_types = ", ".join(item.get("job_types", []) or [])
        notes_bits = [
            f"remote={item.get('remote', False)}",
            f"tags=[{tags}]" if tags else "",
            f"job_types=[{job_types}]" if job_types else "",
        ]
        notes = " | ".join(b for b in notes_bits if b)
        return JobPosting(
            role=item["title"],
            company=item.get("company_name", "") or "",
            url=item["url"],
            source="arbeitnow",
            location=item.get("location", "") or "",
            summary=summary,
            description=desc_text,
            notes=notes,
            status="not_started",
        )
    except Exception as e:
        log.warning(f"skipping malformed item ({e}): {item.get('url', '?')}")
        return None


class ArbeitnowAdapter:
    name = "arbeitnow"

    def __init__(self, max_pages: int = 1, timeout: float = 20.0):
        self.max_pages = max_pages
        self.timeout = timeout

    def fetch(self) -> Iterable[JobPosting]:
        with httpx.Client(timeout=self.timeout) as client:
            for page in range(1, self.max_pages + 1):
                log.info(f"page {page}")
                r = client.get(BASE_URL, params={"page": page})
                r.raise_for_status()
                data = r.json().get("data", [])
                if not data:
                    log.info(f"page {page} empty, stopping")
                    return
                for item in data:
                    p = _to_posting(item)
                    if p is not None:
                        yield p
