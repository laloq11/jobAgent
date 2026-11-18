"""Create your local, git-ignored data/ folder from the examples. Never overwrites.

Run once after cloning:  python3 -m jobs_agent.scripts.init_user
  data/profile/*.yaml     <- jobs_agent/profile_examples/   (your search config)
  data/info/*             <- jobs_agent/info_templates/     (your profile + CV/letter templates)
  data/applications/00_drafts/, logs/, data/private_patterns.txt
Also enables the privacy pre-commit hook (git config core.hooksPath .githooks).
Then edit data/info/me_ai_master.md and data/profile/*.yaml, and run setup_check.
"""
import shutil
import subprocess
from pathlib import Path

PROFILE_EXAMPLES = Path("jobs_agent/profile_examples")
INFO_TEMPLATES = Path("jobs_agent/info_templates")
PROFILE_DIR = Path("data/profile")
INFO_DIR = Path("data/info")
INFO_FILES = ["me_ai_master.md", "cv_industry.tex", "cv_academic.tex", "letter_template.tex"]


def copy_missing(src_dir: Path, dst_dir: Path, names: list[str]) -> None:
    dst_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        dst = dst_dir / name
        if dst.exists():
            print(f"keep    {dst}")
        else:
            shutil.copy(src_dir / name, dst)
            print(f"created {dst}")


def main() -> None:
    copy_missing(PROFILE_EXAMPLES, PROFILE_DIR, sorted(p.name for p in PROFILE_EXAMPLES.glob("*.yaml")))
    copy_missing(INFO_TEMPLATES, INFO_DIR, INFO_FILES)
    for d in (Path("data/applications/00_drafts"), Path("logs")):
        d.mkdir(parents=True, exist_ok=True)
    patterns = Path("data/private_patterns.txt")
    if not patterns.exists():
        patterns.write_text("# One string per line (case-insensitive) that must never be committed:\n"
                            "# your full name, email, phone, street, student id, ...\n")
        print(f"created {patterns}  <- fill it in")
    subprocess.run(["git", "config", "core.hooksPath", ".githooks"], check=False)
    print("enabled pre-commit hook (.githooks/pre-commit)")
    print("next: edit data/private_patterns.txt, data/info/me_ai_master.md and data/profile/*.yaml, "
          "then python3 -m jobs_agent.scripts.setup_check")


if __name__ == "__main__":
    main()
