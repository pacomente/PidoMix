"""Productos por peso (precio por kg, el cliente elige cuánto) y catálogo según el rubro (carta o góndola)."""
import os
import sys
from decimal import Decimal

import pytest

ADMIN = {"email": "admin@test.local", "password": "TestOnly-123!"}
OWNER = {"email": "dueno-kg@test.local", "password": "Dueno-1234"}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("kg") / "kg.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["ENVIRONMENT"] = "development"
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]
    from app import seed
    from app.db import Base, SessionLocal, engine
    from app.models import ModifierGroup, ModifierOption, Product, Role, Store, User
    from app.services.auth import hash_password
    Base.metadata.create_all(engine)
    seed.ADMIN_EMAIL = ADMIN["email"]
    seed.settings.admin_password = ADMIN["password"]
    seed.run_seed()
    with SessionLocal() as db:
        s = db.query(Store).filter_by(slug="burger-mix").one()
        nalga = Product(name="Nalga", description="Para milanesas", price=Decimal("12000"), store_id=s.id, sold_by_weight=True)
        asado = Product(name="Asado de tira", price=Decimal("9000"), store_id=s.id, sold_by_weight=True, weight_step=500, weight_min=1000)
        db.add_all([nalga, asado]); db.flush()
        g = ModifierGroup(product_id=nalga.id, name="Corte", min_select=0, max_select=1)
        db.add(g); db.flush()
        db.add(ModifierOption(group_id=g.id, name="Fileteada", price_extra=Decimal("0")))
        db.add(User(email=OWNER["email"], password_hash=hash_password(OWNER["password"]), role=Role.STORE_ADMIN, store_id=s.id, active=True))
        db.commit()
    yield
    engine.dispose()


def client():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services import ratelimit
    ratelimit.order_limiter.clear()
    return TestClient(app)


def ids():
    from app.db import SessionLocal
    from app.models import ModifierOption, Product, Store
    with SessionLocal() as db:
        return {"store": db.query(Store).filter_by(slug="burger-mix").one().id,
                "nalga": db.query(Product).filter_by(name="Nalga").one().id,
                "asado": db.query(Product).filter_by(name="Asado de tira").one().id,
                "coca": db.query(Product).filter_by(name="Coca Cola").one().id,
                "filete": db.query(ModifierOption).filter_by(name="Fileteada").one().id}


def test_pesos_validos_y_etiquetas(env):
    from app.models import Product
    from app.services import weight
    p = Product(name="x", price=Decimal("1"), sold_by_weight=True)
    assert weight.step(p) == 250 and weight.minimum(p) == 250
    assert [weight.clean_grams(p, g) for g in (0, 100, 600, 740, "1500", "basura", 999999)] == [250, 250, 500, 750, 1500, 250, 20000]
    a = Product(name="y", price=Decimal("1"), sold_by_weight=True, weight_step=500, weight_min=1000)
    assert weight.clean_grams(a, 250) == 1000 and weight.presets(a) == [1000, 1500, 2000, 3000]
    assert [weight.label(g) for g in (250, 1000, 1500, 1250)] == ["250 g", "1 kg", "1,5 kg", "1,25 kg"]
    assert weight.price_for(Decimal("12000"), 750) == Decimal("9000.00")
    assert weight.strip_label("750 g, Fileteada", 750) == "Fileteada" and weight.strip_label("750 g", 750) is None


def test_el_servidor_calcula_el_precio_por_peso(env):
    from app.db import SessionLocal
    from app.services.cart import price_lines
    i = ids()
    with SessionLocal() as db:
        cart = price_lines(db, [{"product_id": i["nalga"], "quantity": 2, "modifiers": [i["filete"]], "grams": 750},
                                {"product_id": i["asado"], "quantity": 1, "modifiers": [], "grams": 300},  # menos del minimo: 1 kg
                                {"product_id": i["coca"], "quantity": 1, "modifiers": [], "grams": 5000}])  # no es por peso: se ignora
    it = {x["product"].name: x for x in cart["items"]}
    assert it["Nalga"]["unit_price"] == Decimal("9000.00") and it["Nalga"]["line_total"] == Decimal("18000.00")
    assert it["Nalga"]["modifiers_text"] == "750 g, Fileteada"
    assert it["Asado de tira"]["grams"] == 1000 and it["Asado de tira"]["unit_price"] == Decimal("9000.00")
    assert it["Coca Cola"].get("grams") is None and "grams" not in cart["lines"][2]
    assert cart["lines"][0]["grams"] == 750


