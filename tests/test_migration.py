"""Migration integrity tests for Step 2 schema hardening."""

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

import app.models  # noqa: F401
from app.core.config import settings
from app.core.database import Base

EXPECTED_DOMAIN_TABLES = {
    "carriers",
    "drivers",
    "vehicles",
    "shipments",
    "eta_updates",
    "driver_exceptions",
    "facility_checkins",
    "facilities",
    "docks",
    "facility_rules",
    "appointment_slots",
    "appointments",
    "chat_threads",
    "chat_messages",
    "contacts",
    "operational_messages",
}


def _postgres_test_url() -> str | None:
    url = os.environ.get("DATABASE_URL", settings.database_url)
    if not url.startswith("postgresql"):
        return None
    try:
        engine = create_engine(url)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        engine.dispose()
        return url
    except Exception:
        return None


@pytest.fixture
def alembic_config(postgres_url: str) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", postgres_url)
    return config


@pytest.fixture
def postgres_url() -> str:
    url = _postgres_test_url()
    if url is None:
        pytest.skip("PostgreSQL unavailable for migration tests")
    return url


def test_migration_upgrade_creates_domain_tables_only(
    alembic_config: Config,
    postgres_url: str,
) -> None:
    engine = create_engine(postgres_url)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))

    command.upgrade(alembic_config, "head")

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert EXPECTED_DOMAIN_TABLES.issubset(tables)
    unexpected = tables - EXPECTED_DOMAIN_TABLES - {"alembic_version"}
    assert unexpected == set()

    engine.dispose()


def test_migration_downgrade_and_upgrade_round_trip(
    alembic_config: Config,
    postgres_url: str,
) -> None:
    engine = create_engine(postgres_url)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))

    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert EXPECTED_DOMAIN_TABLES.issubset(tables)

    engine.dispose()


def test_metadata_matches_migrated_schema(postgres_url: str) -> None:
    engine = create_engine(postgres_url)
    inspector = inspect(engine)
    migrated_tables = set(inspector.get_table_names()) - {"alembic_version"}
    model_tables = set(Base.metadata.tables.keys())
    assert migrated_tables == model_tables

    engine.dispose()
