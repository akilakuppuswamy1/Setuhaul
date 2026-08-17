"""Optional schema bootstrap for hosted deploys (Render).

Local pytest and `uvicorn --reload` do not run this unless
RUN_MIGRATIONS_ON_STARTUP is true. Render sets RENDER=true in the environment.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.core.db_url import normalize_database_url

logger = logging.getLogger("setuhaul")

_DOMAIN_SENTINEL_TABLE = "carriers"


def should_run_startup_migrations() -> bool:
    if settings.run_migrations_on_startup:
        return True
    return os.environ.get("RENDER", "").lower() in {"1", "true", "yes"}


def apply_schema_if_needed() -> None:
    """Connect, then run `alembic upgrade head` when the domain schema is absent.

    If domain tables already exist without alembic_version (local demo DB), skip.
    Do not stamp. Do not DROP.
    """
    if not should_run_startup_migrations():
        return

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            dbname = connection.execute(text("SELECT current_database()")).scalar()
            schema = connection.execute(text("SELECT current_schema()")).scalar()
            tables = set(inspect(connection).get_table_names())
    except Exception:
        logger.exception(
            "DATABASE CONNECTION FAILURE during startup (dialect=%s driver=%s)",
            engine.dialect.name,
            engine.dialect.driver,
        )
        raise

    logger.info(
        "DATABASE CONNECTION OK database=%s schema=%s dialect=%s driver=%s table_count=%s",
        dbname,
        schema,
        engine.dialect.name,
        engine.dialect.driver,
        len(tables),
    )

    if _DOMAIN_SENTINEL_TABLE in tables and "alembic_version" not in tables:
        logger.info(
            "DATABASE SCHEMA OK (tables present, no alembic_version); skipping auto-migrate"
        )
        return

    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    logger.info("Running alembic upgrade head")
    command.upgrade(config, "head")
    logger.info("alembic upgrade head complete")


def should_run_startup_demo_seed() -> bool:
    if settings.seed_demo_on_startup:
        return True
    return os.environ.get("RENDER", "").lower() in {"1", "true", "yes"}


def _is_loopback_database_host() -> bool:
    from sqlalchemy.engine.url import make_url

    parsed = make_url(normalize_database_url(settings.database_url))
    host = (parsed.host or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"}


def apply_demo_seed_if_needed() -> None:
    """Seed the classroom demo dataset on Render when the database is empty.

  Uses scripts/seed_ops_demo.py (idempotent). Skips when shipments already exist.
  Never targets loopback unless SEED_DEMO_ON_STARTUP is explicitly true.
    """
    if not should_run_startup_demo_seed():
        return

    if _is_loopback_database_host() and not settings.seed_demo_on_startup:
        logger.info(
            "Skipping demo seed on loopback database (set SEED_DEMO_ON_STARTUP=true to override)"
        )
        return

    from sqlalchemy.engine.url import make_url

    from app.models import Shipment
    from scripts.seed_ops_demo import FORBIDDEN_DATABASE_NAMES, collect_seed_counts, seed_ops_demo

    parsed = make_url(normalize_database_url(settings.database_url))
    dbname = parsed.database or ""
    if dbname in FORBIDDEN_DATABASE_NAMES:
        logger.warning("Skipping demo seed: forbidden database name %r", dbname)
        return

    session = SessionLocal()
    try:
        with engine.connect() as connection:
            current = connection.execute(text("SELECT current_database()")).scalar()
        if current in FORBIDDEN_DATABASE_NAMES:
            logger.warning("Skipping demo seed: forbidden connected database %r", current)
            return

        shipment_count = session.query(Shipment).count()
        if shipment_count > 0:
            logger.info("Demo seed skipped: shipments already present (count=%s)", shipment_count)
            return

        logger.info("Empty database detected on hosted deploy; running seed_ops_demo")
        result = seed_ops_demo(session)
        counts = collect_seed_counts(session)
        logger.info(
            "Demo seed complete hero_shipments=%s shipments=%s drivers=%s facilities=%s",
            result.get("hero_shipment_numbers"),
            counts.get("shipments"),
            counts.get("drivers"),
            counts.get("facilities"),
        )
    except Exception:
        logger.exception("Demo seed failed during startup")
        raise
    finally:
        session.close()
