"""Check that a new setup is complete. Read-only: changes nothing.

Run:  python3 -m jobs_agent.scripts.setup_check
Checks: data/profile + data/info files, pdflatex/pdfinfo, Notion access, and that the
database properties match what core/notion_repo.py writes (names and types).
Exit code 0 only if nothing is missing.
"""
import shutil
import sys
from typing import get_args

from jobs_agent.scripts.init_user import INFO_FILES, PROFILE_DIR, INFO_DIR, PROFILE_EXAMPLES

problems: list[str] = []
warnings: list[str] = []


def check_files() -> None:
    for name in sorted(p.name for p in PROFILE_EXAMPLES.glob("*.yaml")):
        if not (PROFILE_DIR / name).exists():
            problems.append(f"missing {PROFILE_DIR / name} (run init_user)")
    for name in INFO_FILES:
        path = INFO_DIR / name
        if not path.exists():
            problems.append(f"missing {path} (run init_user)")
        elif "<Your Name>" in path.read_text(errors="ignore"):
            warnings.append(f"{path} still has template placeholders")


def check_tools() -> None:
    for tool in ("pdflatex", "pdfinfo"):
        if not shutil.which(tool):
            problems.append(f"{tool} not found (needed by build_pdf; use the devcontainer)")


def check_notion() -> None:
    try:
        from jobs_agent.core.models import JobPosting, Source, Status
        from jobs_agent.core.notion_repo import NotionRepo
        repo = NotionRepo()
        props = repo.client.data_sources.retrieve(data_source_id=repo.data_source_id)["properties"]
    except Exception as e:  # missing env vars, bad token, DB not shared with the integration
        problems.append(f"Notion: {type(e).__name__}: {e}")
        return

    dummy = JobPosting(role="x", company="x", url="https://example.com", source="manual")
    expected = {name: next(iter(value)) for name, value in repo._posting_to_props(dummy).items()}
    for name, kind in expected.items():
        if name not in props:
            problems.append(f"Notion: property '{name}' missing (type {kind})")
        elif props[name]["type"] != kind:
            problems.append(f"Notion: property '{name}' is {props[name]['type']}, expected {kind}")

    for prop, literal in (("Source", Source), ("Status", Status)):
        if props.get(prop, {}).get("type") != "select":
            continue
        have = {o["name"] for o in props[prop]["select"]["options"]}
        missing = sorted(set(get_args(literal)) - have)
        if missing:
            warnings.append(f"Notion: '{prop}' has no option for {missing} (created on first use)")


def main() -> None:
    check_files()
    check_tools()
    check_notion()
    for w in warnings:
        print(f"WARN  {w}")
    for p in problems:
        print(f"FAIL  {p}")
    print("OK" if not problems else f"{len(problems)} problem(s)")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
