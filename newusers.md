# Goal

This repo fetches job postings from a handful of free/public APIs, filters
them down with keyword rules, dedupes them, and writes the survivors into a
Notion database as review rows. Scoring and CV / cover-letter drafting are
done by Claude Code (no LLM API calls in Python) through the `/jobs` skill
in `.claude/skills/`, which I start by hand — nothing runs on a timer.
**There is no auto-submission.** Setup steps for humans are in `README.md`;
this file is the agent-facing reference.

## How this repo is meant to be used

You are not expected to hand-edit Python here. You talk to an AI coding
agent sitting in the repo (Claude Code, OpenAI Codex CLI, or anything
comparable) and describe what you want — a new job source, a new filter
keyword, a new company to watch — and it makes the change. The sections
below are written so that agent (and you) never have to ask "where do I
even start."

---

## What do I need to start? (`.env`)

Copy `.env.example` to `.env` at the repo root (git-ignored via the `.env*`
pattern, and blocked by the pre-commit hook — never commit it). `jobs_agent/core/config.py` is the single
source of truth for what's read; these are the keys:

| Key | Required? | Used for | Where to get it |
|---|---|---|---|
| `NOTION_TOKEN` | yes | all Notion reads/writes | [notion.so/my-integrations](https://www.notion.so/my-integrations) → "New integration" → copy the "Internal Integration Secret". Then open your Notion database → `...` menu → "Connections" → add the integration, or it can't see the DB. |
| `NOTION_DB_ID` | yes | which database to write to | the 32-char id in the database URL: `notion.so/<workspace>/<DB_ID>?v=...` |
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | only if using the Adzuna adapter | Adzuna job search | free account at [developer.adzuna.com](https://developer.adzuna.com/) |
| `SMTP_HOST` / `SMTP_PORT` | only if using `run_notify` | sending the digest email | defaults to Outlook's SMTP; for Gmail use an "app password", not your normal password |
| `SMTP_USER` / `SMTP_PASSWORD` | only if using `run_notify` | SMTP login | your mailbox + app password |
| `NOTIFY_TO` / `NOTIFY_FROM` | only if using `run_notify` | envelope addresses | defaults to `SMTP_USER` if unset |

Adapters with no key requirement (Arbeitnow, Bundesagentur, Greenhouse,
Ashby) work with zero setup beyond `NOTION_TOKEN`/`NOTION_DB_ID`.

`.env` is read two ways depending on where you run:
- devcontainer: `runArgs: ["--env-file=${localWorkspaceFolder}/.env"]` in `.devcontainer/devcontainer.json`
- outside it: `core/config.py` reads `.env` from the current directory (pydantic-settings `env_file`)

Python deps live in `requirements.txt` (the Dockerfile installs it). If
you (or an agent) add a new dependency, add it there and **rebuild the
container** (`Dev Containers: Rebuild Container`, or
`docker build -t jobagent:latest -f .devcontainer/Dockerfile .`);
otherwise the devcontainer keeps running the old image.

---

## What do I need from Notion

1. Create a full-page database in your workspace (any name, e.g. "Job Pipeline")
   with the properties listed below (names and types must match).
2. Create an integration and connect it to the database (see `.env` table above).
3. Copy the database id into `NOTION_DB_ID`.
4. Run `python3 -m jobs_agent.scripts.setup_check`: it compares the database
   with what the code writes and lists every missing or mistyped property.

The database's properties must match exactly what
`jobs_agent/core/notion_repo.py::_posting_to_props` writes — if you rename
a column in Notion, update that function (or ask the agent to). Current
properties (Notion "Text" type unless stated): `Role` (title), `Company`,
`url` (URL), `Source` (select), `Location`, `Deadline` (date),
`Fit Score` (number), `Summary`, `Status` (select), `cover_letter_path`,
`cv_path`, `todo`, `Application Date` (date), `1st interview` (date),
`1st answer` (select: Yes / No), `Notes`.

The `Select` options for `Source` and `Status` must include every value in
the `Source`/`Status` `Literal`s in `jobs_agent/core/models.py` — those two
enums are the single source of truth; if you add a new source/status in
code, add the matching option in Notion too (or Notion will just create it
implicitly on insert, but it won't have the color/order you want).

This repo also requires a Notion integration on the newer "data source"
API model (2025-09-03+) — `notion_repo.py` calls
`self.client.databases.retrieve(...)` and reads `data_sources[0]`. If that
comes back empty, your integration/workspace predates data sources.

---

## What information should be filled in `data/profile/`

`data/profile/` (git-ignored) holds your own copies, created from
`jobs_agent/profile_examples/` by `python3 -m jobs_agent.scripts.init_user`.
Edit the copies; the examples are only the starting point.


- **`data/profile/companies.yaml`** — `allow:` is the only list you hand-edit:
  display names of companies you want watched (any casing/spacing). The
  `confirmed:` and `confirmed_ashby:` sections are **auto-managed** — do
  not hand-edit them. They're regenerated by:
  ```bash
  python3 -m jobs_agent.scripts.probe_greenhouse   # writes confirmed:
  python3 -m jobs_agent.scripts.probe_ashby        # writes confirmed_ashby:
  ```
  These scripts turn each `allow` name into a slug and check whether that
  company has a public Greenhouse/Ashby job board. Only companies that
  turn up in `confirmed`/`confirmed_ashby` actually get scraped — being in
  `allow` alone does nothing.

- **`data/profile/filter.yaml`** — the cheap keyword filter
  (`jobs_agent/pipeline/filter_cheap.py`). Case-insensitive, word-boundary
  matching over `role + summary + notes`. Rule: any `block` hit rejects
  outright; else any `allow` hit accepts; else rejected (`no_signal`). This
  is what decides whether a fetched posting is worth putting in front of
  you at all — tune it before tuning anything else.

- **`data/profile/ignore_companies.yaml`** — hand-edited `ignore:` list of
  companies you never want to see (e.g. ones that already rejected you), with
  a comment per entry saying why. A company matches if its name contains an
  entry, ignoring case, spaces and punctuation. `run_ingest` does not insert
  their postings, and `close_stale` sets their open rows (`not_started`,
  `needs_review`, `approved_draft`) to status `ignore`, with a todo pointing
  back to this file. Rows further along are left alone.

- **`data/profile/searches.yaml`** — keyword + location + radius queries
  for the two search-based adapters (`adzuna:` and `bundesagentur:`
  sections), since those search a whole job board rather than listing a
  company's postings. Searches without a location cover the whole country;
  Adzuna entries can set `country` (at, ch, nl, be, gb, ...).

- **`data/profile/feeds.yaml`** — RSS / Atom job feeds read by `adapters/rss.py`
  (e.g. a university job portal's keyword feeds). Add an entry (name, url,
  optional company / location) and check it with
  `run_ingest --adapters rss --dry-run`.

- **`data/profile/watch.yaml`** — dream-target group pages watched by
  `adapters/watch.py`. A row `[watch] <name>: page changed` appears when the
  lines containing PhD / position keywords change. These rows skip
  `filter.yaml`. Last seen state: `data/watch_state.json`.

- **`data/profile/phd.yaml`** — what you want from a PhD (topics, exclusions,
  location, contract). The `/jobs` scoring step uses it for Track B postings
  instead of the industry rubric.

- **PhD sources** (adapter name → config):
  - `cea` (`adapters/cea.py`, `data/profile/cea.yaml`) — CEA thesis offers, HTML.
    Reads every list page (the site wraps to page 1 after the last one, so
    paging stops at the first page without a new reference) and fetches the
    detail page only for offers whose category / title passes `cea.yaml`.
    No publication date on the site, so no `published=` in Notes.
  - `jobsacuk` (`adapters/jobsacuk.py`, `data/profile/jobsacuk.yaml`) — jobs.ac.uk
    search with the site's PhD filter, one search per keyword; text, dates,
    employer and location from the detail page's JSON-LD. jobs.ac.uk has no
    RSS feeds any more. Results already in `seen.db` get no detail request.
  - `nadigest` (`adapters/nadigest.py`, no config) — NA-Digest web archive,
    newest 3 weekly issues, PhD items only; `url` = issue URL + `#<item>`.
  - Checked and **not usable** (Nov 2026): CFD Online, FindAPhD and Academic
    Positions answer with a Cloudflare challenge; EURAXESS `robots.txt`
    disallows `/jobs/*` and every URL with a query string. Don't work around
    either.
  - `websearch` — PhD web search, **opt-in and independent of the other
    adapters**: full guide in `jobs_agent/websearch/README.md`. Part 1,
    `scripts/phd_websearch.sh`, runs `claude -p` (WebSearch, WebFetch, the
    claude.ai Indeed connector); it uses subscription usage, so it starts only
    by hand or with `/jobs --phd-search`, at most once per 7 days. Part 2, the
    `websearch` adapter, is plain Python and runs only when named
    (`run_ingest --adapters websearch`): it re-fetches every result and drops
    it unless the page contains the claimed title. A default `run_ingest`
    never includes it (`OPT_IN_ADAPTERS` in `pipeline/ingest.py`, enforced by
    `tests/test_websearch_independent.py`). Settings: `data/profile/websearch.yaml`.
  - `adapters/_http.py` — shared client for these HTML adapters: retry on
    5xx / 429, at most 1 request per second per host.
- **Cross-source dedup** — besides the URL, `data/seen.db` stores a key of
  normalised company + role (`core/dedup.py::posting_key`: lowercase, no
  accents / punctuation / gender tags like `(m/w/d)`). A posting whose key is
  already there, or was accepted earlier in the same run, is counted as
  `skipped_dup`. Roles made only of generic words ("PhD Position (m/f/d)")
  and `watch` rows get no key.
- **Tests** — offline, `python3 -m pytest -q` (`jobs_agent/tests/`, fixtures in
  `jobs_agent/tests/fixtures/`, HTTP via `httpx.MockTransport`).

---

## How to add more APIs into the pipeline

Every source is a small adapter class implementing the `Adapter` protocol
in `jobs_agent/adapters/base.py`: a `.name` attribute and a `.fetch()`
method that yields `JobPosting` objects (`jobs_agent/core/models.py`).
Look at `jobs_agent/adapters/arbeitnow.py` for the simplest example. To add
one: drop a new file in `jobs_agent/adapters/`, then register the class in
`ADAPTER_REGISTRY` in `jobs_agent/pipeline/ingest.py`. That's it — dedup,
filtering, and Notion insert are handled generically by the pipeline.

Just tell the agent the API's docs URL (or paste a sample response) and
which fields map to `JobPosting`; it's simple enough that no further
explanation is needed here.

### Testing new adapters

**Always use `--dry-run` when adding or changing an adapter — this is the
most useful thing in this whole repo.** It runs the real fetch against the
live API and still checks Notion for existing rows (so counts are
accurate), but never writes to Notion and never marks the local dedup
cache. Nothing you do under `--dry-run` can corrupt the board.

```bash
python3 -m jobs_agent.scripts.run_ingest --adapters <your_adapter_name> --dry-run
```

Only drop `--dry-run` once the log output for that adapter looks right
(sane `inserted`/`filtered` counts, no exceptions).

### Finding new APIs to add

Every existing adapter falls into one of two shapes — look for a candidate
that fits one of them before writing any code:

1. **Company-board APIs** (`greenhouse.py`, `ashby.py`) — a specific
   company's careers page is actually rendered from a public JSON endpoint.
   Most ATS (applicant-tracking-system) vendors expose one per company,
   keyed by a company slug, no auth required. To find these: open a target
   company's `/careers` or `/jobs` page, open browser devtools → Network →
   XHR/Fetch, and reload — you're looking for a request that returns raw
   JSON with the job list. The URL pattern (e.g.
   `boards-api.greenhouse.io/v1/boards/<slug>/jobs`,
   `api.ashbyhq.com/posting-api/job-board/<slug>`) tells you the ATS
   vendor. Common ones besides Greenhouse/Ashby: **Lever**
   (`api.lever.co/v0/postings/<slug>`), **SmartRecruiters**, **Personio**,
   **Recruitee**, **Workable** — all follow the same "slug → JSON list"
   shape and are worth adding the exact same way (adapter class + a
   `probe_<vendor>.py` script that checks each name in
   `companies.yaml:allow` and writes a `confirmed_<vendor>:` section).
   This shape is the best fit when you have a specific list of employers
   you care about, regardless of how niche.

2. **Search/aggregator APIs** (`bundesagentur.py`, `adzuna.py`,
   `arbeitnow.py`) — a job board that indexes many employers and exposes a
   documented public search API (keyword + location in, paginated JSON
   list out). These don't need a `companies.yaml` list; instead they need
   a hand-edited list of keyword/location/radius combos in
   `data/profile/searches.yaml` (one section per adapter).
   Good candidates: national job agencies (like
   Bundesagentur), Adzuna, JSearch/RapidAPI, Indeed's affiliate feed, We
   Work Remotely, RemoteOK. Check the docs page directly (search
   `"<name> job search API docs"`) rather than reverse-engineering the
   frontend, since these are meant to be integrated against and usually
   require a free API key.

### Requirements for adapters — and how to vet them

Don't write adapter code first and find out it's a dead end. Vet the
candidate with a single `curl` before anything touches Python — this is
the same instinct as `--dry-run`, just one step earlier. For each
requirement below, here's the concrete check:

- **No-auth or single free-tier API key.**
  ```bash
  curl -sD - -o /dev/null "https://<candidate-endpoint>"
  ```
  Look at the status line. `200` with no headers about a key = free to use
  immediately. `401`/`403` means it wants a header/query-param key — check
  the docs for whether that key is a free self-serve signup (fine, like
  Adzuna) or behind a sales call / paid tier (reject, not worth it here).

- **Returns structured JSON, not HTML.**
  ```bash
  curl -s "https://<candidate-endpoint>" | python3 -m json.tool | head -60
  ```
  If `json.tool` errors out, you got HTML/an error page back — either the
  URL is wrong (check devtools again) or this source doesn't have a real
  API and would need Playwright scraping, which nothing in this repo does
  today. Don't build that; find a different source instead.

- **Has a stable per-posting URL.** Run the same curl twice, a minute or
  two apart, and diff the `id`/`url` fields for a posting present in both:
  ```bash
  curl -s "https://<candidate-endpoint>" | python3 -c "import json,sys; [print(j.get('id'), j.get('url') or j.get('absolute_url')) for j in json.load(sys.stdin).get('jobs', [])[:5]]"
  ```
  If the same job gets a different id/url on each call (session tokens,
  signed links, etc.), `notion_repo.py`'s `exists_by_url` dedup will treat
  every ingest run as "new" and re-insert the same posting forever —
  that's a hard reject, not something to fix later.

- **Enough fields to fill `JobPosting`.** From that same JSON dump, check
  you can see at minimum: a role/title string, a company name (either in
  the payload or implied by the slug you queried), a posting URL, and
  *some* text to run the keyword filter against (description, summary, or
  tags — `filter_cheap.py` needs something to match on, or every posting
  from this source gets rejected as `no_signal`). Location/deadline are
  optional — `JobPosting` defaults them.

- **Rate limit tolerant of a few calls a day.** Check the docs' stated
  limit, or the response headers (`X-RateLimit-Limit`, `Retry-After`,
  etc.). Ingest runs once per `/jobs` run, so anything above "a handful of
  requests per day" clears the bar with room to spare.

Once a candidate clears all five, paste the docs URL (or the raw JSON dump
you already have from the curl above) to the agent — that's enough for it
to write the adapter, the `_to_posting()` field mapping, and (for a
company-board API) the matching `probe_<vendor>.py` script.

---

## Things a new agent should know without asking

- **Pipeline steps** (orchestrated by `/jobs`, see `.claude/skills/jobs/SKILL.md`):
  `run_ingest` (fetch → cheap filter → local SQLite dedup (`data/seen.db`)
  → Notion dedup → insert as `not_started`, full text cached in
  `data/descriptions/`) → Claude scores rows (`pending`, `update_row`) →
  Claude drafts CV + CL for `approved_draft` rows into
  `data/applications/00_drafts/` (`cv-tailoring` skill, `build_pdf`) →
  `run_notify` (email of the rows touched in this run, with the run report
  from `logs/run_report.md` on top; that file is overwritten every run).
- **`cleanup_notion.py`** bulk-trashes rows by status (default
  `not_started`), dry-run unless `--confirm` is passed. Useful for
  clearing out a review backlog you've decided to skip.
- **Deployment**: none. Runs are started by hand from Claude Code inside
  the devcontainer (`/jobs`).
- **Logs**: `jobs_agent/core/logging.py` writes to console + a rotating
  file at `logs/agent.log` (5 × 2MB backups). Check there first if a
  run misbehaved and you don't have terminal output.
- **`data/` is private and git-ignored.** `data/info/` holds the user's
  profile (`me_ai_master.md`) and CV / letter templates; `data/applications/`
  their per-application files. The pipeline only reads `data/info/` and only
  writes to `data/applications/00_drafts/`; every other folder is a manual
  workspace. Never copy anything from `data/` into a tracked file, and never
  commit with `--no-verify`: the pre-commit hook (`.githooks/pre-commit`) is
  what keeps personal data out of the public repo.
- **No auto-submission, ever.** Don't add code that submits applications
  automatically, even if the infrastructure would make it easy.
