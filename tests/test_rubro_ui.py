"""Heladería y cafetería: el color de cada gusto, los tamaños, el orden de los gustos, el número de retiro y "llega frío"."""
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

ADMIN = {"email": "admin@test.local", "password": "TestOnly-123!"}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("rubro") / "rubro.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["ENVIRONMENT"] = "development"
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]
    from app import seed
    from app.db import Base, SessionLocal, engine
    from app.models import ModifierGroup, ModifierOption, Product, Store, StoreCategory
    Base.metadata.create_all(engine)
    seed.ADMIN_EMAIL = ADMIN["email"]
    seed.settings.admin_password = ADMIN["password"]
    seed.run_seed()
    with SessionLocal() as db:
        s = db.query(Store).filter_by(slug="burger-mix").one()
        cat = StoreCategory(name="Heladería", slug="heladeria", active=True)
        db.add(cat); db.flush()
        s.store_category_id = cat.id
        pote = Product(name="Pote ½ kg", price=Decimal("8900"), store_id=s.id)
        db.add(pote); db.flush()
        g = ModifierGroup(product_id=pote.id, name="Gustos", min_select=1, max_select=3, required=True)
        db.add(g); db.flush()
        for i, n in enumerate(["Chocolate amargo", "Frutilla a la crema (sin TACC)", "Dulce de leche granizado", "Limón (vegano)"]):
            db.add(ModifierOption(group_id=g.id, name=n, price_extra=Decimal("0"), display_order=i))
        db.commit()
    yield
    engine.dispose()


def client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def pote():
    from app.db import SessionLocal
    from app.models import ModifierOption, Product
    with SessionLocal() as db:
        p = db.query(Product).filter_by(name="Pote ½ kg").one()
        return p.id, {o.name.split()[0]: o.id for o in db.query(ModifierOption).all() if o.group.product_id == p.id}


def test_colores_y_marcas(env):
    from app.services import rubro_ui
    assert rubro_ui.flavor_color("Dulce de leche granizado") == "#B8794A"  # gana "dulce de leche", no "leche"
    assert rubro_ui.flavor_color("Chocolate blanco") == "#F5EBDD"
    assert rubro_ui.flavor_color("Frutilla a la crema") == "#F9A8D4"
    assert rubro_ui.flavor_color("Gusto misterioso") is None
    assert rubro_ui.option_tags("Frutilla (Sin TACC)") == ["SIN TACC"] and rubro_ui.option_tags("Limón vegano") == ["VEGANO"]
    assert rubro_ui.option_ml("Mediano 350 ml") == 350 and rubro_ui.option_ml("Grande") is None
    size = SimpleNamespace(name="Tamaño", max_select=1, options=[])
    assert rubro_ui.group_json_extra("cafeteria", size) == {"display": "sizes"}
    leche = SimpleNamespace(name="Leche", max_select=1, options=[])
    assert rubro_ui.group_json_extra("cafeteria", leche) == {}
    gustos = SimpleNamespace(name="Gustos", max_select=3, options=[])
    assert rubro_ui.group_json_extra("heladeria", gustos) == {"display": "flavors"}
    assert rubro_ui.group_json_extra("restaurante", gustos) == {}  # en otro rubro, la lista de siempre
    sin = SimpleNamespace(name="Sacale", max_select=3, options=[SimpleNamespace(name="Sin cebolla", active=True, price_extra=0),
                                                              SimpleNamespace(name="Sin ajo", active=True, price_extra=0)])
    assert rubro_ui.group_json_extra("restaurante", sin) == {"display": "without"}


def test_rubro_bar():
    from app.services import weight
    assert [weight.theme_for(t)["key"] for t in ("Bar", "Bares y pubs", "Cervecerías", "Barbería")] == ["bar", "bar", "bar", "restaurante"]


def test_la_api_dice_como_dibujar_los_gustos(env):
    pid, _ = pote()
    c = client()
    for path in (f"/api/v1/products/{pid}", f"/api/products/{pid}/modifiers"):
        data = c.get(path).json()
        assert data["rubro"] == "heladeria"
        g = data["groups"][0]
        assert g["display"] == "flavors"
        by = {o["name"]: o for o in g["options"]}
        assert by["Chocolate amargo"]["color"] == "#5B3A29"
        assert by["Frutilla a la crema (sin TACC)"]["tags"] == ["SIN TACC"]
        assert by["Limón (vegano)"]["tags"] == ["VEGANO"]


def test_los_gustos_quedan_en_el_orden_elegido(env):
    from app.db import SessionLocal
    from app.services.cart import price_lines
    pid, o = pote()
    with SessionLocal() as db:
        cart = price_lines(db, [{"product_id": pid, "quantity": 1, "modifiers": [o["Dulce"], o["Chocolate"], o["Frutilla"]]}])
    item = cart["items"][0]
    assert item["modifiers_text"] == "Dulce de leche granizado, Chocolate amargo, Frutilla a la crema (sin TACC)"
    assert item["unit_price"] == Decimal("8900")


def test_numero_de_retiro_y_llega_frio(env):
    from app.models import OrderStatus
    from app.services import rubro_ui
    store = SimpleNamespace(store_category=SimpleNamespace(slug="heladeria", name="Heladería"), prep_minutes=15)
    now = datetime(2026, 1, 10, 22, 0, tzinfo=timezone.utc)
    left = (now - timedelta(minutes=12)).replace(tzinfo=None)
    o = SimpleNamespace(id=318, delivery_method="delivery", status=OrderStatus.EN_CAMINO, store=store, table_name=None,
                        status_time=lambda st: left if st == OrderStatus.EN_CAMINO else None)
    assert rubro_ui.cold(o, now) == {"minutes_out": 12, "keeps_min": 40, "level": 0.3}
    o.status = OrderStatus.PREPARANDO
    assert rubro_ui.cold(o, now) is None  # todavía no salió
    o.status, o.store = OrderStatus.EN_CAMINO, SimpleNamespace(store_category=None, prep_minutes=15)
    assert rubro_ui.cold(o, now) is None  # no es heladería
    assert rubro_ui.pickup(o) is None  # es con envío
    created = datetime(2026, 1, 10, 21, 0)
    r = SimpleNamespace(id=318, delivery_method="retiro", status=OrderStatus.PREPARANDO, store=store, table_name=None, scheduled_for=None,
                        confirmed_at=created, ready_minutes=8, created_at=created)
    pk = rubro_ui.pickup(r)
    assert pk["code"] == "#318" and pk["ready_at"] == created + timedelta(minutes=8) and pk["rubro"] == "heladeria"
    r.table_name = "Mesa 4"
    assert rubro_ui.pickup(r) is None  # en la mesa no hay retiro
