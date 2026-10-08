"""Búsqueda inteligente: errores de tipeo, sinónimos, plurales y lenguaje natural, sin inventar resultados."""
import os
import sys

import pytest


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("search") / "search.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["ENVIRONMENT"] = "development"
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]
    from app import seed
    from app.db import Base, SessionLocal, engine
    from app.models import Category, Product, Store, StoreStatus
    Base.metadata.create_all(engine)
    seed.ADMIN_EMAIL = "admin@test.local"
    seed.settings.admin_password = "TestOnly-123!"
    seed.run_seed()
    with SessionLocal() as db:
        burger = db.query(Store).filter_by(slug="burger-mix").one()
        postres = db.query(Category).filter_by(slug="postres").one()
        bebidas = db.query(Category).filter_by(slug="bebidas").one()
        pz = Store(name="Pizzería La Esquina", slug="pizzeria-la-esquina", delivery_enabled=False, delivery_cost=0, minimum_order=0, estimated_minutes=35,
                   status=StoreStatus.ACTIVA, store_category_id=burger.store_category_id, city_id=burger.city_id)
        db.add(pz); db.flush()
        db.add_all([
            Product(name="Fugazzeta", price=10500, store_id=pz.id, category_id=db.query(Category).filter_by(slug="pizzas").one().id),
            Product(name="Muzzarella grande", price=9800, previous_price=11500, store_id=pz.id, category_id=db.query(Category).filter_by(slug="pizzas").one().id),
            Product(name="Flan casero", description="Con dulce de leche", price=4200, store_id=pz.id, category_id=postres.id),
            Product(name="Torta de chocolate", price=6500, store_id=pz.id, category_id=postres.id),
            Product(name="Cerveza rubia 1 L", price=3800, store_id=pz.id, category_id=bebidas.id),
        ])
        db.commit()
    yield
    engine.dispose()


def run(q, **kw):
    from app.db import SessionLocal
    from app.services import search
    search._vocab_cache.clear()
    with SessionLocal() as db:
        r = search.run(db, q, **kw)
        return [p.name for p in r.products], [s.name for s in r.stores], r.query


def test_errores_de_tipeo_plurales_y_sinonimos(env):
    names, stores, q = run("ambuguesa")
    assert names == ["Hamburguesa Clásica"] and "Burger Mix" in stores and q.corrected == "hamburguesa"
    names, _, q = run("fugaseta")
    assert names == ["Fugazzeta"] and q.corrected == "fugazzeta"
    names, _, _ = run("pizzas")
    assert {"Fugazzeta", "Muzzarella grande"} <= set(names)
    names, _, _ = run("birra")
    assert names == ["Cerveza rubia 1 L"]
    names, _, _ = run("muzza")
    assert names[0] == "Muzzarella grande"
    names, stores, _ = run("burger")
    assert "Burger Mix" in stores


def test_lenguaje_natural(env):
    names, _, q = run("algo dulce por menos de 5000")
    assert names == ["Flan casero"] and q.max_price == 5000 and "Algo dulce" in q.labels and "Hasta $5.000" in q.labels
    names, _, q = run("algo dulce")
    assert set(names) == {"Flan casero", "Torta de chocolate"}
    names, _, q = run("pizza en promo")
    assert names == ["Muzzarella grande"] and q.promo
    names, _, q = run("hasta 3 mil")
    assert names and all(n in ("Coca Cola",) for n in names) and q.max_price == 3000
    names, _, q = run("pizza entre 10 y 11 mil")
    assert names == ["Fugazzeta"] and (q.min_price, q.max_price) == (10000, 11000)
    # "con envío": la pizzería no hace envíos
    names, stores, q = run("pizza con envio")
    assert names == [] and stores == [] and q.delivery
    names, _, q = run("hamburguesa barata")
    assert names == ["Hamburguesa Clásica"] and q.cheap


def test_no_inventa_y_sugiere(env):
    from app.db import SessionLocal
    from app.services import search
    names, stores, _ = run("sushi")
    assert names == [] and stores == []
    with SessionLocal() as db:
        assert search.suggestion(db, "pisa") == "pizza"


def test_web_app_y_registro(env):
    from fastapi.testclient import TestClient
    from app.db import SessionLocal
    from app.main import app
    from app.models import SearchLog
    c = TestClient(app)
    page = c.get("/buscar?q=ambuguesa").text
    assert "Mostrando resultados para" in page and "Hamburguesa Clásica" in page
    page = c.get("/buscar?q=algo dulce por menos de 5000").text
    assert "Flan casero" in page and "Hasta $5.000" in page and "Torta de chocolate" not in page
    page = c.get("/buscar?q=pisa napolitana xyz").text
    assert "No encontramos nada" in page
    r = c.get("/api/v1/search?q=fugaseta").json()
    assert [p["name"] for p in r["products"]] == ["Fugazzeta"] and r["corrected"] == "fugazzeta"
    r = c.get("/api/v1/search?q=sushi").json()
    assert r["products"] == [] and r["stores"] == []
    with SessionLocal() as db:
        logs = {l.term: l for l in db.query(SearchLog).all()}
        assert logs["ambuguesa"].results >= 1 and logs["ambuguesa"].corrected == "hamburguesa" and logs["ambuguesa"].channel == "web"
        assert logs["sushi"].results == 0 and logs["sushi"].channel == "app"


def test_trappi_ai_usa_la_busqueda_inteligente(env):
    from app.ai.client_tools import buscar_productos
    from app.ai.tools import ToolContext
    from app.db import SessionLocal
    with SessionLocal() as db:
        out = buscar_productos(ToolContext(db=db), texto="ambuguesa")
        assert [p["nombre"] for p in out["productos"]] == ["Hamburguesa Clásica"] and out["busqueda_corregida"] == "hamburguesa"
