# PhD web search

Claude Code searches the web, a few job portals and the claude.ai Indeed connector for
open PhD positions that match `data/profile/phd.yaml`. Plain Python then checks
every result against its page before anything reaches Notion. PhD positions only.

It uses your Claude subscription's usage, so it runs **only when you start it**.

## Independent of the regular adapters

| Rule | How it is enforced |
|---|---|
| A normal ingest never touches it | `websearch` is in `OPT_IN_ADAPTERS` (`pipeline/ingest.py`): `run_ingest` without `--adapters`, and `/jobs` without `--phd-search`, skip it |
| The search (`claude -p`) starts only from `jobs_agent/scripts/phd_websearch.sh` | started by you, or by `/jobs --phd-search`. No timer, no cron |
| No Python code calls Claude | Python only renders the prompt and reads the saved results |
| The regular adapters don't depend on it | none of them imports the web search code |
| At most one search per 7 days | `min_days_between_runs` guard; `--force` overrides it |

`jobs_agent/tests/test_websearch_independent.py` fails if any of the first four rules breaks.

## How to run it

| What | Command |
|---|---|
| Full pipeline plus the search | `/jobs --phd-search` |
| Search only (respects the 7-day guard) | `bash jobs_agent/scripts/phd_websearch.sh` |
| Search again within 7 days | `bash jobs_agent/scripts/phd_websearch.sh --force` |
| Show what would go to Notion | `python3 -m jobs_agent.scripts.run_ingest --adapters websearch --dry-run` |
| Insert into Notion | `python3 -m jobs_agent.scripts.run_ingest --adapters websearch` |

By hand: run the search, then the `--dry-run` ingest, then the real ingest. `/jobs --phd-search` does the search and the real ingest for you, as its step 0b.

The ingest re-reads every result file from the last `read_days` days. Postings already in
`data/seen.db` cost no request, so running it twice is harmless.

### Exit codes of `phd_websearch.sh`
| Code | Meaning | What to do |
|---|---|---|
| 0 | Results saved | Run the ingest |
| 3 | Skipped: last search is less than `min_days_between_runs` old | Wait, or use `--force` |
| 4 | Usage cap (`max_budget_usd`) reached; nothing saved | Raise the cap or lower the soft limits |
| 1 | Claude run failed twice | See `data/websearch/runs/<stamp>/claude_output.json` and `.stderr` |

## Usage

- **Not charged:** each run uses part of your subscription's usage limits, the same limits as `/jobs` scoring and drafting. Nothing is billed, unless you have turned on paid extra usage.
- **The dollar figure:** the script prints Claude Code's usage estimate at API list prices (`costBasis: list`). Use it to compare runs. `max_budget_usd` caps this estimate, and a run that hits the cap saves nothing.
- **Where the tokens go:** about half are Haiku, which reads search results and fetched pages inside Claude Code. The other half are the main model (`model:`), which plans the searches and picks the results.

First runs (17 Nov 2026, Sonnet):

| Run | Estimate | Web searches | Postings saved | What changed after it |
|---|---|---|---|---|
| 1 | $0.36 | 16 | 0 | "published in the last 14 days" removed: most pages show no date |
| 2 | $0.47 | 19 | 1 | portal hints added |
| 3 | $0.35 | 12 | 0 | prompt turned into ordered steps; WebFetch made optional |
| 4 | $0.54 | 23 | 1 | – |

The 2 saved postings (Lund University, KIT) both passed the page check.

## How it works

```
phd_websearch.sh                                     run_ingest --adapters websearch
  websearch/files.py prepare                           adapters/websearch.py (no LLM)
    7-day guard, prompt from phd.yaml + websearch.yaml    reads results/*.json (last read_days days)
  claude -p (WebSearch, WebFetch, Indeed connector)        fetches each URL again, checks it
    capped by max_budget_usd                               -> filter.yaml block list -> dedup -> Notion
  websearch/files.py collect
    -> data/websearch/results/<stamp>.json
```

