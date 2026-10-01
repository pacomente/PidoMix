import sys

from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker


def test_seed_is_idempotent_on_empty_database(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'seed.db'}")
    from app.db import Base
    import app.models  # noqa: F401

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    import app.seed as seed

    monkeypatch.setattr(seed, "SessionLocal", session_factory)
    seed.settings.admin_email = "Admin@Test.Local"
    seed.ADMIN_EMAIL = "admin@test.local"
    seed.settings.admin_password = "TestOnly-123!"
    seed.settings.whatsapp_default_number = "5492910000000"
    seed.settings.environment = "development"

    seed.run_seed()
    seed.run_seed()

    with session_factory() as db:
        from app.models import Category, Product, Store, StoreCategory, User

        assert db.query(User).count() == 1
        assert db.query(StoreCategory).count() == 1
        assert db.query(Store).count() == 1
        assert db.query(Category).count() == 4
        assert db.query(Product).count() == 2
        assert db.query(User).filter(func.lower(User.email) == "admin@test.local").count() == 1


def test_seed_runs_after_real_alembic_migration(monkeypatch, tmp_path):
    # This is the production ordering test: an empty database must first be
    # migrated by Alembic, and only then may the seed query/insert data.
    import os
    import subprocess

    db_path = tmp_path / "after_alembic.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    env["ENVIRONMENT"] = "development"
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True, env=env)

    from sqlalchemy import create_engine, inspect
    from sqlalchemy.orm import sessionmaker
    import app.seed as seed

    engine = create_engine(f"sqlite:///{db_path}")
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    seed.SessionLocal = Session
    seed.settings.admin_email = "after-alembic@test.local"
    seed.ADMIN_EMAIL = "after-alembic@test.local"
    seed.settings.admin_password = "TestOnly-123!"
    seed.settings.whatsapp_default_number = "5492910000000"
    seed.settings.environment = "development"

    assert "users" in inspect(engine).get_table_names()
    seed.run_seed()
    seed.run_seed()

    with Session() as db:
        from app.models import Product, Store, User
        assert db.query(User).count() == 1
        assert db.query(Store).count() == 1
        assert db.query(Product).count() == 2
