"""CLI for the notify pipeline.

Usage:
  python3 -m jobs_agent.scripts.run_notify --since 2026-11-14T18:00:00Z
  python3 -m jobs_agent.scripts.run_notify                 # last 24h
  python3 -m jobs_agent.scripts.run_notify --statuses needs_final_review --send-empty
  python3 -m jobs_agent.scripts.run_notify --since <RUN_START> --report logs/run_report.md
  python3 -m jobs_agent.scripts.run_notify --since <RUN_START> --report logs/run_report.md --preview /tmp/digest
"""
import argparse
from pathlib import Path
from jobs_agent.pipeline.notify import run_notify


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=None, help="ISO UTC timestamp, e.g. run start")
    ap.add_argument("--statuses", nargs="+", default=None)
    ap.add_argument("--send-empty", action="store_true",
                    help="send the email even if there are no rows")
    ap.add_argument("--report", type=Path, default=None,
                    help="Markdown run report to put on top (e.g. logs/run_report.md)")
    ap.add_argument("--preview", type=Path, default=None,
                    help="write <path>.html and <path>.txt instead of sending")
    args = ap.parse_args()
    run_notify(since=args.since, statuses=args.statuses, send_empty=args.send_empty,
               report_path=args.report, preview=args.preview)


if __name__ == "__main__":
    main()
