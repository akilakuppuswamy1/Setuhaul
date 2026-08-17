"""Dedicated PostgreSQL URL and schema-reset guards for pytest.

The live demo database (DATABASE_URL / ``setuhaul``) is never selected for
destructive test setup. Tests use TEST_DATABASE_URL, or DATABASE_URL rewritten
to database name ``setuhaul_test``.
"""

from __future__ import annotations

import os
import re
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import URL, make_url

from app.core.config import settings

DEMO_DATABASE_NAME = "setuhaul"
TEST_DATABASE_NAME = "setuhaul_test"
PROTECTED_DATABASE_NAMES = frozenset(
    {DEMO_DATABASE_NAME, "postgres", "template0", "template1"}
)
_SAFE_DB_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _render(url: URL) -> str:
    return url.render_as_string(hide_password=False)


def _live_database_url() -> str:
    return os.environ.get("DATABASE_URL", settings.database_url)


def _same_database(left: URL, right: URL) -> bool:
    left_host = (left.host or "").lower()
    right_host = (right.host or "").lower()
    left_port = left.port or 5432
    right_port = right.port or 5432
    return (
        left_host == right_host
        and left_port == right_port
        and left.database == right.database
    )


def resolved_test_database_url() -> str:
    """Return the configured test URL without connecting.

    Raises RuntimeError if the URL would target the live demo database.
    """
    explicit = os.environ.get("TEST_DATABASE_URL", settings.test_database_url).strip()
    live = _live_database_url()
    if explicit:
        candidate = explicit
    else:
        if not str(live).startswith("postgresql"):
            raise RuntimeError("DATABASE_URL is not PostgreSQL; cannot derive TEST_DATABASE_URL")
        candidate = _render(make_url(live).set(database=TEST_DATABASE_NAME))

    if not candidate.startswith("postgresql"):
        raise RuntimeError("TEST_DATABASE_URL must be a PostgreSQL URL")

    parsed = make_url(candidate)
    dbname = parsed.database
    if not dbname or dbname in PROTECTED_DATABASE_NAMES:
        raise RuntimeError(
            f"Refusing PostgreSQL test database {dbname!r}. "
            f"Set TEST_DATABASE_URL to a dedicated database (default {TEST_DATABASE_NAME!r})."
        )
    if live.startswith("postgresql") and _same_database(parsed, make_url(live)):
        raise RuntimeError(
            "TEST_DATABASE_URL must not point at the same database as DATABASE_URL"
        )
    return _render(parsed)


def _ensure_database_exists(test_url: URL) -> None:
    dbname = test_url.database
    if not dbname or not _SAFE_DB_NAME.fullmatch(dbname):
        raise RuntimeError(f"Unsafe test database name {dbname!r}")

    admin_urls = [test_url.set(database="postgres")]
    live = _live_database_url()
    if live.startswith("postgresql"):
        admin_urls.append(make_url(live))

    last_error: Exception | None = None
    for admin in admin_urls:
        engine = None
        try:
            engine = create_engine(
                _render(admin),
                isolation_level="AUTOCOMMIT",
                connect_args={"connect_timeout": 3},
            )
            with engine.connect() as connection:
                exists = connection.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :n"),
                    {"n": dbname},
                ).scalar()
                if not exists:
                    connection.execute(text(f'CREATE DATABASE "{dbname}"'))
            return
        except Exception as exc:  # noqa: BLE001 — try next admin database
            last_error = exc
        finally:
            if engine is not None:
                engine.dispose()
    if last_error is not None:
        raise last_error


def postgres_test_url() -> str | None:
    """Connectable dedicated test URL, or None if PostgreSQL is unavailable."""
    live = _live_database_url()
    explicit = os.environ.get("TEST_DATABASE_URL", settings.test_database_url).strip()
    if not explicit and not str(live).startswith("postgresql"):
        return None
    try:
        rendered = resolved_test_database_url()
    except RuntimeError:
        raise
    except Exception:
        return None

    parsed = make_url(rendered)
    try:
        _ensure_database_exists(parsed)
        engine = create_engine(rendered, connect_args={"connect_timeout": 3})
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            connected = connection.execute(text("SELECT current_database()")).scalar()
        engine.dispose()
    except RuntimeError:
        raise
    except Exception:
        return None

    if connected in PROTECTED_DATABASE_NAMES:
        raise RuntimeError(
            f"Connected to protected database {connected!r}; refusing pytest use"
        )
    if connected != parsed.database:
        raise RuntimeError(
            f"Connected to {connected!r} but test URL database is {parsed.database!r}"
        )
    return rendered


def reset_public_schema(connection: Any) -> None:
    """DROP/CREATE public schema only when connected to the dedicated test DB."""
    current = connection.execute(text("SELECT current_database()")).scalar()
    live = _live_database_url()
    live_name = make_url(live).database if str(live).startswith("postgresql") else None
    if current in PROTECTED_DATABASE_NAMES or (live_name and current == live_name):
        raise RuntimeError(
            f"Refusing DROP SCHEMA public on database {current!r} "
            "(pytest must use TEST_DATABASE_URL / setuhaul_test)"
        )
    connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
    connection.execute(text("CREATE SCHEMA public"))
