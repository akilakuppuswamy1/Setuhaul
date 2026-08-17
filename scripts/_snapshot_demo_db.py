"""One-off snapshot of the live demo database (not used by pytest)."""

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine.url import make_url

from app.core.config import settings
from tests.db import postgres_test_url, resolved_test_database_url

live = settings.database_url
print("LIVE_URL_DB", make_url(live).database)
print("TEST_RESOLVED_DB", make_url(resolved_test_database_url()).database)
connected_test = postgres_test_url()
print("TEST_CONNECT_DB", make_url(connected_test).database if connected_test else None)

engine = create_engine(live)
with engine.connect() as connection:
    print("CONNECTED", connection.execute(text("SELECT current_database()")).scalar())
    tables = inspect(engine).get_table_names()
    print("TABLE_COUNT", len(tables))
    print("TABLES", ",".join(sorted(tables)))
    if "shipments" in tables:
        cols = {column["name"] for column in inspect(engine).get_columns("shipments")}
        print("SHIPMENT_COUNT", connection.execute(text("SELECT count(*) FROM shipments")).scalar())
        if "code" in cols:
            print(
                "SH_1024",
                connection.execute(
                    text("SELECT count(*) FROM shipments WHERE code = 'SH-1024'")
                ).scalar(),
            )
        elif "reference_code" in cols:
            print(
                "SH_1024",
                connection.execute(
                    text("SELECT count(*) FROM shipments WHERE reference_code = 'SH-1024'")
                ).scalar(),
            )
engine.dispose()
