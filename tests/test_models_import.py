def test_sqlalchemy_models_import_and_map(monkeypatch):
    # Use an in-memory SQLite engine for the mapper/import test so CI can verify
    # SQLAlchemy typing without requiring a running PostgreSQL service.
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")

    from sqlalchemy import inspect
    from app.db import Base
    from app.models.models import Category, Order, OrderItem, Product, Store, User

    for model in (User, Store, Product, Category, Order, OrderItem):
        mapper = inspect(model)
        assert mapper is not None

    assert "users" in Base.metadata.tables
    assert "stores" in Base.metadata.tables
    assert "products" in Base.metadata.tables
    assert "orders" in Base.metadata.tables
