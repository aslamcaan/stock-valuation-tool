"""Local response cache. Every entry is stored with the time it was fetched.

Layout: <root>/<category>/<sha1(key)>.json  (JSON payloads)
        <root>/<category>/<sha1(key)>.bin + .json meta  (binary payloads, e.g. Damodaran .xls)

Categories in DB_CATEGORIES can instead live in the database (core/db.py) when one is passed: the deployed app's
files are wiped on restart, and the AI response cache is what keeps re-runs deterministic.

Cache keys must never contain secrets; callers build keys from URLs with API keys stripped.
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

MINUTE = 60
HOUR = 60 * MINUTE
DAY = 24 * HOUR

# Cache lifetimes from the brief (Section 3). News is never cached longer than 1 hour.
TTL_SECONDS: dict[str, int] = {
    "price": 15 * MINUTE,
    "estimates": DAY,
    "fred": DAY,
    "filings": 30 * DAY,
    "companyfacts": 30 * DAY,
    "damodaran": 30 * DAY,
    "news": HOUR,
    "reference": DAY,  # ticker lists, profiles, peers
    "fundamentals": DAY,  # FMP fallback statements, ownership
    "ai": 3650 * DAY,  # AI responses keyed by the exact request: same inputs -> same output (determinism)
}
MAX_TTL = {"news": HOUR}
DB_CATEGORIES = {"ai"}


class CacheMiss(Exception):
    """Raised in offline mode when a key is not cached."""


@dataclass(frozen=True)
class Cached:
    payload: Any
    fetched_at: datetime
    from_cache: bool
    key: str
    category: str

    @property
    def fetched_at_iso(self) -> str:
        return self.fetched_at.isoformat(timespec="seconds")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Cache:
    def __init__(self, root: Path, offline: bool = False, db=None):
        self.root = Path(root)
        self.offline = offline
        self.db = db
        if db is not None:
            db.execute("CREATE TABLE IF NOT EXISTS cache_entries (category TEXT NOT NULL, digest TEXT NOT NULL, "
                       "fetched_at TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY (category, digest))")
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def _lock(self, path: Path) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(str(path), threading.Lock())

    def _path(self, category: str, key: str) -> Path:
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
        return self.root / category / f"{digest}.json"

    @staticmethod
    def ttl(category: str) -> int:
        ttl = TTL_SECONDS.get(category, DAY)
        return min(ttl, MAX_TTL.get(category, ttl))

    def _in_db(self, category: str) -> bool:
        return self.db is not None and category in DB_CATEGORIES

    def _read_db(self, category: str, key: str, allow_stale: bool) -> Cached | None:
        rows = self.db.query("SELECT fetched_at, payload FROM cache_entries WHERE category=? AND digest=?",
                             (category, self._path(category, key).stem))
        if not rows:
            return None
        fetched_at = datetime.fromisoformat(rows[0]["fetched_at"])
        if not (allow_stale or _now() - fetched_at < timedelta(seconds=self.ttl(category))):
            return None
        return Cached(json.loads(rows[0]["payload"]), fetched_at, True, key, category)

    def read(self, category: str, key: str, allow_stale: bool = False) -> Cached | None:
        if self._in_db(category):
            hit = self._read_db(category, key, allow_stale)
            if hit is not None:
                return hit
        meta_path = self._path(category, key)
        if not meta_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        fetched_at = datetime.fromisoformat(meta["fetched_at"])
        fresh = _now() - fetched_at < timedelta(seconds=self.ttl(category))
        if not (fresh or allow_stale):
            return None
        if meta.get("binary"):
            payload: Any = meta_path.with_suffix(".bin").read_bytes()
        else:
            payload = meta["payload"]
        return Cached(payload, fetched_at, True, key, category)

    def write(self, category: str, key: str, payload: Any, binary: bool = False,
              fetched_at: datetime | None = None) -> Cached:
        fetched_at = fetched_at or _now()
        if self._in_db(category) and not binary:
            self.db.upsert("cache_entries", {"category": category, "digest": self._path(category, key).stem,
                                             "fetched_at": fetched_at.isoformat(), "payload": json.dumps(payload)},
                           keys=("category", "digest"))
            return Cached(payload, fetched_at, False, key, category)
        meta_path = self._path(category, key)
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta = {"key": key, "category": category, "fetched_at": fetched_at.isoformat(), "binary": binary}
        if binary:
            meta_path.with_suffix(".bin").write_bytes(payload)
        else:
            meta["payload"] = payload
        tmp = meta_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(meta), encoding="utf-8")
        tmp.replace(meta_path)
        return Cached(payload, fetched_at, False, key, category)

    def get_or_fetch(self, category: str, key: str, fetch: Callable[[], Any],
                     binary: bool = False, force: bool = False) -> Cached:
        """Return a fresh cached entry or call `fetch()` and store its result.

        Offline mode serves whatever is cached regardless of age and never calls `fetch`.
        """
        if self.offline:
            hit = self.read(category, key, allow_stale=True)
            if hit is None:
                raise CacheMiss(f"offline and not cached: {category} {key}")
            return hit
        path = self._path(category, key)
        with self._lock(path):
            if not force:
                hit = self.read(category, key)
                if hit is not None:
                    return hit
            payload = fetch()
            return self.write(category, key, payload, binary=binary)

    def clear(self, category: str | None = None) -> int:
        target = self.root / category if category else self.root
        n = 0
        if target.exists():
            for p in target.rglob("*"):
                if p.is_file():
                    p.unlink()
                    n += 1
        return n
