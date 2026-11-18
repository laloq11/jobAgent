"""SQLite-backed local dedup before hitting Notion.

Two keys, both in data/seen.db:
- seen_urls: the posting URL (per source).
- seen_keys: normalised company + role (see posting_key), so the same PhD
  posted on EURAXESS, FindAPhD, CFD Online and jobs.ac.uk is inserted once.
"""
import re
import sqlite3
import time
import unicodedata
from pathlib import Path

DB_PATH = Path("data/seen.db")

# (m/w/d), (f/m/x), (w/m/d), (m/f/div), (all genders), (gn*) ... and bare m/w/d.
_GENDER_TAGS = re.compile(
    r"\(\s*(?:[mwfdx]|div|divers)(?:\s*[/|,]\s*(?:[mwfdx]|div|divers))+\s*\)"
    r"|\(\s*(?:all genders|gn\*?|w\*m|m\*w)\s*\)"
    r"|\b[mwfd]\s*/\s*[mwfd]\s*/\s*(?:[mwfdx]|div)\b",
    re.IGNORECASE,
)
# Role words that alone do not identify a posting. A role made only of these
# ("PhD Position (m/w/d)") gets no key: same company + generic title is often
# two different offers.
_GENERIC = {
    "phd", "ph", "d", "position", "positions", "doctoral", "doctorate", "researcher",
    "researchers", "student", "students", "studentship", "studentships", "candidate",
    "candidates", "research", "associate", "assistant", "fellow", "fellowship", "project",
    "early", "stage", "esr", "dc", "r1", "fully", "funded", "open", "vacancy", "offer",
    "thesis", "these", "doktorand", "doktorandin", "doktorandinnen", "promotion",
    "promotionsstelle", "wissenschaftliche", "wissenschaftlicher", "mitarbeiterin",
    "mitarbeiter", "mitarbeiter_in", "r", "innen", "in", "of", "on", "for", "the", "a", "an", "and",
    "at", "with", "to", "im", "bereich", "der", "die", "das", "und", "fur", "zur", "zum",
    "de", "du", "des", "en", "la", "le", "et",
}


def normalise(text: str) -> str:
    """Lowercase, no accents, no gender tags, no punctuation, single spaces."""
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = _GENDER_TAGS.sub(" ", t.lower())
    t = re.sub(r"[\W_]+", " ", t)
    return " ".join(t.split())


def posting_key(company: str, role: str) -> str | None:
    """Cross-source dedup key, or None when company or role is too generic."""
    c, r = normalise(company), normalise(role)
    if not c or not r or not (set(r.split()) - _GENERIC):
        return None
    return f"{c}|{r}"


class SeenUrls:
    def __init__(self, path: Path = DB_PATH):
        path.parent.mkdir(exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS seen_urls (url TEXT PRIMARY KEY, seen_at INTEGER)"
        )
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS seen_keys (key TEXT PRIMARY KEY, url TEXT, seen_at INTEGER)"
        )
        self.conn.commit()

    def is_seen(self, url: str) -> bool:
        cur = self.conn.execute("SELECT 1 FROM seen_urls WHERE url = ?", (url,))
        return cur.fetchone() is not None

    def key_seen_as(self, key: str) -> str | None:
        """URL first stored under this company+role key, or None."""
        row = self.conn.execute("SELECT url FROM seen_keys WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def mark_seen(self, url: str, key: str | None = None) -> None:
        now = int(time.time())
        self.conn.execute("INSERT OR IGNORE INTO seen_urls (url, seen_at) VALUES (?, ?)", (url, now))
        if key:
            self.conn.execute(
                "INSERT OR IGNORE INTO seen_keys (key, url, seen_at) VALUES (?, ?, ?)", (key, url, now)
            )
        self.conn.commit()

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM seen_urls").fetchone()[0]
