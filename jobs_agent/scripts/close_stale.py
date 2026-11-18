"""Set expired postings to `closed` and ignore-list companies to `ignore` in
Notion. Dry-run unless --confirm.

Checked rows: status in not_started, needs_review, approved_draft.
- Company on data/profile/ignore_companies.yaml: `ignore` (no web request).
- Greenhouse / Ashby: posting must still be on the company's live job board.
- Others: closed if the posting date in Notes (created= / published=) is older
  than --max-age-days, or if the posting URL returns 404 / 410.
Anything uncertain (403, timeout, no date) stays open.

Usage:
  python3 -m jobs_agent.scripts.close_stale                    # dry-run
  python3 -m jobs_agent.scripts.close_stale --confirm
  python3 -m jobs_agent.scripts.close_stale --max-age-days 45 --confirm
"""
import argparse
import re
from datetime import datetime, timezone
import httpx
from jobs_agent.core.logging import get_logger
from jobs_agent.core.notion_repo import NotionRepo
from jobs_agent.core.profile_loader import IGNORE_COMPANIES_PATH, load_ignored_companies
from jobs_agent.pipeline.filter_cheap import ignored_company
from jobs_agent.pipeline.notify import _prop_text

log = get_logger("scripts.close_stale")

OPEN_STATUSES = ["not_started", "needs_review", "approved_draft"]
GREENHOUSE = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
ASHBY = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


def _note(notes: str, key: str) -> str:
    m = re.search(rf"(?:^|\| ){key}=([^|]+)", notes)
    return m.group(1).strip() if m else ""


def _posted_at(notes: str) -> datetime | None:
    raw = _note(notes, "created") or _note(notes, "published")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class BoardCache:
    """Live job ids (Greenhouse) / job URLs (Ashby) per company slug, fetched once."""

    def __init__(self, client: httpx.Client):
        self.client = client
        self.cache: dict[tuple[str, str], set[str] | None] = {}

    def live(self, vendor: str, slug: str) -> set[str] | None:
        key = (vendor, slug)
        if key not in self.cache:
            self.cache[key] = self._fetch(vendor, slug)
        return self.cache[key]

    def _fetch(self, vendor: str, slug: str) -> set[str] | None:
        try:
            if vendor == "greenhouse":
                r = self.client.get(GREENHOUSE.format(slug=slug))
                r.raise_for_status()
                return {str(j.get("id")) for j in r.json().get("jobs", [])}
            r = self.client.get(ASHBY.format(slug=slug))
            r.raise_for_status()
            return {u for j in r.json().get("jobs", [])
                    for u in (j.get("jobUrl"), j.get("applyUrl")) if u}
        except Exception as e:
            log.warning(f"{vendor}/{slug}: board fetch failed ({e}); rows kept open")
            return None


def _url_gone(client: httpx.Client, url: str) -> bool:
    try:
        return client.get(url, follow_redirects=True).status_code in (404, 410)
    except Exception:
        return False


def stale_reason(row: dict, boards: BoardCache, client: httpx.Client,
                 max_age_days: int) -> str | None:
    url, notes = row["url"], row["notes"]
    slug = _note(notes, "slug")

    if "greenhouse.io" in url and slug:
        live = boards.live("greenhouse", slug)
        if live is not None and _note(notes, "id") not in live:
            return "not on Greenhouse board"
        return None
    if "ashbyhq.com" in url and slug:
        live = boards.live("ashby", slug)
        if live is not None and url not in live:
            return "not on Ashby board"
        return None

    posted = _posted_at(notes)
    if posted:
        age = (datetime.now(timezone.utc) - posted).days
        if age > max_age_days:
            return f"posted {age} days ago"
    if url and _url_gone(client, url):
        return "posting URL returns 404/410"
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-age-days", type=int, default=60)
    ap.add_argument("--confirm", action="store_true", help="write `closed` / `ignore` to Notion")
    args = ap.parse_args()

    repo = NotionRepo()
    ignore = load_ignored_companies()
    pages = repo.query_by_statuses(OPEN_STATUSES)
    log.info(f"{len(pages)} open rows | max_age_days={args.max_age_days} | "
             f"ignore_companies={len(ignore)} | confirm={args.confirm}")

    closed = ignored = kept = 0
    with httpx.Client(timeout=15.0, headers={"User-Agent": "jobsAgent/0.1"}) as client:
        boards = BoardCache(client)
        for page in pages:
            p = page["properties"]
            company = _prop_text(p.get("Company"))
            label = f"{company} — {_prop_text(p.get('Role'))}"
            entry = ignored_company(company, ignore)
            if entry:
                ignored += 1
                log.info(f"{'ignoring' if args.confirm else 'would ignore'} "
                         f"(company on ignore list: {entry}): {label}")
                if args.confirm:
                    repo.update_fields(page["id"], status="ignore",
                                       todo=f"ignored: '{entry}' is on {IGNORE_COMPANIES_PATH}")
                continue
            row = {"url": _prop_text(p.get("url")), "notes": _prop_text(p.get("Notes"))}
            reason = stale_reason(row, boards, client, args.max_age_days)
            if reason is None:
                kept += 1
                continue
            closed += 1
            log.info(f"{'closing' if args.confirm else 'would close'} ({reason}): {label}")
            if args.confirm:
                repo.update_fields(page["id"], status="closed", todo=f"auto-closed: {reason}")

    verb = "" if args.confirm else "would "
    log.info(f"done | {verb}close={closed} {verb}ignore={ignored} kept_open={kept}")


if __name__ == "__main__":
    main()
