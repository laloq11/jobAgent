"""Adzuna adapter.

Endpoint: https://api.adzuna.com/v1/api/jobs/{country}/search/{page}
Docs: https://developer.adzuna.com/docs/search
Auth: app_id + app_key as query params. Country = "de" unless a search sets "country".
Searches: `adzuna:` in data/profile/searches.yaml.

Free tier is generous but rate-limited. One page (up to 50 results) per search.
"""
from typing import Iterable
import httpx
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception
from jobs_agent.core.models import JobPosting
from jobs_agent.core.config import settings
from jobs_agent.core.logging import get_logger
from jobs_agent.core.profile_loader import load_searches

log = get_logger("adapters.adzuna")

BASE = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
COUNTRY = "de"
RESULTS_PER_PAGE = 50
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


def _strip_html(html: str) -> str:
    return BeautifulSoup(html or "", "lxml").get_text(" ", strip=True)


def _to_posting(item: dict) -> JobPosting | None:
    try:
        job_id = item.get("id")
        if not job_id:
            return None
        title = item.get("title", "") or ""
        company = (item.get("company") or {}).get("display_name", "") or ""
        location = (item.get("location") or {}).get("display_name", "") or ""
        url = item.get("redirect_url", "")
        if not url:
            return None
        desc = _strip_html(item.get("description", ""))
        summary = desc[:SUMMARY_MAX]
        category = (item.get("category") or {}).get("label", "")
        notes_bits = [
            f"created={item.get('created', '')}",
            f"category={category}" if category else "",
            f"contract={item.get('contract_type', '')}" if item.get("contract_type") else "",
            f"salary={item.get('salary_min', '')}-{item.get('salary_max', '')}"
            if item.get("salary_min") else "",
            f"id={job_id}",
        ]
        return JobPosting(
            role=title,
            company=company,
            url=url,
            source="adzuna",
            location=location,
            summary=summary,
            description=desc,
            notes=" | ".join(b for b in notes_bits if b),
            status="not_started",
        )
    except Exception as e:
        log.warning(f"skipping malformed item ({e}): id={item.get('id', '?')}")
        return None


class AdzunaAdapter:
    name = "adzuna"

    def __init__(self, searches: list[dict] | None = None,
                 country: str = COUNTRY, timeout: float = 20.0):
        self.searches = searches or load_searches("adzuna")
        self.country = country
        self.timeout = timeout
        self.app_id = settings.adzuna_app_id
        self.app_key = settings.adzuna_app_key

    def fetch(self) -> Iterable[JobPosting]:
        if not self.app_id or not self.app_key:
            log.warning("ADZUNA_APP_ID or ADZUNA_APP_KEY missing, skipping")
            return

        seen_ids: set[str] = set()

        with httpx.Client(timeout=self.timeout) as client:
            for search in self.searches:
                search = dict(search)
                country = search.pop("country", self.country)
                url = BASE.format(country=country, page=1)
                params = {
                    "app_id": self.app_id,
                    "app_key": self.app_key,
                    "results_per_page": RESULTS_PER_PAGE,
                    "content-type": "application/json",
                    **search,
                }
                log.info(f"search: {search} country={country}")
                try:
                    r = _get(client, url, params)
                except Exception as e:
                    log.exception(f"search failed {search}: {e}")
                    continue
                items = r.json().get("results", []) or []
                log.info(f"  → {len(items)} results")
                for item in items:
                    jid = str(item.get("id", ""))
                    if not jid or jid in seen_ids:
                        continue
                    seen_ids.add(jid)
                    p = _to_posting(item)
                    if p is not None:
                        yield p