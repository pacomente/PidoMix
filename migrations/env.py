from logging.config import fileConfig
from pathlib import Path
import sys

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make imports independent from the shell working directory. Render, local CLI
# usage, and IDEs can invoke Alembic from different directories, so resolve
# the repository root from this file instead of relying on a machine-specific
# absolute path.
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import settings
from app.db import Base, normalize_database_url
import app.models  # noqa: F401 - register all SQLAlchemy models with Base.metadata

config = context.config
database_url = normalize_database_url(settings.database_url)
# ConfigParser treats % as interpolation syntax. Escaping it here keeps valid
# percent-encoded PostgreSQL credentials/URLs safe when Alembic reads them.
config.set_main_option('sqlalchemy.url', database_url.replace('%', '%%'))

if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix='sqlalchemy.',
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
