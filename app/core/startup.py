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
from app.core.database import engine

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
