"""Page watcher for dream-target groups that publish positions only on their website.

Pages are listed in data/profile/watch.yaml (name, url, keywords). On every run the page
text is fetched and the lines containing a keyword are hashed. When that hash
differs from the last run (data/watch_state.json), one posting is emitted:
"[watch] <name>: page changed", with the matched lines as summary. The URL gets
a "#<hash>" fragment, so each change is a new Notion row and an unchanged page
is skipped by the normal URL dedup.

Watch postings bypass filter.yaml (see pipeline/ingest.py): dream targets are
always shown.
"""
import hashlib
import json
from pathlib import Path
from typing import Iterable
import httpx
import yaml
from bs4 import BeautifulSoup
from jobs_agent.core.models import JobPosting
from jobs_agent.core.logging import get_logger

log = get_logger("adapters.watch")

WATCH_PATH = Path("data/profile/watch.yaml")
STATE_PATH = Path("data/watch_state.json")
DEFAULT_KEYWORDS = ["PhD", "doctoral", "Doktorand", "Promotion", "position", "Stelle", "vacancy"]
HEADERS = {"User-Agent": "jobsAgent/0.1"}


def load_watchlist(path: Path = WATCH_PATH) -> list[dict]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text()) or {}
    return [w for w in (data.get("watch") or []) if w and w.get("url")]


def _load_state(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def matched_lines(html: str, keywords: list[str]) -> list[str]:
    text = BeautifulSoup(html or "", "lxml").get_text("\n", strip=True)
    keys = [k.lower() for k in keywords]
    return [ln for ln in text.splitlines() if any(k in ln.lower() for k in keys)]


class WatchAdapter:
    name = "watch"

    def __init__(self, pages: list[dict] | None = None, state_path: Path = STATE_PATH,
                 timeout: float = 20.0, dry_run: bool = False):
        self.pages = pages if pages is not None else load_watchlist()
        self.state_path = state_path
        self.timeout = timeout
        self.dry_run = dry_run

    def fetch(self) -> Iterable[JobPosting]:
        if not self.pages:
            log.warning(f"no pages in {WATCH_PATH}")
            return
        state = _load_state(self.state_path)
        with httpx.Client(timeout=self.timeout, headers=HEADERS, follow_redirects=True) as client:
            for page in self.pages:
                name, url = page.get("name", page["url"]), page["url"]
                try:
                    r = client.get(url)
                    r.raise_for_status()
                except Exception as e:
                    log.exception(f"watch failed {name}: {e}")
                    continue
                lines = matched_lines(r.text, page.get("keywords") or DEFAULT_KEYWORDS)
                digest = hashlib.sha256("\n".join(lines).encode()).hexdigest()[:12]
                if not lines:
                    log.warning(f"  {name}: no line contains a keyword — wrong page or nothing posted")
                    continue
                if state.get(url) == digest:
                    log.info(f"  {name}: no change")
                    continue
                log.info(f"  {name}: changed ({len(lines)} matching lines)")
                state[url] = digest
                text = "\n".join(lines)
                yield JobPosting(
                    role=f"[watch] {name}: page changed",
                    company=page.get("company", name),
                    url=f"{url}#{digest}",
                    source="watch",
                    location=page.get("location", ""),
                    summary=text[:500],
                    description=text,
                    notes=f"watch={name} | hash={digest}",
                    status="not_started",
                )
        if not self.dry_run:
            _save_state(self.state_path, state)
