"""run_ingest with a fake adapter, a fake Notion repo and a temp seen.db."""
import pytest
from jobs_agent.core.dedup import SeenUrls, posting_key
from jobs_agent.core.models import JobPosting
from jobs_agent.core.profile_loader import FilterConfig
from jobs_agent.pipeline import ingest


def _posting(url: str, role: str, company: str = "ACME", source: str = "rss") -> JobPosting:
    return JobPosting(role=role, company=company, url=url, source=source, summary=role)


class FakeAdapter:
    name = "fake"

    def __init__(self, postings):
        self.postings = postings

    def fetch(self):
        return iter(self.postings)


class FakeRepo:
    def __init__(self, existing=()):
        self.existing = set(existing)
        self.inserted: list[JobPosting] = []

    def exists_by_url(self, url: str) -> bool:
        return url in self.existing

    def insert(self, p: JobPosting) -> str:
        self.inserted.append(p)
        return f"page-{len(self.inserted)}"


@pytest.fixture
def run(tmp_path, monkeypatch):
    """Returns run(postings, dry_run, existing=()) -> (counts, repo, seen)."""
    db = tmp_path / "seen.db"
    monkeypatch.setattr(ingest, "load_filter", lambda: FilterConfig(allow=["CFD"], block=["Praktikum"]))
    monkeypatch.setattr(ingest, "load_ignored_companies", lambda: [])
    monkeypatch.setattr(ingest, "DESCRIPTIONS_DIR", tmp_path / "descriptions")

    def _run(postings, dry_run, existing=(), more_adapters=()):
        """postings go to adapter "fake"; more_adapters = [(name, postings), ...] run after it.
        Returns (counts of "fake" or a dict of all counts when more_adapters, repo, seen)."""
        repo = FakeRepo(existing)
        adapters = [FakeAdapter(postings)]
        for name, ps in more_adapters:
            a = FakeAdapter(ps)
            a.name = name
            adapters.append(a)
        monkeypatch.setattr(ingest, "NotionRepo", lambda: repo)
        monkeypatch.setattr(ingest, "SeenUrls", lambda: SeenUrls(db))
        monkeypatch.setattr(ingest, "load_adapters", lambda names, dry: adapters)
        counts = ingest.run_ingest(["fake"], dry_run=dry_run)
        return (counts if more_adapters else counts["fake"]), repo, SeenUrls(db)

    return _run


def test_dry_run_is_read_only(run):
    postings = [
        _posting("https://x.org/1", "CFD Praktikum"),            # filtered (block)
        _posting("https://x.org/2", "Sales"),                    # filtered (no_signal)
        _posting("https://x.org/3", "CFD PhD"),                  # already in Notion
        _posting("https://x.org/4", "CFD engineer"),             # would insert
    ]
    for _ in range(2):
        counts, repo, seen = run(postings, dry_run=True, existing={"https://x.org/3"})
        assert counts["filtered"] == 2
        assert counts["skipped_local"] == 0
        assert counts["skipped_notion"] == 1
        assert counts["inserted"] == 1
        assert repo.inserted == []
        assert seen.count() == 0


def test_live_run_marks_seen(run):
    postings = [_posting("https://x.org/1", "CFD Praktikum"), _posting("https://x.org/4", "CFD engineer")]
    counts, repo, seen = run(postings, dry_run=False)
    assert counts["inserted"] == 1 and counts["filtered"] == 1
    assert seen.is_seen("https://x.org/1") and seen.is_seen("https://x.org/4")
    counts, _, _ = run(postings, dry_run=False)
    assert counts["skipped_local"] == 1 and counts["inserted"] == 0


def test_posting_key_normalisation():
    a = posting_key("Universität Stuttgart", "Doktorand (m/w/d) – Strömungssimulation")
    b = posting_key("Universitat  Stuttgart.", "DOKTORAND (w/m/d): Strömungssimulation")
    assert a == b == "universitat stuttgart|doktorand stromungssimulation"
    assert posting_key("CEA", "PhD: GPU solver for CFD (f/m/x)") == posting_key("cea", "PhD - GPU solver for CFD")
    # generic titles get no key: two "PhD Position" offers at one university are different offers
    assert posting_key("TU Delft", "PhD Position (m/f/d)") is None
    assert posting_key("x", "Wissenschaftliche/r Mitarbeiter/in (w/m/d)") is None
    assert posting_key("", "PhD in CFD") is None


def test_cross_source_duplicate_skipped(run):
    a = _posting("https://euraxess.example/jobs/1", "PhD in CFD for turbomachinery (m/f/d)", "TU Delft")
    b = _posting("https://findaphd.example/phd/2", "PhD in CFD for Turbomachinery", "TU Delft ")
    counts, repo, seen = run([a], dry_run=False, more_adapters=[("other", [b])])
    assert counts["fake"]["inserted"] == 1
    assert counts["other"]["skipped_dup"] == 1 and counts["other"]["inserted"] == 0
    assert len(repo.inserted) == 1
    # next run: the key is in seen.db, a third URL with the same company/role is a dup too
    c = _posting("https://jobs.ac.uk.example/3", "PhD in CFD for turbomachinery", "TU Delft")
    counts, _, _ = run([c], dry_run=False)
    assert counts["skipped_dup"] == 1


def test_cross_source_duplicate_dry_run(run):
    a = _posting("https://a.example/1", "PhD in CFD for turbomachinery", "TU Delft")
    b = _posting("https://b.example/2", "PhD in CFD for turbomachinery", "TU Delft")
    for _ in range(2):
        counts, _, seen = run([a, b], dry_run=True)
        assert counts["inserted"] == 1 and counts["skipped_dup"] == 1
        assert seen.count() == 0


def test_generic_titles_and_watch_not_deduped(run):
    ps = [
        _posting("https://a.example/1", "PhD Position (m/f/d) CFD", "TU Delft"),
        _posting("https://a.example/2", "PhD Position (m/f/d) CFD", "TU Delft"),  # has a topic word: dup
        _posting("https://a.example/3", "PhD Position (m/f/d)", "TU Delft"),      # generic: kept
        _posting("https://a.example/4", "PhD Position (m/f/d)", "TU Delft"),      # generic: kept
        _posting("https://w.example/#aaa", "[watch] G: page changed", "G", source="watch"),
        _posting("https://w.example/#bbb", "[watch] G: page changed", "G", source="watch"),
    ]
    # generic ones need an allow hit: put CFD in the summary
    for p in ps:
        p.summary = "CFD"
    counts, _, _ = run(ps, dry_run=True)
    assert counts["skipped_dup"] == 1
    assert counts["inserted"] == 5


def test_websearch_rows_skip_allow_list_but_not_block_list(run):
    ps = [
        _posting("https://a.example/1", "Doctoral researcher in sediment transport", source="websearch"),
        _posting("https://a.example/2", "Praktikum sediment transport", source="websearch"),
        _posting("https://a.example/3", "Doctoral researcher in sediment transport", "Other", source="rss"),
    ]
    counts, _, _ = run(ps, dry_run=True)
    assert counts["inserted"] == 1      # websearch row without an allow hit passes
    assert counts["filtered"] == 2      # block hit (websearch) and no_signal (rss)