def test_web_agrega_por_peso_y_el_pedido_guarda_el_peso(env):
    from app.db import SessionLocal
    from app.models import Order
    from app.services import upsell
    i = ids()
    c = client()
    j = c.get(f"/api/products/{i['nalga']}/modifiers").json()
    assert j["weight"] == {"step": 250, "min": 250, "presets": [250, 500, 750, 1000, 1500]}
    r = c.post("/api/cart/add", json={"product_id": i["nalga"], "quantity": 1, "modifiers": [], "grams": 500}).json()
    r = c.post("/api/cart/add", json={"product_id": i["nalga"], "quantity": 1, "modifiers": [], "grams": 1000}).json()
    assert len(r["items"]) == 2  # distinto peso: lineas distintas
    small = next(x for x in r["items"] if x["grams"] == 500)
    assert small["price"] == 6000 and small["modifiers_text"] == "500 g"
    r = c.post("/api/cart/update", json={"line_key": small["line_key"], "quantity": 0}).json()
    assert [x["grams"] for x in r["items"]] == [1000] and r["subtotal"] == 12000
    resp = c.post("/checkout", data={"first_name": "Ana", "last_name": "Paz", "phone": "2914001122", "delivery_method": "retiro", "payment_method": "efectivo"}, follow_redirects=False)
    assert resp.status_code == 303
    oid = int(resp.headers["location"].split("/pedido/")[1].split("?")[0])
    with SessionLocal() as db:
        o = db.get(Order, oid)
        item = o.items[0]
        assert item.weight_grams == 1000 and item.modifiers_text == "1 kg" and item.unit_price == Decimal("12000.00") and o.subtotal == Decimal("12000.00")
        lines, skipped = upsell.repeat_lines(db, o)  # «Pedí de nuevo» repite el mismo peso
    assert skipped == 0 and lines == [{"product_id": i["nalga"], "quantity": 1, "modifiers": [], "grams": 1000}]


def test_app_cotiza_por_peso(env):
    i = ids()
    c = client()
    j = c.get(f"/api/v1/products/{i['asado']}").json()
    assert j["weight"] == {"step": 500, "min": 1000, "presets": [1000, 1500, 2000, 3000]} and j["price"] == 9000
    q = c.post("/api/v1/cart/quote", json={"items": [{"product_id": i["asado"], "quantity": 1, "grams": 1500}], "delivery_method": "retiro"}).json()
    assert q["items"][0]["grams"] == 1500 and q["items"][0]["unit_price"] == 13500 and q["items"][0]["modifiers_text"] == "1,5 kg"
    assert q["subtotal"] == 13500
    assert c.get(f"/api/v1/products/{i['coca']}").json()["weight"] is None


def test_catalogo_segun_el_rubro(env):
    from app.db import SessionLocal
    from app.models import Store, StoreCategory
    from app.services import weight
    i = ids()
    c = client()
    page = c.get("/tienda/burger-mix").text
    assert 'class="mlist"' in page and "mtile" not in page and "/kg" in page and "Elegís cuánto" in page
    st = c.get("/api/v1/stores/burger-mix").json()["store"]
    assert st["catalog_style"] == "menu" and st["rubro"] == "restaurante"
    with SessionLocal() as db:
        cat = StoreCategory(name="Carnicería", slug="carniceria")
        db.add(cat); db.flush()
        db.get(Store, i["store"]).store_category_id = cat.id
        db.commit()
        assert weight.catalog_style(db.get(Store, i["store"])) == "grid"
    page = c.get("/tienda/burger-mix").text
    assert 'class="mgrid"' in page and "mtile" in page and "x kg" in page and "rubro-carniceria" in page and "#B91C1C" in page
    st = c.get("/api/v1/stores/burger-mix").json()["store"]
    assert st["catalog_style"] == "grid" and st["rubro"] == "carniceria" and st["accent"] == "#B91C1C"


