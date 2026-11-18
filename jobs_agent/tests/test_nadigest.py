"""NA-Digest adapter against saved fixtures (httpx.MockTransport, no network)."""
from pathlib import Path
import httpx
from jobs_agent.adapters.nadigest import NaDigestAdapter, is_phd_item, parse_issue

FIX = Path(__file__).parent / "fixtures"


def _transport(calls: list[str]) -> httpx.MockTransport:
    pages = {
        "/na-digest-html/": "nadigest_archive.html",
        "/na-digest-html/26/index.html": "nadigest_year.html",
        "/na-digest-html/26/v26n45.html": "nadigest_issue.html",
    }

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        name = pages.get(req.url.path)
        return httpx.Response(200, text=(FIX / name).read_text()) if name else httpx.Response(404)

    return httpx.MockTransport(handler)


def test_parse_issue():
    date, items = parse_issue((FIX / "nadigest_issue.html").read_text())
    assert date == "2026-11-06"
    assert [i["number"] for i in items] == ["1", "2", "3"]
    third = items[2]
    assert third["subject"].startswith("PhD Position in Matrix-Free CFD Solvers")
    assert third["date"] == "2026-11-05" and third["domain"] == "uni-example.de"
    assert "End of Digest" not in third["body"] and "matrix-free" in third["body"]


def test_is_phd_item():
    assert is_phd_item("PhD Position in CFD", "")
    assert not is_phd_item("Postdoctoral Position in CFD", "Applicants must hold a PhD.")
    assert not is_phd_item("Workshop on CFD, Feb 2027", "PhD students are welcome.")
    assert is_phd_item("Open position in scientific computing", "We offer two PhD positions in CFD.")


def test_fetch_newest_issue_only_phd_items():
    calls: list[str] = []
    postings = list(NaDigestAdapter(issues=1, transport=_transport(calls), min_interval=0).fetch())
    assert calls == ["/na-digest-html/", "/na-digest-html/26/index.html", "/na-digest-html/26/v26n45.html"]
    assert len(postings) == 1
    p = postings[0]
    assert p.source == "nadigest" and p.company == "uni-example.de"
    assert str(p.url) == "https://na-digest.coecis.cornell.edu/na-digest-html/26/v26n45.html#3"
    assert "published=2026-11-05" in p.notes and "id=3" in p.notes and "issue=v26n45" in p.notes
    assert p.summary.startswith("We offer a fully funded PhD position")
