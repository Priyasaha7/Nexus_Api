# alembic/env.py
import os
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Alembic Config object
config = context.config

# Fix the DB URL — swap asyncpg → psycopg2 for alembic (alembic needs sync driver)
db_url = os.getenv("DATABASE_URL", "")
db_url = db_url.replace("+asyncpg", "+psycopg2").replace("?ssl=require", "?sslmode=require")
config.set_main_option("sqlalchemy.url", db_url)

# Setup logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import your models so alembic can detect them
from app.database import Base
from app.models import *  # this pulls in Organisation, User, CreditTransaction

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
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
        context.configure(
            connection=connection,
            target_metadata=target_metadata
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()