**What Claude is told** (`websearch/prompt_template.md`, rendered by `files.py`):
1. Run `site:` searches on the `portal_hints` portals.
2. Run Indeed searches in `indeed_countries`.
3. Run topic searches in English and German, until the search budget is used.
4. Report only the institution's own page, never a page on an `original_only` site.
5. Report postings that are still open, at any match strength.
6. Never invent anything. Leads it can't confirm go in `notes`.

**What Part 2 keeps from Claude:** the URL, the title (once checked against the page), the
institution and `found_via`. The description and summary are the fetched page text. Location
and deadline are kept only if they appear on the page. `published=` in Notes is the search date,
used by `close_stale` for its 60-day rule.

**Keyword filter:** these rows skip `filter.yaml`'s `allow` list, because Claude already matched them to `phd.yaml`. The `block` list still applies.

### Why a result is dropped (in the log line `N results: K verified, dropped/skipped {...}`)
| Reason | Meaning |
|---|---|
| `invalid` | missing title, institution or URL |
| `original_only` | URL on LinkedIn, Indeed, EURAXESS, FindAPhD, CFD Online or Academic Positions |
| `seen` | already in `data/seen.db` (skipped, no request) |
| `robots` | the site's `robots.txt` disallows the page |
| `http` | 403 / 404 / timeout |
| `bot_check` | Cloudflare or similar challenge page |
| `unreadable` | broken PDF etc. |
| `title_not_on_page` | under 80 % of the title's words appear on the page (made-up or wrong page) |
| `deadline_passed` | the deadline Claude reported is on the page and already past |

## Settings: `data/profile/websearch.yaml`

| Key | Default | Meaning |
|---|---|---|
| `min_days_between_runs` | 7 | guard instead of a timer |
| `max_posting_age_days` | 60 | drop a posting only if its page shows an older publication date |
| `read_days` | 14 | which result files the ingest reads |
| `model` | sonnet | main model: `haiku` (less usage, may follow the search plan less carefully), `sonnet`, `opus` |
| `max_budget_usd` | 3.00 | cap on the usage estimate per attempt |
| `max_results`, `max_web_searches`, `max_page_fetches` | 25, 20, 25 | soft limits written into the prompt |
| `use_indeed`, `max_indeed_searches`, `indeed_countries` | true, 6, DE AT CH NL | Indeed connector, used to find postings only |
| `portal_hints` | AcademicTransfer, Varbi, Jobbnorge, academics.de, ETH | portals for `site:` searches (checked: no bot check, robots.txt allows job pages) |
| `extra_queries` | [] | extra search ideas |
| `original_only` | LinkedIn, Indeed, EURAXESS, FindAPhD, CFD Online, Academic Positions | sites Python cannot fetch: Claude must report the original page |

The search topics come from `phd.yaml`. Edit that file, not the prompt.

## Files
| Path | What |
|---|---|
| `jobs_agent/scripts/phd_websearch.sh` | Part 1 launcher, the only caller of `claude -p` |
| `jobs_agent/websearch/files.py` | guard, prompt rendering, saving results (no LLM) |
| `jobs_agent/websearch/prompt_template.md`, `schema.json` | the prompt and the output format |
| `jobs_agent/adapters/websearch.py` | Part 2, the check |
| `data/websearch/results/<stamp>.json` | saved results with Claude's `notes` (leads it could not confirm) |
| `data/websearch/runs/<stamp>/` | the exact prompt, arguments and raw `claude -p` output of each run |

`data/websearch/` is git-ignored.

## Known limits
- **Few results:** general web search mostly finds postings that have already closed, so expect 0–2 new postings per run. The dedicated adapters (jobs.ac.uk, CEA, NA-Digest) find far more.
- **Indeed:** links change on every call, and `/viewjob` pages are disallowed by Indeed's `robots.txt`. Indeed is only used to find postings, and a result counts only once its original page is found.
- **XING:** posting pages are allowed by `robots.txt` but untested.
- **Claude's own fetches:** its WebFetch sometimes gets a 403 where Python's fetch would work, and vice versa. Claude reports a result even when its own fetch fails, and Part 2 decides.
