"""Guarantee: the PhD web search is independent of the regular adapters.

- A default ingest (run_ingest / `/jobs` without --phd-search) never loads `websearch`.
- No Python module starts the Claude CLI: the only caller of `claude -p` is
  jobs_agent/scripts/phd_websearch.sh, started by hand or by `/jobs --phd-search`.
- The regular adapters do not import the web search code.
"""
import re
from pathlib import Path
from jobs_agent.pipeline import ingest

PKG = Path(__file__).resolve().parents[1]          # jobs_agent/


def test_default_run_excludes_websearch():
    assert "websearch" in ingest.ADAPTER_REGISTRY
    assert "websearch" not in ingest.default_adapter_names()
    loaded = [type(a).__name__ for a in ingest.load_adapters(None)]
    assert "WebsearchAdapter" not in loaded
    assert len(loaded) == len(ingest.ADAPTER_REGISTRY) - len(ingest.OPT_IN_ADAPTERS)


def test_websearch_runs_only_when_named():
    loaded = ingest.load_adapters(["websearch"])
    assert [type(a).__name__ for a in loaded] == ["WebsearchAdapter"]


def test_no_python_module_calls_claude():
    calls_claude = re.compile(r"""(subprocess|os\.system|os\.exec|Popen)[^\n]*["']claude\b""")
    offenders = [str(f.relative_to(PKG)) for f in PKG.rglob("*.py")
                 if "tests" not in f.parts and calls_claude.search(f.read_text())]
    assert offenders == []
    assert "anthropic" not in "".join(f.read_text() for f in PKG.rglob("*.py") if "tests" not in f.parts)


def test_regular_adapters_do_not_import_websearch():
    for f in (PKG / "adapters").glob("*.py"):
        if f.name in ("websearch.py", "__init__.py"):
            continue
        assert "websearch" not in f.read_text(), f.name
