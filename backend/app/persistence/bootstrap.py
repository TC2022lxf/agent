"""Create the database and bring tables in line with the models.

create_all makes missing tables. Existing tables keep their rows; a column the models
have and the table does not is added. Extra columns and type changes are left alone.
"""

from __future__ import annotations

from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.schema import MetaData


def ensure_database(url: str) -> None:
    made = make_url(url)
    if not made.drivername.startswith("mysql"):
        return
    name = made.database
    if not name:
        raise RuntimeError("MYSQL_DATABASE is empty")
    server = create_engine(made.set(database=None), isolation_level="AUTOCOMMIT")
    with server.connect() as conn:
        conn.exec_driver_sql(
            f"CREATE DATABASE IF NOT EXISTS `{name}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
    server.dispose()


def sync_columns(engine: Engine, metadata: MetaData) -> None:
    metadata.create_all(engine)
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            present = {col["name"] for col in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in present:
                    continue
                ddl = col.type.compile(dialect=engine.dialect)
                conn.exec_driver_sql(
                    f"ALTER TABLE {table.name} ADD COLUMN {col.name} {ddl} NULL"
                )
