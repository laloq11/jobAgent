"""CEA adapter against saved fixtures (httpx.MockTransport, no network)."""
from pathlib import Path
import httpx
from jobs_agent.adapters.cea import CeaAdapter, parse_list

FIX = Path(__file__).parent / "fixtures"
CFG = {"max_pages": 30, "categories": ["Engineering science"], "title_keywords": ["solver"]}


def _transport(calls: list[str]) -> httpx.MockTransport:
    list_html = (FIX / "cea_list.html").read_text()
    detail_html = (FIX / "cea_detail.html").read_text()

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        if req.url.path.endswith("ListeOffre.aspx"):
            # like the real site: every page past the last one wraps to page 1
            return httpx.Response(200, text=list_html)
        if req.url.path.startswith("/job/"):
            return httpx.Response(200, text=detail_html)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_parse_list():
    items = parse_list((FIX / "cea_list.html").read_text())
    assert [i["ref"] for i in items] == ["SL-DES-27-0001", "SL-DRF-27-0002"]
    assert items[0]["category"] == "Engineering science"


def test_fetch_stops_on_wraparound_and_fetches_only_candidates():
    calls: list[str] = []
    postings = list(CeaAdapter(config=CFG, transport=_transport(calls), min_interval=0).fetch())
    list_calls = [c for c in calls if "ListeOffre" in c]
    detail_calls = [c for c in calls if "/job/" in c]
    assert len(list_calls) == 2           # page 2 brings no new reference -> stop
    assert len(detail_calls) == 1         # the Life Sciences offer fails the title check
    assert len(postings) == 1
    p = postings[0]
    assert p.source == "cea" and p.company == "CEA"
    assert p.role == "PhD thesis: GPU-accelerated solver for two-phase flows in nuclear reactors"
    assert str(p.url) == ("https://www.theses-postdocs.cea.fr/job/"
                          "job-gpu-accelerated-solver-for-two-phase-flows_40001.aspx?LCID=2057")
    assert p.location == "Saclay, France"
    assert p.summary.startswith("The thesis develops a GPU-accelerated")
    assert "id=SL-DES-27-0001" in p.notes and "start=2027-10-01" in p.notes
    assert "category=Engineering science" in p.notes
    assert "Organisation" not in p.description and "Université Paris-Saclay" in p.description
