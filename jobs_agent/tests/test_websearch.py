"""websearch adapter (part 2): Claude's results checked against fixture pages, no network."""
import json
from datetime import date, datetime, timezone
from pathlib import Path
import httpx
from jobs_agent.adapters.websearch import (WebsearchAdapter, date_on_page, normalise_url,
                                           title_ratio)
from jobs_agent.core.dedup import SeenUrls

FIX = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 18, 9, 0, tzinfo=timezone.utc)
CFG = {"read_days": 14, "original_only": ["linkedin.com", "indeed.com"]}


def _transport(calls: list[str]) -> httpx.MockTransport:
    page = (FIX / "websearch_page.html").read_text()
    other = "<html><body><h1>PhD Position: Something Else Entirely</h1></body></html>"
    challenge = "<html><head><title>Just a moment...</title></head><body></body></html>"

    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        calls.append(url)
        html = {"content-type": "text/html; charset=utf-8"}
        if req.url.path == "/robots.txt":
            if req.url.host == "blocked.example.net":
                return httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")
            return httpx.Response(404)
        if url == "https://uni.example.org/jobs/phd-gpu-cfd":
            return httpx.Response(200, text=page, headers=html)
        if url == "https://uni.example.org/jobs/closed":
            return httpx.Response(200, text="<h1>PhD in Spectral Element Methods</h1><p>Deadline: 01.11.2026</p>",
                                  headers=html)
        if url == "https://uni.example.org/jobs/other":
            return httpx.Response(200, text=other, headers=html)
        if url == "https://cf.example.com/phd":
            return httpx.Response(200, text=challenge, headers=html)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _results_dir(tmp_path: Path) -> Path:
    d = tmp_path / "results"
    d.mkdir()
    current = json.loads((FIX / "websearch_results.json").read_text())
    current["postings"].append({"title": "PhD in Spectral Element Methods", "institution": "Example University",
                                "url": "https://uni.example.org/jobs/closed", "found_via": "portal",
                                "deadline": "2026-11-01"})
    (d / "2026-11-17_1200.json").write_text(json.dumps(current))
    old = json.loads((FIX / "websearch_results.json").read_text())
    old["created"] = "2026-10-01T12:00:00Z"   # older than read_days: ignored
    old["postings"] = [{"title": "Old PhD", "institution": "X", "url": "https://old.example.org/a",
                        "found_via": "web search"}]
    (d / "2026-10-01_1200.json").write_text(json.dumps(old))
    return d


def test_helpers():
    assert normalise_url("https://a.org/x?id=3&utm_source=s&gclid=1#frag") == "https://a.org/x?id=3"
    page = "Doktorand*in (w/m/d) für Strömungssimulation mit GPU-Lösern"
    assert title_ratio("Doktorand*in (m/w/d) – Strömungssimulation mit GPU-Lösern", page) == 1.0
    assert title_ratio("PhD in quantum chemistry", page) < 0.5
    assert date_on_page("2026-12-15", "Deadline: 15.12.2026") == date(2026, 12, 15)
    assert date_on_page("2026-12-15", "Deadline: 15 December 2026") == date(2026, 12, 15)
    assert date_on_page("2026-12-16", "Deadline: 15.12.2026") is None
    assert date_on_page("2026-11-29", "Last application date\n29.Nov.2026") == date(2026, 11, 29)


def test_fetch_keeps_only_verified(tmp_path):
    seen = SeenUrls(tmp_path / "seen.db")
    seen.mark_seen("https://uni.example.org/jobs/seen")
    calls: list[str] = []
    adapter = WebsearchAdapter(config=CFG, results=_results_dir(tmp_path), seen=seen,
                               transport=_transport(calls), min_interval=0, now=NOW)
    postings = list(adapter.fetch())

    assert len(postings) == 1
    p = postings[0]
    assert p.source == "websearch"
    assert str(p.url) == "https://uni.example.org/jobs/phd-gpu-cfd"     # tracking + fragment dropped
    assert p.company == "Example University"
    assert p.location == "Exampleton, Germany"                          # city is on the page
    assert p.deadline == date(2026, 12, 15)                             # 15.12.2026 is on the page
    assert "found_via=indeed" in p.notes and "published=2026-11-17" in p.notes
    assert "site=uni.example.org" in p.notes
    assert p.summary.startswith("PhD Position (f/m/d): GPU-accelerated")  # menu skipped
    assert "matrix-free discontinuous Galerkin" in p.description

    # never requested: LinkedIn (original_only), the seen URL, the stale file, robots-disallowed page
    assert not any("linkedin" in c for c in calls)
    assert "https://uni.example.org/jobs/seen" not in calls
    assert not any("old.example.org" in c for c in calls)
    assert "https://blocked.example.net/private/phd" not in calls
    assert "https://blocked.example.net/robots.txt" in calls


def test_no_result_files(tmp_path):
    adapter = WebsearchAdapter(config=CFG, results=tmp_path / "none", seen=SeenUrls(tmp_path / "s.db"),
                               transport=_transport([]), min_interval=0, now=NOW)
    assert list(adapter.fetch()) == []
