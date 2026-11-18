"""Compile a .tex file with pdflatex twice and check the result.

Output goes to <tex dir>/build/.
Checks: exit code, Overfull/Underfull boxes in the log, page count (pdfinfo).
data/info is added to TEXINPUTS so files there (e.g. a photo) resolve without copying.

Usage:
  python3 -m jobs_agent.scripts.build_pdf data/applications/00_drafts/<dir>/cv_x.tex --pages 1
Prints one JSON line; exit code 0 only if all checks pass.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

INFO_DIR = Path("data/info").resolve()


def _pdflatex(tex: Path, env: dict) -> int:
    cmd = ["pdflatex", "-interaction=nonstopmode", "-halt-on-error",
           "-output-directory=build", tex.name]
    return subprocess.run(cmd, cwd=tex.parent, env=env,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode


def _page_count(pdf: Path) -> int:
    out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
    m = re.search(r"^Pages:\s+(\d+)", out, re.MULTILINE)
    return int(m.group(1)) if m else -1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("tex", type=Path)
    ap.add_argument("--pages", type=int, default=1, help="required page count")
    args = ap.parse_args()

    tex = args.tex.resolve()
    env = {**os.environ, "TEXINPUTS": f"{INFO_DIR}:"}
    build = tex.parent / "build"
    build.mkdir(exist_ok=True)

    rc = _pdflatex(tex, env) or _pdflatex(tex, env)
    log_file = build / f"{tex.stem}.log"
    log = log_file.read_text(errors="ignore") if log_file.exists() else ""
    pdf = build / f"{tex.stem}.pdf"

    result = {
        "pdf": str(pdf),
        "compiled": rc == 0 and pdf.exists(),
        "pages": _page_count(pdf) if pdf.exists() else 0,
        "overfull": re.findall(r"^Overfull .*$", log, re.MULTILINE),
        "underfull": re.findall(r"^Underfull .*$", log, re.MULTILINE),
        "errors": re.findall(r"^! .*$", log, re.MULTILINE),
    }
    result["ok"] = (result["compiled"] and result["pages"] == args.pages
                    and not result["overfull"] and not result["underfull"])
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
