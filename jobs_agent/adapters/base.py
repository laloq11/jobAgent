"""Adapter protocol. Each source implements .name and .fetch()."""
from typing import Protocol, Iterable
from jobs_agent.core.models import JobPosting


class Adapter(Protocol):
    name: str

    def fetch(self) -> Iterable[JobPosting]: ...
