"""websearch part 1 helpers: guard, prompt, collect (no claude call)."""
import json
from datetime import datetime, timezone
from pathlib import Path
from jobs_agent.websearch.files import DEFAULTS, collect, guard, prepare, render_prompt

NOW = datetime(2026, 11, 18, 9, 0, tzinfo=timezone.utc)
PHD = "phd_profile:\n  core_topics:\n    - GPU-accelerated / matrix-free solvers\n"
CFG = {**DEFAULTS, "original_only": ["linkedin.com", "indeed.com"], "indeed_countries": ["DE", "AT"],
       "portal_hints": ["academictransfer.com", "varbi.com"]}


def _result(dir_: Path, created: str) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    (dir_ / f"{created[:10]}.json").write_text(json.dumps({"created": created, "postings": []}))


def test_render_prompt():
    text = render_prompt(CFG, NOW, PHD)
    assert "Today is 2026-11-18" in text and "publication date before 2026-09-19" in text
    assert "matrix-free solvers" in text
    assert "linkedin.com, indeed.com" in text
    assert "country_code from DE, AT" in text
    assert "site:academictransfer.com PhD CFD" in text and "for each of academictransfer.com, varbi.com" in text
    assert text.index("Job portals") < text.index("Indeed: load") < text.index("Topic searches")
    assert "$" not in text
    assert "search_jobs" not in render_prompt({**CFG, "use_indeed": False}, NOW, PHD)


def test_guard(tmp_path):
    assert guard(CFG, NOW, tmp_path) is None
    _result(tmp_path, "2026-11-16T09:00:00Z")
    assert "next one from 2026-11-23" in guard(CFG, NOW, tmp_path)
    assert guard(CFG, datetime(2026, 11, 24, tzinfo=timezone.utc), tmp_path) is None


def test_prepare(tmp_path):
    phd = tmp_path / "phd.yaml"
    phd.write_text(PHD)
    run_dir = prepare(CFG, NOW, root=tmp_path, phd_path=phd)
    assert run_dir == tmp_path / "runs" / "2026-11-18_0900"
    args = (run_dir / "args.sh").read_text()
    assert "TOOLS=WebSearch,WebFetch,ToolSearch" in args
    assert "mcp__claude_ai_Indeed__search_jobs" in args and "BUDGET=3.00" in args
    assert json.loads((run_dir / "schema.json").read_text())["required"] == ["postings", "searches_done"]
    _result(tmp_path / "results", "2026-11-17T09:00:00Z")
    assert prepare(CFG, NOW, root=tmp_path, phd_path=phd) is None           # guard
    assert prepare(CFG, NOW, force=True, root=tmp_path, phd_path=phd) is not None


def test_collect(tmp_path):
    run = tmp_path / "runs" / "2026-11-18_0900"
    run.mkdir(parents=True)
    raw = run / "claude_output.json"
    results = tmp_path / "results"

    raw.write_text(json.dumps({"subtype": "error_max_budget_usd", "is_error": True, "total_cost_usd": 3.01}))
    assert collect(raw, NOW, results)[0] == 4
    raw.write_text(json.dumps({"subtype": "error_during_execution", "is_error": True}))
    assert collect(raw, NOW, results)[0] == 1
    assert not results.exists()

    out = {"postings": [{"title": "t", "institution": "i", "url": "https://a.org", "found_via": "web search"}],
           "searches_done": ["q1", "q2"]}
    raw.write_text(json.dumps({"subtype": "success", "is_error": False, "total_cost_usd": 1.5,
                               "num_turns": 30, "structured_output": out}))
    code, msg = collect(raw, NOW, results)
    assert code == 0 and "1 postings" in msg
    saved = json.loads((results / "2026-11-18_0900.json").read_text())
    assert saved["created"] == "2026-11-18T09:00:00Z" and saved["cost_usd"] == 1.5
    assert saved["postings"] == out["postings"]
