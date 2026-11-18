"""Generic RSS / Atom adapter for job feeds (university portals, institutes).

Feeds are listed in data/profile/feeds.yaml. Each entry: name, url, and optional
company / location used when the feed items do not carry them.
Parsing: feedparser (installed in .devcontainer/Dockerfile).
"""
import time
from pathlib import Path
from typing import Iterable
import feedparser
import httpx
import yaml
from bs4 import BeautifulSoup
from jobs_agent.core.models import JobPosting
from jobs_agent.core.logging import get_logger

log = get_logger("adapters.rss")

FEEDS_PATH = Path("data/profile/feeds.yaml")
SUMMARY_MAX = 500
HEADERS = {"User-Agent": "jobsAgent/0.1"}


def load_feeds(path: Path = FEEDS_PATH) -> list[dict]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text()) or {}
    return [f for f in (data.get("feeds") or []) if f and f.get("url")]


def _strip_html(raw: str) -> str:
    return BeautifulSoup(raw or "", "lxml").get_text(" ", strip=True)


def _published(entry) -> str:
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", t) if t else ""


def _to_posting(entry, feed: dict) -> JobPosting | None:
    try:
        title = (entry.get("title") or "").strip()
        url = entry.get("link") or ""
        if not title or not url:
            return None
        desc = _strip_html(entry.get("summary") or entry.get("description") or "")
        published = _published(entry)
        notes_bits = [
            f"feed={feed['name']}",
            f"published={published}" if published else "",
        ]
        return JobPosting(
            role=title,
            company=feed.get("company", feed["name"]),
            url=url,
            source="rss",
            location=feed.get("location", ""),
            summary=desc[:SUMMARY_MAX],
            description=desc,
            notes=" | ".join(b for b in notes_bits if b),
            status="not_started",
        )
    except Exception as e:
        log.warning(f"skipping malformed item ({e}): {entry.get('link', '?')}")
        return None


class RssAdapter:
    name = "rss"

    def __init__(self, feeds: list[dict] | None = None, timeout: float = 20.0):
        self.feeds = feeds if feeds is not None else load_feeds()
        self.timeout = timeout

    def fetch(self) -> Iterable[JobPosting]:
        if not self.feeds:
            log.warning(f"no feeds in {FEEDS_PATH}")
            return
        with httpx.Client(timeout=self.timeout, headers=HEADERS, follow_redirects=True) as client:
            for feed in self.feeds:
                log.info(f"feed: {feed['name']}")
                try:
                    r = client.get(feed["url"])
                    r.raise_for_status()
                except Exception as e:
                    log.exception(f"feed failed {feed['name']}: {e}")
                    continue
                parsed = feedparser.parse(r.content)
                if parsed.bozo and not parsed.entries:
                    log.warning(f"  {feed['name']}: not a valid feed ({parsed.bozo_exception})")
                    continue
                log.info(f"  → {len(parsed.entries)} items")
                for entry in parsed.entries:
                    p = _to_posting(entry, feed)
                    if p is not None:
                        yield p