def test_el_local_carga_productos_por_peso_y_el_estilo(env):
    from app.db import SessionLocal
    from app.models import Product, Store
    i = ids()
    owner = client()
    assert owner.post("/admin/login", data=OWNER, follow_redirects=False).status_code == 303
    page = owner.get("/admin/products").text
    assert 'name="sold_by_weight"' in page and "⚖️ Por kg" in page
    token = page.split('name="csrf_token" value="')[1].split('"')[0]
    owner.post("/admin/products", data={"csrf_token": token, "name": "Queso cremoso", "price": "8.000", "store_id": str(i["store"]),
                                        "sold_by_weight": "1", "weight_step": "100", "weight_min": "200"})
    with SessionLocal() as db:
        q = db.query(Product).filter_by(name="Queso cremoso").one()
        assert q.sold_by_weight and q.weight_step == 100 and q.weight_min == 200 and q.price == Decimal("8000")
        qid = q.id
    owner.post(f"/admin/products/{qid}/edit", data={"csrf_token": token, "name": "Queso cremoso", "price": "8000", "store_id": str(i["store"])})
    with SessionLocal() as db:
        q = db.get(Product, qid)
        assert not q.sold_by_weight and q.weight_step is None
    page = owner.get("/admin/stores").text
    assert 'name="catalog_style"' in page
    form = {"csrf_token": token, "name": "Burger Mix", "slug": "burger-mix", "delivery_enabled": "on", "delivery_cost": "1500", "minimum_order": "0", "estimated_minutes": "30"}
    owner.post(f"/admin/stores/{i['store']}/edit", data={**form, "catalog_style": "menu"})
    with SessionLocal() as db:
        assert db.get(Store, i["store"]).catalog_style == "menu"
    owner.post(f"/admin/stores/{i['store']}/edit", data={**form, "catalog_style": "cualquiera"})
    with SessionLocal() as db:
        assert db.get(Store, i["store"]).catalog_style is None


def test_la_app_ve_el_peso_del_pedido_y_los_puntos(env):
    from app.db import SessionLocal
    from app.models import Order
    from app.routers.mobile_api import order_json
    with SessionLocal() as db:
        o = db.query(Order).filter(Order.items.any()).order_by(Order.id.desc()).first()
        j = order_json(o)
    item = j["items"][0]
    assert item["grams"] == 1000 and item["current_price"] == 12000 and j["points_earned"] == 0


def test_rubros_con_color_y_secciones_con_emoji(env):
    from app.services import weight
    assert weight.theme_for("supermercados Supermercados") == {"key": "super", "accent": "#16A34A"}
    assert weight.theme_for("") == {"key": "restaurante", "accent": "#6C2BD9"}
    c = client()
    cats = c.get("/api/v1/home").json()["store_categories"]
    carn = next(x for x in cats if x["name"] == "Carnicería")
    assert carn["key"] == "carniceria" and carn["accent"] == "#B91C1C" and carn["emoji"] == "🥩"
    menu = c.get("/api/v1/stores/burger-mix").json()["menu"]
    assert all(m["emoji"] for m in menu)


def _weight_order(c, grams=1000, payment="efectivo"):
    from app.db import SessionLocal
    from app.models import Order
    i = ids()
    c.post("/api/cart/clear")
    c.post("/api/cart/add", json={"product_id": i["nalga"], "quantity": 1, "modifiers": [], "grams": grams})
    c.post("/api/cart/add", json={"product_id": i["coca"], "quantity": 1})
    r = c.post("/checkout", data={"first_name": "Ana", "last_name": "Paz", "phone": "2914001122", "delivery_method": "retiro",
                                  "payment_method": payment, "call_if_missing": "1"}, follow_redirects=False)
    assert r.status_code == 303, r.text[:300]
    oid = int(r.headers["location"].split("/pedido/")[1].split("?")[0].split("/")[0])
    with SessionLocal() as db:
        o = db.get(Order, oid)
        it = next(x for x in o.items if x.weight_grams)
        return oid, it.id


def test_peso_real_dentro_del_margen_ajusta_el_total(env):
    from app.db import SessionLocal
    from app.models import AuditLog, Order
    from app.services import weight
    c = client()
    oid, iid = _weight_order(c)
    with SessionLocal() as db:
        o = db.get(Order, oid)
        assert o.call_if_missing and o.items[0].price_per_kg == Decimal("12000.00")
        before = o.total
        assert weight.set_real(db, o, {iid: 1080}) == "ok"  # +8 %: dentro del 10 %
        db.commit()
        o = db.get(Order, oid)
        it = next(x for x in o.items if x.id == iid)
        assert it.weight_real_grams == 1080 and it.unit_price == Decimal("12960.00") and o.total == before + Decimal("960.00")
        assert db.query(AuditLog).filter_by(action="peso_real_ajuste", entity_id=str(oid)).count() == 1


