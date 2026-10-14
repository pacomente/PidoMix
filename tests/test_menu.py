"""Armar el menú: el local mueve secciones y productos arrastrando, renombra y elimina."""
import os
import re
import sys

import pytest


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("menu") / "menu.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["ENVIRONMENT"] = "development"
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]
    from app import seed
    from app.db import Base, SessionLocal, engine
    from app.models import Product, Store, StoreSection, User
    from app.services.auth import hash_password
    Base.metadata.create_all(engine)
    seed.ADMIN_EMAIL = "admin@test.local"
    seed.settings.admin_password = "TestOnly-123!"
    seed.run_seed()
    with SessionLocal() as db:
        s = db.query(Store).filter_by(slug="burger-mix").one()
        other = db.query(Store).filter(Store.id != s.id).first()
        db.add(User(email="menu@burger.test", password_hash=hash_password("Menu-1234"), store_id=s.id))
        a, b = StoreSection(store_id=s.id, name="Hamburguesas", display_order=10), StoreSection(store_id=s.id, name="Bebidas", display_order=20)
        db.add_all([a, b]); db.flush()
        ps = db.query(Product).filter_by(store_id=s.id).all()
        for p in ps: p.section_id = a.id
        foreign = Product(name="Ajeno", price=100, store_id=other.id) if other else None
        if foreign: db.add(foreign)
        db.commit()
        ids = {"store": s.id, "a": a.id, "b": b.id, "products": [p.id for p in ps], "foreign": foreign.id if foreign else None}
    yield ids
    engine.dispose()


def login():
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    assert c.post("/admin/login", data={"email": "menu@burger.test", "password": "Menu-1234"}, follow_redirects=False).status_code == 303
    page = c.get("/admin/sections").text
    return c, re.search(r'name="csrf-token" content="([^"]+)"', page).group(1), page


def test_armar_el_menu(env):
    from app.db import SessionLocal
    from app.models import Product, StoreSection
    c, tok, page = login()
    assert "Armar el menú" in page and "Hamburguesas" in page and "dnd-handle" in page
    p1, p2 = env["products"][:2]
    # Bebidas arriba de Hamburguesas; p2 pasa a Bebidas y p1 queda sin sección
    body = {"sections": [env["b"], env["a"]], "products": {str(env["b"]): [p2], str(env["a"]): [], "none": [p1]}}
    r = c.post("/admin/sections/order", json=body, headers={"X-CSRF-Token": tok})
    assert r.status_code == 200 and r.json()["ok"]
    with SessionLocal() as db:
        assert db.get(StoreSection, env["b"]).display_order < db.get(StoreSection, env["a"]).display_order
        assert db.get(Product, p2).section_id == env["b"] and db.get(Product, p1).section_id is None
    # la tienda muestra el nuevo orden
    store = c.get("/tienda/burger-mix").text
    assert store.index("Bebidas") < store.index("Otros")
    # sin CSRF no se guarda; con productos o secciones de otro local tampoco
    assert c.post("/admin/sections/order", json=body, headers={"x-no-csrf": "1"}).status_code == 403
    if env["foreign"]:
        bad = c.post("/admin/sections/order", json={"sections": [], "products": {"none": [env["foreign"]]}}, headers={"X-CSRF-Token": tok})
        assert bad.status_code == 400
    # renombrar y eliminar una sección: sus productos quedan sin sección (no se borran)
    form = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    c.post(f"/admin/sections/{env['b']}/rename", data={"name": "Bebidas frías", "csrf_token": form})
    assert "Bebidas frías" in c.get("/admin/sections").text
    r = c.post(f"/admin/sections/{env['b']}/delete", data={"csrf_token": form}, follow_redirects=False)
    assert r.status_code == 303 and "section_deleted" in r.headers["location"]
    with SessionLocal() as db:
        assert db.get(StoreSection, env["b"]) is None and db.get(Product, p2) is not None and db.get(Product, p2).section_id is None
    # eliminar un producto desde el menú vuelve al menú
    r = c.post(f"/admin/products/{p1}/delete", data={"csrf_token": form, "back": f"/admin/sections?store_id={env['store']}"}, follow_redirects=False)
    assert r.headers["location"].startswith("/admin/sections") and "product_deleted" in r.headers["location"]
    # una sección nueva va al final
    c.post("/admin/sections", data={"name": "Postres", "csrf_token": form})
    with SessionLocal() as db:
        orders = {s.name: s.display_order for s in db.query(StoreSection).filter_by(store_id=env["store"])}
        assert orders["Postres"] > orders["Hamburguesas"]
