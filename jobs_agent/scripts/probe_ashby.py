"""Probe each name in companies.yaml `allow` against the Ashby public job-board API.

Slug = lowercase, punctuation removed, spaces → hyphens.
Existing confirmed_ashby entries are preserved.

Usage: python3 -m jobs_agent.scripts.probe_ashby
"""
import re
import httpx
from jobs_agent.core.logging import get_logger
from jobs_agent.core.profile_loader import load_companies, update_section

log = get_logger("scripts.probe_ashby")

BASE = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


def _to_slug(name: str) -> str:
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"\s+", "-", s)
    return s


def _has_board(client: httpx.Client, slug: str) -> bool:
    try:
        r = client.get(BASE.format(slug=slug))
        if r.status_code != 200:
            return False
        return "jobs" in r.json()
    except Exception:
        return False


def main() -> None:
    cfg = load_companies()
    allow = cfg["allow"]
    existing = set(cfg["confirmed_ashby"])
    log.info(f"allow: {len(allow)} names | already confirmed_ashby: {len(existing)}")

    found: set[str] = set(existing)
    with httpx.Client(timeout=15.0) as client:
        for name in allow:
            slug = _to_slug(name)
            if not slug or slug in found:
                if slug in found:
                    log.info(f"  {name} → {slug} (already confirmed)")
                continue
            ok = _has_board(client, slug)
            log.info(f"  {name} → {slug}: {'FOUND' if ok else 'not on ashby'}")
            if ok:
                found.add(slug)

    update_section("confirmed_ashby", sorted(found))
    added = found - existing
    log.info(f"confirmed_ashby total: {len(found)} | added: {sorted(added)}")


if __name__ == "__main__":
    main()
