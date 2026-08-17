from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings
from app.core.db_url import normalize_database_url


database_url = normalize_database_url(settings.database_url)

_connect_args: dict[str, object] = {"connect_timeout": 10}
if "+psycopg" in database_url.split("://", 1)[0]:
    # Disable prepared statements so PgBouncer/Render pooler URLs work with psycopg3.
    _connect_args["prepare_threshold"] = None

engine = create_engine(
    database_url,
    pool_pre_ping=True,
    connect_args=_connect_args,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
