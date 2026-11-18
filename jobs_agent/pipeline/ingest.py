"""Ingest pipeline: adapters -> cheap filter -> local dedup -> Notion dedup -> insert."""
from pathlib import Path
from jobs_agent.core.logging import get_logger
from jobs_agent.core.dedup import SeenUrls, posting_key
from jobs_agent.core.notion_repo import NotionRepo
from jobs_agent.core.profile_loader import load_filter, load_ignored_companies
from jobs_agent.adapters.base import Adapter
from jobs_agent.adapters.arbeitnow import ArbeitnowAdapter
from jobs_agent.adapters.bundesagentur import BundesagenturAdapter
from jobs_agent.adapters.adzuna import AdzunaAdapter
from jobs_agent.adapters.greenhouse import GreenhouseAdapter
from jobs_agent.adapters.ashby import AshbyAdapter
from jobs_agent.adapters.rss import RssAdapter
from jobs_agent.adapters.watch import WatchAdapter
from jobs_agent.adapters.cea import CeaAdapter
from jobs_agent.adapters.nadigest import NaDigestAdapter
from jobs_agent.adapters.jobsacuk import JobsAcUkAdapter
from jobs_agent.adapters.websearch import WebsearchAdapter
from jobs_agent.pipeline.filter_cheap import check as cheap_check, ignored_company

log = get_logger("pipeline.ingest")

DESCRIPTIONS_DIR = Path("data/descriptions")


def description_path(page_id: str) -> Path:
    return DESCRIPTIONS_DIR / f"{page_id}.txt"


def save_description(page_id: str, text: str) -> None:
    if not text:
        return
    DESCRIPTIONS_DIR.mkdir(parents=True, exist_ok=True)
    description_path(page_id).write_text(text)

ADAPTER_REGISTRY: dict[str, type] = {
    "arbeitnow": ArbeitnowAdapter,
    "bundesagentur": BundesagenturAdapter,
    "adzuna": AdzunaAdapter,
    "greenhouse": GreenhouseAdapter,
    "ashby": AshbyAdapter,
    "rss": RssAdapter,
    "watch": WatchAdapter,
    "cea": CeaAdapter,
    "nadigest": NaDigestAdapter,
    "jobsacuk": JobsAcUkAdapter,
    "websearch": WebsearchAdapter,
}

# Run only when named explicitly (--adapters websearch), never in a default run.
# websearch ingests the results of the PhD web search (jobs_agent/websearch/README.md),
# which is started on its own and uses subscription usage: it stays independent of
# the regular adapters. Guarded by tests/test_websearch_independent.py.
OPT_IN_ADAPTERS = {"websearch"}


def default_adapter_names() -> list[str]:
    return [n for n in ADAPTER_REGISTRY if n not in OPT_IN_ADAPTERS]


def load_adapters(names: list[str] | None = None, dry_run: bool = False) -> list[Adapter]:
    if not names:
        names = default_adapter_names()
    out: list[Adapter] = []
    for n in names:
        cls = ADAPTER_REGISTRY.get(n)
        if cls is None:
            log.warning(f"unknown adapter: {n}")
            continue
        out.append(cls(dry_run=dry_run) if cls is WatchAdapter else cls())
    return out


def run_ingest(adapter_names: list[str] | None = None, dry_run: bool = False) -> dict[str, dict]:
    """Run the pipeline. Returns the counts per adapter (also logged)."""
    repo = NotionRepo()
    dedup = SeenUrls()
    filter_cfg = load_filter()
    ignore = load_ignored_companies()
    adapters = load_adapters(adapter_names, dry_run)
    log.info(
        f"adapters: {[a.name for a in adapters]} | dry_run={dry_run} | "
        f"filter: allow={len(filter_cfg.allow)} block={len(filter_cfg.block)} "
        f"ignore_companies={len(ignore)}"
    )

    results: dict[str, dict] = {}
    run_keys: set[str] = set()  # company+role keys accepted in this run (all adapters)
    for adapter in adapters:
        log.info(f"[{adapter.name}] fetching")
        try:
            postings = list(adapter.fetch())
        except Exception as e:
            log.exception(f"[{adapter.name}] fetch failed: {e}")
            continue
        log.info(f"[{adapter.name}] {len(postings)} postings received")

        inserted = 0
        filtered = 0
        ignored = 0
        skipped_local = 0
        skipped_dup = 0
        skipped_notion = 0
        failed = 0

        for p in postings:
            url = str(p.url)

            # Not marked seen: removing a company from the ignore list brings its postings back.
            entry = ignored_company(p.company, ignore)
            if entry:
                log.debug(f"ignored (company on ignore list: {entry}): {p.company} — {p.role}")
                ignored += 1
                continue

            # Dream-target watch rows skip the keyword filter: always shown.
            passes, reason = (True, "watch") if p.source == "watch" else cheap_check(p, filter_cfg)
            # Web-search rows were already matched to phd.yaml by Claude (and cost tokens):
            # only filter.yaml's block list applies to them, not the allow list.
            if p.source == "websearch" and reason == "no_signal":
                passes, reason = True, "websearch"
            if not passes:
                log.debug(f"filtered ({reason}): {p.company} — {p.role}")
                filtered += 1
                if not dry_run:
                    dedup.mark_seen(url)  # don't re-evaluate next run
                continue

            if dedup.is_seen(url):
                skipped_local += 1
                continue

            # Same company + role from another source (or another search) = duplicate.
            # Watch rows reuse one role string per page, so they are never keyed.
            key = posting_key(p.company, p.role) if p.source != "watch" else None
            if key and (key in run_keys or dedup.key_seen_as(key)):
                log.debug(f"duplicate ({key}): {url}")
                skipped_dup += 1
                continue

            try:
                if repo.exists_by_url(url):
                    if not dry_run:
                        dedup.mark_seen(url, key)
                    if key:
                        run_keys.add(key)
                    skipped_notion += 1
                    continue
            except Exception as e:
                log.exception(f"[{adapter.name}] notion exists check failed: {e}")
                failed += 1
                continue

            if dry_run:
                log.info(f"[dry-run] would insert ({reason}): {p.company} — {p.role}")
                inserted += 1
                if key:
                    run_keys.add(key)
                continue

            try:
                page_id = repo.insert(p)
                dedup.mark_seen(url, key)
                if key:
                    run_keys.add(key)
                save_description(page_id, p.description)
                inserted += 1
                log.info(f"inserted ({reason}): {p.company} — {p.role}")
            except Exception as e:
                log.exception(f"[{adapter.name}] insert failed for {url}: {e}")
                failed += 1

        results[adapter.name] = dict(
            inserted=inserted, filtered=filtered, ignored=ignored, skipped_local=skipped_local,
            skipped_dup=skipped_dup, skipped_notion=skipped_notion, failed=failed,
        )
        log.info(
            f"[{adapter.name}] done | inserted={inserted} filtered={filtered} "
            f"ignored={ignored} skipped_local={skipped_local} skipped_dup={skipped_dup} "
            f"skipped_notion={skipped_notion} failed={failed}"
        )
    return results