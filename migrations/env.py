import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Load app settings + models so autogenerate sees the full metadata
from app.config import settings
from app.database import Base
from app import models  # noqa: F401  (registers all tables on Base.metadata)

config = context.config

# Fail fast with a clear message when deployed without a real DATABASE_URL.
# On Railway the .env file is not deployed (gitignored), so the variable MUST
# be set on the service (Variables tab); otherwise settings fall back to the
# localhost default and the connection fails cryptically after a long timeout.
_DEFAULT_LOCAL = "postgresql://postgres:postgres@localhost:5432/archie_db"
if settings.DATABASE_URL == _DEFAULT_LOCAL and (
        "RAILWAY_ENVIRONMENT" in os.environ or settings.ENVIRONMENT == "production"):
    raise RuntimeError(
        "DATABASE_URL is not set. Add it in Railway -> service -> Variables "
        "(your Neon connection string, or ${{Postgres.DATABASE_URL}} if using "
        "Railway Postgres). The .env file is gitignored and is NOT deployed."
    )

config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
