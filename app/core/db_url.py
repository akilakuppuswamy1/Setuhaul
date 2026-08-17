"""Safe DATABASE_URL normalization for SQLAlchemy and Alembic.

Never log the raw URL. Callers may pass postgres:// (Render) or postgresql://.
"""


def normalize_database_url(url: str) -> str:
    """Return a SQLAlchemy URL that uses the psycopg 3 driver.

    Render and Heroku often inject postgres:// or postgresql://, which SQLAlchemy
    maps to psycopg2. This project depends on psycopg (v3) only.
    """
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url
