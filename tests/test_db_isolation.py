"""Guards that pytest never targets the live SetuHaul demo database."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.engine.url import make_url

from tests.db import (
    DEMO_DATABASE_NAME,
    TEST_DATABASE_NAME,
    postgres_test_url,
    reset_public_schema,
    resolved_test_database_url,
)


def test_resolved_test_url_is_not_demo_database() -> None:
    url = resolved_test_database_url()
    parsed = make_url(url)
    assert parsed.database == TEST_DATABASE_NAME
    assert parsed.database != DEMO_DATABASE_NAME


def test_explicit_demo_url_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://setuhaul:setuhaul@localhost:5433/setuhaul",
    )
    with pytest.raises(RuntimeError, match="Refusing PostgreSQL test database"):
        resolved_test_database_url()


def test_explicit_url_matching_live_database_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live = "postgresql+psycopg://setuhaul:setuhaul@localhost:5433/demo_live"
    monkeypatch.setenv("DATABASE_URL", live)
    monkeypatch.setenv("TEST_DATABASE_URL", live)
    with pytest.raises(RuntimeError, match="must not point at the same database"):
        resolved_test_database_url()


def test_reset_public_schema_refuses_demo_database_name() -> None:
    class _FakeResult:
        def scalar(self) -> str:
            return DEMO_DATABASE_NAME

    connection = SimpleNamespace(execute=lambda _stmt: _FakeResult())
    with pytest.raises(RuntimeError, match="Refusing DROP SCHEMA"):
        reset_public_schema(connection)


def test_postgres_test_url_connects_to_dedicated_database() -> None:
    url = postgres_test_url()
    if url is None:
        pytest.skip("PostgreSQL unavailable for test-database isolation check")
    parsed = make_url(url)
    assert parsed.database == TEST_DATABASE_NAME
    assert parsed.database != DEMO_DATABASE_NAME
