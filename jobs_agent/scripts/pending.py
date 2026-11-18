"""Print Notion rows as JSON for Claude Code to process.

Usage:
  python3 -m jobs_agent.scripts.pending unscored --limit 30
  python3 -m jobs_agent.scripts.pending to_draft --limit 5   # highest Fit Score first
"""
import argparse
import json
from jobs_agent.core.notion_repo import NotionRepo
from jobs_agent.pipeline.ingest import description_path
from jobs_agent.pipeline.notify import _prop_text


def _row(page: dict) -> dict:
    p = page.get("properties", {})
    desc = description_path(page["id"])
    return {
        "page_id": page["id"],
        "role": _prop_text(p.get("Role")),
        "company": _prop_text(p.get("Company")),
        "location": _prop_text(p.get("Location")),
        "url": _prop_text(p.get("url")),
        "source": _prop_text(p.get("Source")),
        "fit_score": _prop_text(p.get("Fit Score")),
        "summary": _prop_text(p.get("Summary")),
        "notes": _prop_text(p.get("Notes")),
        "description_path": str(desc) if desc.exists() else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["unscored", "to_draft"])
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    repo = NotionRepo()
    if args.mode == "unscored":
        pages = repo.query_unscored(args.limit)
    else:
        pages = repo.query_to_draft(args.limit)
    print(json.dumps([_row(p) for p in pages], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
