"""Regression tests for DATABASE_URL handling and shared list-endpoint failures."""

from __future__ import annotations

import logging

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.db_url import normalize_database_url
from app.core.startup import should_run_startup_migrations
from app.main import app as fastapi_app
import app.models  # noqa: F401


def test_normalize_render_postgres_scheme() -> None:
    assert normalize_database_url("postgres://user:pass@host:5432/db").startswith(
        "postgresql+psycopg://"
    )


def test_normalize_postgresql_scheme() -> None:
    assert normalize_database_url("postgresql://user:pass@host:5432/db").startswith(
        "postgresql+psycopg://"
    )


def test_normalize_leaves_psycopg_scheme() -> None:
    url = "postgresql+psycopg://user:pass@host:5432/db"
    assert normalize_database_url(url) == url


def test_startup_migrations_off_by_default(monkeypatch) -> None:
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.setattr("app.core.startup.settings.run_migrations_on_startup", False)
    assert should_run_startup_migrations() is False


def test_startup_migrations_on_render(monkeypatch) -> None:
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setattr("app.core.startup.settings.run_migrations_on_startup", False)
    assert should_run_startup_migrations() is True


def test_apply_schema_upgrades_when_domain_tables_missing(monkeypatch) -> None:
    from app.core import startup as startup_mod

    class _Conn:
        def execute(self, _stmt):
            return _Result()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class _Result:
        def scalar(self):
            return "setuhaul"

    monkeypatch.setattr(startup_mod, "should_run_startup_migrations", lambda: True)
    monkeypatch.setattr(startup_mod.engine, "connect", lambda: _Conn())
    monkeypatch.setattr(startup_mod, "inspect", lambda _conn: type("I", (), {"get_table_names": lambda self: []})())
    called = {"upgrade": False}

    def fake_upgrade(_config, revision):
        called["upgrade"] = True
        assert revision == "head"

    monkeypatch.setattr(startup_mod.command, "upgrade", fake_upgrade)
    startup_mod.apply_schema_if_needed()
    assert called["upgrade"] is True


def test_apply_schema_skips_when_tables_exist_without_alembic_version(monkeypatch) -> None:
    from app.core import startup as startup_mod

    class _Conn:
        def execute(self, _stmt):
            return _Result()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class _Result:
        def scalar(self):
            return "setuhaul"

    monkeypatch.setattr(startup_mod, "should_run_startup_migrations", lambda: True)
    monkeypatch.setattr(startup_mod.engine, "connect", lambda: _Conn())
    monkeypatch.setattr(
        startup_mod,
        "inspect",
        lambda _conn: type("I", (), {"get_table_names": lambda self: ["carriers", "drivers"]})(),
    )
    called = {"upgrade": False}
    monkeypatch.setattr(
        startup_mod.command,
        "upgrade",
        lambda *_a, **_k: called.__setitem__("upgrade", True),
    )
    startup_mod.apply_schema_if_needed()
    assert called["upgrade"] is False


def _client_for_engine(engine):
    factory = sessionmaker(bind=engine)

    def override_get_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    fastapi_app.dependency_overrides[get_db] = override_get_db
    return TestClient(fastapi_app, raise_server_exceptions=False)


def test_list_carriers_without_schema_returns_500_without_traceback(caplog) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    client = _client_for_engine(engine)
    try:
        with caplog.at_level(logging.ERROR, logger="setuhaul"):
            response = client.get("/carriers", params={"page": 1, "page_size": 1})
        assert response.status_code == 500
        body = response.json()
        assert body == {"detail": "Internal Server Error"}
        assert "Traceback" not in response.text
        assert any("Unhandled error" in rec.getMessage() for rec in caplog.records)
        assert any("OperationalError" in rec.getMessage() or rec.exc_info for rec in caplog.records)
    finally:
        fastapi_app.dependency_overrides.clear()
        engine.dispose()


def test_health_ok_without_schema() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    client = _client_for_engine(engine)
    try:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "service": "setuhaul"}
    finally:
        fastapi_app.dependency_overrides.clear()
        engine.dispose()


def test_list_carriers_with_schema_returns_200() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    client = _client_for_engine(engine)
    try:
        response = client.get("/carriers", params={"page": 1, "page_size": 1})
        assert response.status_code == 200
        body = response.json()
        assert body["items"] == []
        assert body["total"] == 0
        assert body["page"] == 1
    finally:
        fastapi_app.dependency_overrides.clear()
        engine.dispose()


def test_shared_list_endpoints_without_schema_all_500() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    client = _client_for_engine(engine)
    paths = [
        "/carriers",
        "/drivers",
        "/vehicles",
        "/shipments",
        "/facilities",
        "/appointments",
        "/eta-updates",
        "/chat-threads",
    ]
    try:
        for path in paths:
            response = client.get(path, params={"page": 1, "page_size": 1})
            assert response.status_code == 500, path
            assert response.json() == {"detail": "Internal Server Error"}
    finally:
        fastapi_app.dependency_overrides.clear()
        engine.dispose()


def test_shared_list_endpoints_with_schema_all_200() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    client = _client_for_engine(engine)
    paths = [
        "/carriers",
        "/drivers",
        "/vehicles",
        "/shipments",
        "/facilities",
        "/appointments",
        "/eta-updates",
        "/chat-threads",
    ]
    try:
        for path in paths:
            response = client.get(path, params={"page": 1, "page_size": 1})
            assert response.status_code == 200, path
            body = response.json()
            assert body["items"] == []
            assert body["total"] == 0
    finally:
        fastapi_app.dependency_overrides.clear()
        engine.dispose()
