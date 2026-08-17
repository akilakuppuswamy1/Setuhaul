"""Safe database diagnostic (no credentials). Usage: python scripts/diagnose_db.py"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import inspect, text
from sqlalchemy.engine.url import make_url

from app.core.database import engine
from app.core.db_url import normalize_database_url
from app.core.config import settings

SENTINEL_TABLES = (
    "carriers",
    "drivers",
    "vehicles",
    "shipments",
    "facilities",
    "appointments",
    "eta_updates",
    "chat_threads",
)


def main() -> int:
    raw = settings.database_url
    normalized = normalize_database_url(raw)
    parsed = make_url(normalized)
    print("DATABASE_URL configured:", bool(raw))
    print("drivername:", parsed.drivername)
    print("host:", parsed.host)
    print("port:", parsed.port)
    print("database:", parsed.database)
    print("sqlalchemy dialect:", engine.dialect.name)
    print("sqlalchemy driver:", engine.dialect.driver)

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            dbname = connection.execute(text("SELECT current_database()")).scalar()
            schema = connection.execute(text("SELECT current_schema()")).scalar()
            tables = set(inspect(connection).get_table_names())
            alembic_version = None
            try:
                alembic_version = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar()
            except Exception as exc:
                print("DATABASE MIGRATION OUT OF DATE: alembic_version unreadable:", type(exc).__name__)
            print("DATABASE CONNECTION OK")
            print("current_database:", dbname)
            print("current_schema:", schema)
            print("alembic_version:", alembic_version)
            missing = [name for name in SENTINEL_TABLES if name not in tables]
            if missing:
                print("DATABASE TABLE MISSING:", ", ".join(missing))
                return 2
            print("DATABASE SCHEMA OK")
            return 0
    except Exception as exc:
        print("DATABASE CONNECTION FAILURE:", type(exc).__name__)
        print(str(exc).split("\n")[0][:300])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
