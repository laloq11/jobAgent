"""setup_check.check_notion against a fake Notion repo (no network)."""
from jobs_agent.core import notion_repo
from jobs_agent.scripts import setup_check


class FakeRepo(notion_repo.NotionRepo):
    def __init__(self, props):
        self.data_source_id = "ds"
        self.client = type("C", (), {"data_sources": type("D", (), {
            "retrieve": staticmethod(lambda data_source_id: {"properties": props})})()})()


def _props_ok() -> dict:
    kinds = {"Role": "title", "url": "url", "Source": "select", "Status": "select",
             "1st answer": "select", "Fit Score": "number", "Deadline": "date",
             "Application Date": "date", "1st interview": "date"}
    names = ["Role", "Company", "url", "Source", "Location", "Deadline", "Fit Score", "Summary",
             "Status", "cover_letter_path", "cv_path", "todo", "Application Date",
             "1st interview", "1st answer", "Notes"]
    props = {n: {"type": kinds.get(n, "rich_text")} for n in names}
    for n in ("Source", "Status", "1st answer"):
        props[n]["select"] = {"options": []}
    return props


def _run(monkeypatch, props):
    monkeypatch.setattr(notion_repo, "NotionRepo", lambda: FakeRepo(props))
    monkeypatch.setattr(setup_check, "problems", [])
    monkeypatch.setattr(setup_check, "warnings", [])
    setup_check.check_notion()
    return setup_check.problems, setup_check.warnings


def test_matching_schema_has_no_problems(monkeypatch):
    problems, warnings = _run(monkeypatch, _props_ok())
    assert problems == []
    assert any("Status" in w for w in warnings)      # no select options yet


def test_missing_and_wrong_type(monkeypatch):
    props = _props_ok()
    del props["Notes"]
    props["Fit Score"]["type"] = "rich_text"
    problems, _ = _run(monkeypatch, props)
    assert any("'Notes' missing" in p for p in problems)
    assert any("'Fit Score' is rich_text, expected number" in p for p in problems)
