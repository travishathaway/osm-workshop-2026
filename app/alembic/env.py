from __future__ import annotations

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool, text

from alembic import context

# Import models metadata so 'alembic revision --autogenerate' can detect schema changes.
# Note: geometry columns (GEOMETRY type) are NOT autogenerateable without geoalchemy2;
# add geometry DDL by hand in migration files.
from parkalyzer.db.models import Base

config = context.config

# Inject DSN from environment, overriding the placeholder in alembic.ini.
dsn = os.environ.get("PARKALYZER_DSN")
if dsn:
    config.set_main_option("sqlalchemy.url", dsn)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting (useful for generating SQL scripts)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        version_table_schema="parkalyzer",
    )
    with context.begin_transaction():
        context.execute("CREATE SCHEMA IF NOT EXISTS parkalyzer")
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect to the DB and apply migrations."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS parkalyzer"))
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            version_table_schema="parkalyzer",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
