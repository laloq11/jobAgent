#!/usr/bin/env bash
# PhD web search, part 1 of 2: Claude Code (claude -p) searches the web and the
# claude.ai Indeed connector for PhD postings that match data/profile/phd.yaml
# and writes data/websearch/results/<stamp>.json.
# Part 2 is the opt-in `websearch` adapter (plain Python, no LLM): run_ingest --adapters
# websearch re-fetches every result and drops anything whose page does not contain the
# claimed title.
#
# Uses your Claude subscription's usage. Started only by hand or by `/jobs --phd-search`,
# never on a timer and never by a regular ingest. Docs: jobs_agent/websearch/README.md
# Settings: data/profile/websearch.yaml (usage cap, limits, 7-day guard).
#
# Usage: bash jobs_agent/scripts/phd_websearch.sh [--force]
# Exit: 0 saved | 3 skipped (7-day guard) | 4 usage cap reached | 1 failed
# Then: python3 -m jobs_agent.scripts.run_ingest --adapters websearch [--dry-run]
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1

RUN_DIR=$(python3 -m jobs_agent.websearch.files prepare "$@")
rc=$?
[ $rc -ne 0 ] && exit $rc
# shellcheck source=/dev/null
source "$RUN_DIR/args.sh"   # MODEL BUDGET TOOLS ALLOWED RAW

for attempt in 1 2; do
  echo "PhD web search: attempt $attempt (model $MODEL, usage cap \$$BUDGET estimate)" >&2
  claude -p "$(cat "$RUN_DIR/prompt.md")" \
    --model "$MODEL" \
    --max-budget-usd "$BUDGET" \
    --output-format json \
    --json-schema "$(cat "$RUN_DIR/schema.json")" \
    --system-prompt "$(cat "$RUN_DIR/system.md")" \
    --tools "$TOOLS" \
    --allowedTools "$ALLOWED" \
    --no-session-persistence \
    > "$RAW" 2> "$RAW.stderr"
  python3 -m jobs_agent.websearch.files collect "$RAW"
  rc=$?
  [ $rc -eq 0 ] && exit 0
  [ $rc -eq 4 ] && exit 4      # usage cap: a retry would use it again
  [ "$attempt" -eq 1 ] && echo "retrying once" >&2
done
exit 1
