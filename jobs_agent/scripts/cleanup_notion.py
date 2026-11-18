"""Trash rows in Notion that are still `not_started` (untouched auto-inserts).

Safe by default: dry-run unless --confirm passed.

Usage:
  python3 -m jobs_agent.scripts.cleanup_notion                    # dry-run
  python3 -m jobs_agent.scripts.cleanup_notion --confirm          # actually trash
  python3 -m jobs_agent.scripts.cleanup_notion --status rejected --confirm
"""
import argparse
from jobs_agent.core.notion_repo import NotionRepo
from jobs_agent.core.logging import get_logger

log = get_logger("scripts.cleanup")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", default="not_started",
                    help="only trash rows with this status (default: not_started)")
    ap.add_argument("--confirm", action="store_true",
                    help="actually perform the trash (default: dry-run)")
    args = ap.parse_args()

    repo = NotionRepo()
    rows = repo.query_by_status(args.status)
    log.info(f"found {len(rows)} rows with status={args.status}")

    if not args.confirm:
        log.info("dry-run mode — pass --confirm to trash")
        for r in rows[:10]:
            log.info(f"  would trash: {r['id']}")
        if len(rows) > 10:
            log.info(f"  ... and {len(rows) - 10} more")
        return

    trashed = 0
    failed = 0
    for r in rows:
        try:
            repo.trash_page(r["id"])
            trashed += 1
        except Exception as e:
            log.exception(f"trash failed for {r['id']}: {e}")
            failed += 1
    log.info(f"done | trashed={trashed} failed={failed}")


if __name__ == "__main__":
    main()
