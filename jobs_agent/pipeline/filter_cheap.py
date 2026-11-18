"""Cheap keyword filter with word-boundary matching."""
import re
from jobs_agent.core.models import JobPosting
from jobs_agent.core.profile_loader import FilterConfig


def _haystack(p: JobPosting) -> str:
    return " ".join([p.role, p.summary, p.notes]).lower()


def _compile(terms: list[str]) -> list[tuple[str, re.Pattern]]:
    return [(t, re.compile(r"\b" + re.escape(t) + r"\b", re.IGNORECASE)) for t in terms]


_cache: dict[int, tuple[list, list]] = {}


def _get_patterns(cfg: FilterConfig):
    key = id(cfg)
    if key not in _cache:
        _cache[key] = (_compile(cfg.block), _compile(cfg.allow))
    return _cache[key]


def _norm(name: str) -> str:
    return re.sub(r"[\W_]+", "", name.lower())


def ignored_company(company: str, ignore: list[str]) -> str | None:
    """Return the ignore-list entry that `company` matches, or None.
    Match = entry contained in the company name, ignoring case, spaces and
    punctuation, so "proxima fusion" matches "proxima-fusion" and
    "Proxima Fusion GmbH"."""
    name = _norm(company or "")
    for entry in ignore:
        key = _norm(entry)
        if key and key in name:
            return entry
    return None


def check(p: JobPosting, cfg: FilterConfig) -> tuple[bool, str]:
    """Return (passes, reason)."""
    hay = _haystack(p)
    block_p, allow_p = _get_patterns(cfg)
    for term, pat in block_p:
        if pat.search(hay):
            return False, f"block:{term}"
    for term, pat in allow_p:
        if pat.search(hay):
            return True, f"allow:{term}"
    return False, "no_signal"