"""
SPA Alembic env.py — BL-008 Phase 3
====================================

Wires Alembic to the SPA dual-driver database URL resolver. The URL is
read from `SPA_DATABASE_URL` (via spa_core.database.db_url.get_db_url),
NOT from the sqlalchemy.url key in alembic.ini.

Both online (live connection) and offline (--sql) modes are supported.

Design notes
------------
* We deliberately keep the migration set raw-SQL based (`op.execute(...)`).
  No SQLAlchemy ORM models are required.
* `target_metadata = None` because we don't autogenerate from ORM models;
  baseline + future migrations are hand-written.
* The repo layout has `spa_core/database/alembic/` as the script location.
  To let env.py `import spa_core...` we add the repo root to sys.path on
  startup.
"""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context

# ---------------------------------------------------------------------------
# Make `spa_core` importable when alembic is invoked from spa_core/database/.
# Path layout:  <repo>/spa_core/database/alembic/env.py
#   parents[0] -> alembic/
#   parents[1] -> database/
#   parents[2] -> spa_core/
#   parents[3] -> repo root
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.database.db_url import get_db_url, is_postgres, is_sqlite  # noqa: E402

config = context.config

# Configure Python logging from alembic.ini if present.
if config.config_file_name is not None:
    try:
        fileConfig(config.config_file_name)
    except Exception:
        # Logging config is best-effort — never fail a migration on it.
        pass

# No ORM models -> autogenerate is not used.
target_metadata = None


def _resolved_url() -> str:
    """
    Pick the active DB URL.

    Order:
      1. -x url=... command-line override (alembic -x url=postgresql://...)
      2. SPA_DATABASE_URL via spa_core.database.db_url
    """
    x_args = context.get_x_argument(as_dictionary=True)
    if "url" in x_args and x_args["url"]:
        return x_args["url"]
    return get_db_url()


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode — emits SQL to stdout, no live DB.

    Usage:
        alembic upgrade head --sql > out.sql
    """
    url = _resolved_url()
    dialect = "postgresql" if is_postgres(url) else "sqlite"
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        dialect_name=dialect,
        compare_type=False,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode using a SQLAlchemy engine built
    from the env-resolved URL.

    Alembic itself requires a SQLAlchemy-flavoured Connection (it reads
    `connection.dialect`), so we use SQLAlchemy purely as the driver
    wrapper. The migrations themselves stay raw-SQL (`op.execute(...)`).

    SQLAlchemy is already a transitive dependency of Alembic, so no
    extra entry in requirements.txt is needed beyond `alembic>=1.13.0`.
    """
    from sqlalchemy import create_engine  # noqa: WPS433
    from sqlalchemy.pool import NullPool  # noqa: WPS433

    url = _resolved_url()
    # NullPool keeps Alembic from holding the connection open after we exit.
    engine = create_engine(url, poolclass=NullPool, future=True)

    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=False,
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
