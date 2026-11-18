# jobAgent

Job search pipeline: Python does fetching, filtering, dedup and Notion I/O; Claude Code does scoring and CV/letter drafting. No LLM API calls in Python. Nothing runs on a timer: the user starts every run.

- Main entry: `/jobs` (`.claude/skills/jobs`). Tailoring only: `/cv-tailoring`. Learn from past applications: `/learn-applications` → `data/info/application_patterns.md`.
- PhD web search (`claude -p`, uses subscription usage): opt-in only, via `/jobs --phd-search` or `jobs_agent/scripts/phd_websearch.sh`; never part of a default ingest. Guide: `jobs_agent/websearch/README.md`.
- Run from the repo root inside the devcontainer: `python3 -m jobs_agent.scripts.<name>`. Dependencies: `requirements.txt`. Tests: `python3 -m pytest -q`.
- Notion DB is the source of truth. Status flow:
  `not_started` → (AI score) `approved_draft` | `needs_review` (user decides) | `low_fit` → `drafting` → `needs_final_review` → (user) `ready_to_submit` → `submitted` …
  `rejected` = the company rejected the user (set by the user). `closed` = posting expired. `ignore` = company on `data/profile/ignore_companies.yaml`.
- **This repo is public. `data/` and `logs/` are private and git-ignored.** User config: `data/profile/*.yaml` (examples in `jobs_agent/profile_examples/`). Profile and CV templates: `data/info/` (templates in `jobs_agent/info_templates/`). Auto drafts: `data/applications/00_drafts/`; other `data/applications/` folders are the user's manual workspace: do not modify them.
- Never copy content from `data/` into tracked files (code, docs, examples, tests, commit messages). Never commit with `--no-verify`; the pre-commit hook in `.githooks/` guards against leaks.
- Local runtime data: `data/seen.db` (URL cache), `data/descriptions/<page_id>.txt` (full posting text), `logs/agent.log`.
- Never read `.env`. Never write facts about the user that are not in `data/info/me_ai_master.md` §0–§14; §15 holds statements from past applications that need re-confirmation before use. No auto-submission, ever.
- More context for agents: `newusers.md`.
