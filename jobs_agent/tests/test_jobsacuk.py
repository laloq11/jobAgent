"""jobs.ac.uk adapter against saved fixtures (httpx.MockTransport, no network)."""
from datetime import date
from pathlib import Path
import httpx
from jobs_agent.adapters.jobsacuk import JobsAcUkAdapter, parse_results
from jobs_agent.core.dedup import SeenUrls

FIX = Path(__file__).parent / "fixtures"
CFG = {"job_type": "phds", "max_pages": 2, "searches": ["CFD", "GPU"]}


def _transport(calls: list[httpx.Request]) -> httpx.MockTransport:
    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        if req.url.path == "/search/":
            return httpx.Response(200, text=(FIX / "jobsacuk_search.html").read_text())
        if req.url.path == "/job/AAA001/phd-studentship-gpu-cfd-solvers":
            return httpx.Response(200, text=(FIX / "jobsacuk_detail.html").read_text())
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def test_parse_results():
    rs = parse_results((FIX / "jobsacuk_search.html").read_text())
    assert [r["path"] for r in rs] == ["/job/AAA001/phd-studentship-gpu-cfd-solvers",
                                       "/job/AAA002/phd-studentship-already-seen"]
    assert rs[0]["employer"] == "Example University" and rs[0]["department"] == "Mechanical Engineering"


def test_fetch(tmp_path):
    seen = SeenUrls(tmp_path / "seen.db")
    seen.mark_seen("https://www.jobs.ac.uk/job/AAA002/phd-studentship-already-seen")
    calls: list[httpx.Request] = []
    postings = list(JobsAcUkAdapter(config=CFG, seen=seen, transport=_transport(calls),
                                    min_interval=0).fetch())
    searches = [c for c in calls if c.url.path == "/search/"]
    details = [c for c in calls if c.url.path.startswith("/job/")]
    assert len(searches) == 2                     # one page each: fewer than 25 results
    assert searches[0].url.params["jobTypeFacet[]"] == "phds"
    assert len(details) == 1                      # AAA002 is in seen.db, results deduped across searches
    p = postings[0]
    assert p.source == "jobsacuk" and p.company == "Example University"
    assert p.location == "Exampleton, United Kingdom"
    assert p.deadline == date(2027, 1, 23)
    assert "published=2026-10-23" in p.notes and "id=AAA001" in p.notes
    assert "matrix-free GPU solvers" in p.summary