def test_peso_real_fuera_del_margen_lo_acepta_el_cliente(env):
    from app.db import SessionLocal
    from app.models import Order
    from app.routers.public import order_token
    from app.services import weight
    c = client()
    oid, iid = _weight_order(c)
    with SessionLocal() as db:
        o = db.get(Order, oid)
        before = o.total
        assert weight.set_real(db, o, {iid: 1250}) == "pending"  # +25 %: tiene que aceptar
        db.commit()
        assert db.get(Order, oid).total == before
    j = c.get(f"/api/v1/orders/{oid}?t={order_token(oid)}").json()
    assert j["weight"]["status"] == "pending" and j["weight"]["diff"] == 3000 and j["call_if_missing"] is True
    assert c.post(f"/api/v1/orders/{oid}/weight", json={"t": "malo", "accept": True}).status_code == 404
    r = c.post(f"/api/v1/orders/{oid}/weight", json={"t": order_token(oid), "accept": True}).json()
    assert r["ok"] and r["order"]["weight"]["status"] == "accepted" and r["order"]["total"] == float(before) + 3000
    assert c.post(f"/api/v1/orders/{oid}/weight", json={"t": order_token(oid), "accept": True}).status_code == 400  # ya respondió
    # el que no acepta: el total no cambia y el local lo vuelve a pesar
    oid2, iid2 = _weight_order(c)
    with SessionLocal() as db:
        weight.set_real(db, db.get(Order, oid2), {iid2: 700}); db.commit()
        total = db.get(Order, oid2).total
    r = c.post(f"/api/v1/orders/{oid2}/weight", json={"t": order_token(oid2), "accept": False}).json()
    assert r["order"]["weight"]["status"] == "rejected" and r["order"]["total"] == float(total)


def test_peso_real_con_pago_online_no_cambia_el_cobro(env):
    from app.db import SessionLocal
    from app.models import Order
    from app.services import weight
    c = client()
    oid, iid = _weight_order(c)
    with SessionLocal() as db:
        o = db.get(Order, oid)
        o.payment_method = "mercadopago"
        from datetime import datetime
        o.paid_at = datetime.utcnow()
        before = o.total
        assert weight.set_real(db, o, {iid: 1300}) == "fixed"
        db.commit()
        assert db.get(Order, oid).total == before
        o = db.get(Order, oid)
        o.status = __import__("app.models", fromlist=["OrderStatus"]).OrderStatus.EN_CAMINO
        with pytest.raises(weight.WeightError):
            weight.set_real(db, o, {iid: 1000})


def test_el_local_carga_el_peso_desde_el_panel(env):
    from app.db import SessionLocal
    from app.models import Order, Product
    c = client()
    oid, iid = _weight_order(c)
    owner = client()
    assert owner.post("/admin/login", data=OWNER, follow_redirects=False).status_code == 303
    page = owner.get(f"/admin/orders/{oid}").text
    assert "Peso real" in page and f'name="g{iid}"' in page and "Si falta algo, llamá" in page
    token = page.split('name="csrf_token" value="')[1].split('"')[0]
    owner.post(f"/admin/orders/{oid}/peso", data={"csrf_token": token, f"g{iid}": "950"})
    with SessionLocal() as db:
        o = db.get(Order, oid)
        assert o.weight_status == "ok" and next(x for x in o.items if x.id == iid).weight_real_grams == 950
        nalga = db.query(Product).filter_by(name="Nalga").one()
        pid = nalga.id
    owner.post(f"/admin/products/{pid}/edit", data={"csrf_token": token, "name": "Nalga", "price": "12000", "store_id": str(ids()["store"]),
                                                     "sold_by_weight": "1", "prep_options": "Milanesas, Bifes, Entera"})
    j = client().get(f"/api/v1/products/{pid}").json()
    g = next(x for x in j["groups"] if x["name"] == "¿Cómo te lo preparamos?")
    assert [o["name"] for o in g["options"]] == ["Milanesas", "Bifes", "Entera"] and g["max_select"] == 1


def test_precio_por_unidad_de_medida(env):
    from app.models import Product
    from app.services import weight
    assert weight.unit_price_text(Product(name="Leche", price=Decimal("1350"), content_amount=Decimal("1"), content_unit="L")) == "$1.350 / L"
    assert weight.unit_price_text(Product(name="Manteca", price=Decimal("2960"), content_amount=Decimal("200"), content_unit="g")) == "$14.800 / kg"
    assert weight.unit_price_text(Product(name="Huevos", price=Decimal("4300"), content_amount=Decimal("12"), content_unit="u")) == "$358 / u"
    assert weight.unit_price_text(Product(name="x", price=Decimal("1"))) is None
