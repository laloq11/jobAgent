"""Bundesagentur für Arbeit Jobsuche adapter.

Endpoint: https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs
Docs: https://github.com/bundesAPI/jobsuche-api
Auth: header X-API-Key: jobboerse-jobsuche (public clientId).

Search-based: no "give me all" endpoint. Searches: `bundesagentur:` in data/profile/searches.yaml.
"""
from typing import Iterable
import httpx
from jobs_agent.core.models import JobPosting
from jobs_agent.core.logging import get_logger
from jobs_agent.core.profile_loader import load_searches

log = get_logger("adapters.bundesagentur")

BASE = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs"
HEADERS = {"X-API-Key": "jobboerse-jobsuche", "User-Agent": "jobsAgent/0.1"}
PUBLIC_URL = "https://www.arbeitsagentur.de/jobsuche/jobdetail/{}"


def _public_url(refnr: str) -> str:
    # The public page takes the plain refnr ("10001-1003956917-S"). The base64 form
    # is only for the API's jobdetails endpoint; on the website it returns 410,
    # which made close_stale close every row from this adapter.
    return PUBLIC_URL.format(refnr)


def _location(item: dict) -> str:
    locs = item.get("stellenlokationen") or []
    if not locs:
        return ""
    adr = locs[0].get("adresse") or {}
    parts = [adr.get("plz", ""), adr.get("ort", ""), adr.get("region", "")]
    return " ".join(p for p in parts if p).strip()


def _to_posting(item: dict) -> JobPosting | None:
    try:
        refnr = item.get("referenznummer") or item.get("refnr")
        if not refnr:
            return None
        url = item.get("externeUrl") or _public_url(refnr)
        role = item.get("stellenangebotsTitel") or item.get("hauptberuf") or "(no title)"
        company = item.get("firma", "") or ""
        location = _location(item)
        published = (item.get("veroeffentlichungszeitraum") or {}).get("von", "")
        start_date = (item.get("eintrittszeitraum") or {}).get("von", "")
        notes_bits = [
            f"published={published}" if published else "",
            f"start={start_date}" if start_date else "",
            f"refnr={refnr}",
        ]
        return JobPosting(
            role=role,
            company=company,
            url=url,
            source="bundesagentur",
            location=location,
            summary=f"{role} at {company} — {location}",
            notes=" | ".join(b for b in notes_bits if b),
            status="not_started",
        )
    except Exception as e:
        log.warning(f"skipping malformed item ({e}): refnr={item.get('referenznummer', '?')}")
        return None

class BundesagenturAdapter:
    name = "bundesagentur"

    def __init__(self, searches: list[dict] | None = None,
                 size: int = 25, timeout: float = 20.0):
        self.searches = searches or load_searches("bundesagentur")
        self.size = size
        self.timeout = timeout

    def fetch(self) -> Iterable[JobPosting]:
        seen_refnr: set[str] = set()
        with httpx.Client(timeout=self.timeout, headers=HEADERS) as client:
            for search in self.searches:
                params = {**search, "page": 1, "size": self.size,
                          "angebotsart": 1, "pav": "false"}
                log.info(f"search: {search}")
                try:
                    r = client.get(BASE, params=params)
                    r.raise_for_status()
                except Exception as e:
                    log.exception(f"search failed {search}: {e}")
                    continue
                items = r.json().get("ergebnisliste", []) or []
                log.info(f"  → {len(items)} results")
                for item in items:
                    refnr = item.get("referenznummer") or item.get("refnr")
                    if not refnr or refnr in seen_refnr:
                        continue
                    seen_refnr.add(refnr)
                    p = _to_posting(item)
                    if p is not None:
                        yield p
