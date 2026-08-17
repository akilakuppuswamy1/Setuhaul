"""Migration integrity tests for Step 2 schema hardening."""

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

import app.models  # noqa: F401
from app.core.database import Base
from tests.db import postgres_test_url as _postgres_test_url
from tests.db import reset_public_schema

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
        reset_public_schema(connection)

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
        reset_public_schema(connection)

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
