"""Update fields of one Notion row. Only passed flags are written.

Usage:
  python3 -m jobs_agent.scripts.update_row PAGE_ID --score 8 --summary "..." \
      --deadline 2026-12-01 --status approved_draft --todo "..."
  python3 -m jobs_agent.scripts.update_row PAGE_ID --cv-path applications/x/cv.pdf \
      --cl-path applications/x/letter.pdf --status needs_final_review
"""
import argparse
from datetime import date
from jobs_agent.core.models import Status
from jobs_agent.core.notion_repo import NotionRepo
from typing import get_args


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("page_id")
    ap.add_argument("--score", type=float, dest="fit_score")
    ap.add_argument("--summary")
    ap.add_argument("--deadline", type=date.fromisoformat)
    ap.add_argument("--status", choices=get_args(Status))
    ap.add_argument("--cv-path", dest="cv_path")
    ap.add_argument("--cl-path", dest="cover_letter_path")
    ap.add_argument("--todo")
    args = vars(ap.parse_args())

    page_id = args.pop("page_id")
    fields = {k: v for k, v in args.items() if v is not None}
    if not fields:
        ap.error("nothing to update")
    NotionRepo().update_fields(page_id, **fields)
    print(f"updated {page_id}: {sorted(fields)}")


if __name__ == "__main__":
    main()
