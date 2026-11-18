"""Shared HTTP for the HTML adapters (cea, euraxess, findaphd, nadigest, ...).

User-Agent jobsAgent/0.1, timeout 20 s, retry on 5xx / 429 / network errors
(same policy as greenhouse.py), and at most one request per second per host.
"""
import time
from urllib.parse import urlsplit
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

HEADERS = {"User-Agent": "jobsAgent/0.1"}
TIMEOUT = 20.0


def _is_retriable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.RequestError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500 or exc.response.status_code == 429
    return False


class PoliteClient:
    """httpx.Client wrapper. `transport` is for tests (httpx.MockTransport)."""

    def __init__(self, min_interval: float = 1.0, timeout: float = TIMEOUT,
                 transport: httpx.BaseTransport | None = None):
        self.client = httpx.Client(timeout=timeout, headers=HEADERS, follow_redirects=True,
                                   transport=transport)
        self.min_interval = min_interval
        self._last: dict[str, float] = {}

    def __enter__(self) -> "PoliteClient":
        return self

    def __exit__(self, *exc) -> None:
        self.client.close()

    def _throttle(self, url: str) -> None:
        host = urlsplit(url).netloc
        last = self._last.get(host)
        if last is not None:
            wait = self.min_interval - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
        self._last[host] = time.monotonic()

    def fetch(self, url: str) -> httpx.Response:
        """One throttled GET without retry and without raising on 4xx / 5xx (robots.txt checks)."""
        self._throttle(url)
        return self.client.get(url)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception(_is_retriable),
        reraise=True,
    )
    def get(self, url: str, params: dict | None = None) -> httpx.Response:
        self._throttle(url)
        r = self.client.get(url, params=params)
        r.raise_for_status()
        return r
