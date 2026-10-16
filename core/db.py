"""One small database interface over SQLite (local) and Postgres (deployed).

Streamlit Community Cloud wipes local files on every restart, so the deployed app keeps its saved reports, track
record, estimate snapshots, AI spend ledger and AI response cache in a hosted Postgres database (DATABASE_URL in
the Streamlit secrets). Locally everything stays in data/vt.sqlite.

SQL is written once with `?` placeholders and `{BLOB}` for binary columns; upserts use `ON CONFLICT`, which both
engines support. The connection string is a secret: it is never logged or put into error messages.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any


class DatabaseError(Exception):
    """A database problem, described without the connection string."""


class Database:
    def __init__(self, target: str | Path):
        text = str(target)
        self.is_postgres = text.startswith(("postgres://", "postgresql://"))
        self._url = text if self.is_postgres else None
        self._path = None if self.is_postgres else Path(text)
        self._lock = threading.RLock()
        self._pg = None
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def kind(self) -> str:
        return "Postgres" if self.is_postgres else "SQLite"

    def _sql(self, sql: str) -> str:
        sql = sql.replace("{BLOB}", "BYTEA" if self.is_postgres else "BLOB")
        return sql.replace("?", "%s") if self.is_postgres else sql

    def _pg_conn(self):
        if self._pg is None or self._pg.closed:
            import psycopg

            try:
                self._pg = psycopg.connect(self._url, autocommit=True, connect_timeout=15,
                                           prepare_threshold=None)  # poolers (Supabase) reject prepared statements
            except psycopg.Error as exc:
                raise DatabaseError(f"Could not connect to the hosted database ({type(exc).__name__}). "
                                    "Check DATABASE_URL in the secrets.") from None
        return self._pg

    def _run(self, sql: str, params: tuple, fetch: bool) -> list[dict]:
        sql = self._sql(sql)
        if not self.is_postgres:
            with sqlite3.connect(self._path) as c:
                c.row_factory = sqlite3.Row
                cur = c.execute(sql, params)
                return [dict(r) for r in cur.fetchall()] if fetch else []
        import psycopg
        from psycopg.rows import dict_row

        with self._lock:
            for attempt in (1, 2):  # one reconnect: hosted databases drop idle connections
                try:
                    with self._pg_conn().cursor(row_factory=dict_row) as cur:
                        cur.execute(sql, params)
                        return [dict(r) for r in cur.fetchall()] if fetch else []
                except psycopg.OperationalError:
                    self._pg = None
                    if attempt == 2:
                        raise DatabaseError("Lost the connection to the hosted database.") from None
        return []

    def execute(self, sql: str, params: tuple = ()) -> None:
        self._run(sql, params, fetch=False)

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        return self._run(sql, params, fetch=True)

    def scalar(self, sql: str, params: tuple = ()) -> Any:
        rows = self.query(sql, params)
        return next(iter(rows[0].values())) if rows else None

    def script(self, sql: str) -> None:
        for stmt in (s.strip() for s in sql.split(";")):
            if stmt:
                self.execute(stmt)

    def upsert(self, table: str, row: dict, keys: tuple[str, ...]) -> None:
        cols = list(row)
        updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c not in keys)
        self.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
                     f"ON CONFLICT ({', '.join(keys)}) DO " + (f"UPDATE SET {updates}" if updates else "NOTHING"),
                     tuple(row[c] for c in cols))


def as_database(target: "Database | str | Path") -> Database:
    return target if isinstance(target, Database) else Database(target)
