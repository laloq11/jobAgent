"""Probe each name in companies.yaml `allow` against the Greenhouse Job Board API.

For each name: try slug = lowercase + no whitespace/punct. GET /jobs endpoint.
If 200 with jobs → add slug to `confirmed`. Existing entries in `confirmed` are kept.

Usage: python3 -m jobs_agent.scripts.probe_greenhouse
"""
import re
import httpx
from jobs_agent.core.logging import get_logger
from jobs_agent.core.profile_loader import load_companies, update_confirmed

log = get_logger("scripts.probe_greenhouse")

BASE = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"


def _to_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _has_board(client: httpx.Client, slug: str) -> bool:
    try:
        r = client.get(BASE.format(slug=slug), params={"content": "false"})
        if r.status_code != 200:
            return False
        return "jobs" in r.json()
    except Exception:
        return False


def main() -> None:
    cfg = load_companies()
    allow = cfg["allow"]
    existing = set(cfg["confirmed"])

    log.info(f"allow: {len(allow)} names | already confirmed: {len(existing)}")

    found: set[str] = set(existing)
    with httpx.Client(timeout=15.0) as client:
        for name in allow:
            slug = _to_slug(name)
            if not slug:
                continue
            if slug in found:
                log.info(f"  {name} → {slug} (already confirmed)")
                continue
            ok = _has_board(client, slug)
            log.info(f"  {name} → {slug}: {'FOUND' if ok else 'not on greenhouse'}")
            if ok:
                found.add(slug)

    update_confirmed(sorted(found))
    added = found - existing
    log.info(f"confirmed total: {len(found)} | added this run: {sorted(added)}")


if __name__ == "__main__":
    main()