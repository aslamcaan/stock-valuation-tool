"""Get ready to deploy: check the keys, test the hosted database, copy local data into it, write secrets.toml.

    python scripts/deploy_prep.py

Reads .env. Needs APP_PASSWORD and DATABASE_URL filled in there first. Writes .streamlit/secrets.toml (gitignored)
for pasting into the Streamlit Cloud "Secrets" box. Never prints a key, password or connection string.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import dotenv_values  # noqa: E402

from core.db import Database, DatabaseError  # noqa: E402
from core.store import Store  # noqa: E402

REQUIRED = ["SEC_USER_NAME", "SEC_USER_EMAIL", "FMP_API_KEY", "FRED_API_KEY", "ANTHROPIC_API_KEY", "APP_PASSWORD",
            "DATABASE_URL"]
OPTIONAL = ["TIINGO_API_KEY", "FINNHUB_API_KEY", "MAX_COST_PER_REPORT", "MAX_COST_PER_DAY"]
TABLES = {"estimate_snapshots": ("ticker", "snapshot_date", "fiscal_year_end"), "track_record": ("report_id",),
          "reports": ("report_id",)}


def main() -> int:
    env = {k: (v or "").strip().strip('"').strip("'") for k, v in dotenv_values(ROOT / ".env").items()}
    missing = [k for k in REQUIRED if not env.get(k)]
    for k in REQUIRED + OPTIONAL:
        print(f"  {k:<20} {'set' if env.get(k) else 'missing'}")
    if missing:
        print(f"\nFill these in .env first: {', '.join(missing)}")
        return 1
    if len(env["APP_PASSWORD"]) < 12:
        print("\nNote: APP_PASSWORD is shorter than 12 characters; a longer one is harder to guess.")

    print("\nConnecting to the hosted database...")
    try:
        hosted = Store(Database(env["DATABASE_URL"]))
    except DatabaseError as exc:
        print(f"  {exc}")
        return 1
    print("  connected, tables ready")

    local_path = ROOT / "data" / "vt.sqlite"
    if local_path.exists():
        local = Database(local_path)
        Store(local)  # makes sure the local tables exist
        for table, keys in TABLES.items():
            rows = local.query(f"SELECT * FROM {table}")
            for r in rows:
                if "payload" in r:
                    r["payload"] = bytes(r["payload"])
                hosted.db.upsert(table, r, keys)
            print(f"  copied {len(rows)} rows of {table}")

    lines = ["# Paste everything below into Streamlit Cloud > your app > Settings > Secrets. Keep this file private."]
    for k in REQUIRED + OPTIONAL:
        if env.get(k):
            v = env[k].replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{k} = "{v}"')
    out = ROOT / ".streamlit" / "secrets.toml"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWrote {out.relative_to(ROOT)} (gitignored). Open it, copy everything, paste into Streamlit's Secrets box.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
