"""HTTP helpers: rate limiting, retries, and secret redaction.

Errors raised from here never contain API keys: URLs and messages are redacted.
"""
from __future__ import annotations

import re
import threading
import time
from urllib.parse import urlencode

import requests

SECRET_PARAMS = {"apikey", "api_key", "token", "key"}
_SECRET_RE = re.compile(r"(?i)((?:apikey|api_key|token|key)=)[^&\s'\"]+")


class DataSourceError(Exception):
    """A fetch failed. `status` is the HTTP status when there was one."""

    def __init__(self, source: str, message: str, status: int | None = None):
        self.source = source
        self.status = status
        super().__init__(f"{source}: {redact(message)}")


def redact(text: str) -> str:
    return _SECRET_RE.sub(r"\1***", str(text))


def cache_key(url: str, params: dict | None = None) -> str:
    """A stable key for a request with secret parameters removed."""
    clean = {k: v for k, v in sorted((params or {}).items()) if k.lower() not in SECRET_PARAMS}
    return f"{url}?{urlencode(clean)}" if clean else url


class RateLimiter:
    """Thread-safe minimum interval between requests (e.g. SEC: 10 req/s)."""

    def __init__(self, per_second: float):
        self.interval = 1.0 / per_second
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self.interval
        if delay > 0:
            time.sleep(delay)


COOLDOWN_SECONDS = 600  # after a source exhausts its retries on HTTP 429 (e.g. a daily quota), fail fast for a while
_cooldown: dict[str, float] = {}


def get(source: str, url: str, *, params: dict | None = None, headers: dict | None = None,
        limiter: RateLimiter | None = None, timeout: float = 30, retries: int = 3,
        session: requests.Session | None = None) -> requests.Response:
    sess = session or requests
    last_err: Exception | None = None
    until = _cooldown.get(source)
    if until is not None and time.monotonic() < until:
        raise DataSourceError(source, f"rate limited (HTTP 429); not retried for {until - time.monotonic():.0f}s", 429)
    for attempt in range(retries):
        if limiter:
            limiter.wait()
        try:
            resp = sess.get(url, params=params, headers=headers, timeout=timeout)
        except requests.RequestException as exc:  # network error; message may embed the URL
            last_err = DataSourceError(source, f"network error: {type(exc).__name__}: {exc}")
            time.sleep(1.5 * (attempt + 1))
            continue
        if resp.status_code == 429 or resp.status_code >= 500:
            last_err = DataSourceError(source, f"HTTP {resp.status_code} from {redact(resp.url)}",
                                       resp.status_code)
            time.sleep(2.0 * (attempt + 1))
            continue
        if resp.status_code >= 400:
            body = resp.text[:300].replace("\n", " ")
            raise DataSourceError(source, f"HTTP {resp.status_code} from {redact(resp.url)}: {body}",
                                  resp.status_code)
        return resp
    assert last_err is not None
    if getattr(last_err, "status", None) == 429:
        _cooldown[source] = time.monotonic() + COOLDOWN_SECONDS
    raise last_err
