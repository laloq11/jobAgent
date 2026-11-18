"""CLI entry point for the ingest pipeline.

Usage:
  python3 -m jobs_agent.scripts.run_ingest                  # all adapters, live
  python3 -m jobs_agent.scripts.run_ingest --dry-run        # no writes
  python3 -m jobs_agent.scripts.run_ingest --adapters arbeitnow
  python3 -m jobs_agent.scripts.run_ingest --adapters websearch    # PhD web search results only

The default run (no --adapters) never includes the opt-in adapters (websearch):
see jobs_agent/websearch/README.md.
"""
import argparse
from jobs_agent.pipeline.ingest import run_ingest


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapters", nargs="+", default=None,
                    help="adapter names to run (default: all registered except opt-in ones: websearch)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    run_ingest(adapter_names=args.adapters, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
