"""Smoke test de punta a punta: levanta la app sobre SQLite, carga datos demo y
recorre las paginas publicas, el carrito, el checkout y el panel admin."""
import os
import sys

import pytest


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("pages") / "pages.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["ENVIRONMENT"] = "development"
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]

    from fastapi.testclient import TestClient
    from app.db import Base, SessionLocal, engine
    from app import seed
    from app.main import app
    from app.models import ModifierGroup, ModifierOption, Product

    Base.metadata.create_all(engine)
    seed.ADMIN_EMAIL = "admin@test.local"
    seed.settings.admin_password = "TestOnly-123!"
    seed.run_seed()
    with SessionLocal() as db:
        burger = db.query(Product).filter_by(name="Hamburguesa Clásica").one()
        group = ModifierGroup(product_id=burger.id, name="Extras <b>", max_select=2)
        db.add(group); db.flush()
        db.add(ModifierOption(group_id=group.id, name="Cheddar", price_extra=500))
        db.commit()
    yield TestClient(app)
    engine.dispose()


def test_public_pages(client):
    for url in ["/", "/tiendas", "/tiendas?sort=rapidos", "/tienda/burger-mix", "/categoria/hamburguesas", "/buscar?q=coca", "/favoritos", "/mis-pedidos", "/checkout", "/robots.txt", "/sitemap.xml", "/health"]:
        r = client.get(url)
        assert r.status_code == 200, (url, r.status_code)
    assert client.get("/tienda/no-existe").status_code == 404


def test_store_menu_groups_products(client):
    html = client.get("/tienda/burger-mix").text
    assert "Hamburguesa Clásica" in html and "Coca Cola" in html
    assert 'id="cat-' in html


def test_cart_and_checkout(client):
    from app.db import SessionLocal
    from app.models import ModifierOption, Product
    with SessionLocal() as db:
        coca = db.query(Product).filter_by(name="Coca Cola").one().id
        burger = db.query(Product).filter_by(name="Hamburguesa Clásica").one().id
        cheddar = db.query(ModifierOption).filter_by(name="Cheddar").one().id
    r = client.post("/api/cart/add", json={"product_id": coca, "quantity": 2})
    assert r.status_code == 200 and r.json()["count"] == 2
    r = client.post("/api/cart/add", json={"product_id": burger, "modifiers": [cheddar]})
    data = r.json()
    assert data["count"] == 3 and data["subtotal"] == 2 * 2000 + 10500
    r = client.post("/checkout", data={"first_name": "Ana", "last_name": "Paz", "phone": "123", "delivery_method": "retiro"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/pedido/")
    assert client.get(r.headers["location"]).status_code == 200
    assert client.get("/mis-pedidos").status_code == 200
    assert client.get("/api/cart").json()["count"] == 0


def test_admin_pages(client):
    r = client.post("/admin/login", data={"email": "admin@test.local", "password": "TestOnly-123!"}, follow_redirects=False)
    assert r.status_code == 303
    for url in ["/admin", "/admin/stores", "/admin/products", "/admin/orders", "/admin/orders/pending", "/admin/reports", "/admin/customers", "/admin/users", "/admin/coupons", "/admin/reviews", "/admin/categories", "/admin/banners", "/admin/settings", "/admin/sections", "/admin/reports/export.csv"]:
        r = client.get(url, follow_redirects=False)
        assert r.status_code == 200, (url, r.status_code)
    r = client.post("/admin/stores/1/hours", data={"d0_open": "10:00", "d0_close": "22:00"}, follow_redirects=False)
    assert r.status_code == 303


def test_static_assets_are_compressed_and_cached(client):
    r = client.get("/static/css/trappi.css?v=1", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers.get("content-encoding") == "gzip"
    assert "max-age" in r.headers.get("cache-control", "")


def test_bulk_price_update(client):
    from decimal import Decimal
    from app.db import SessionLocal
    from app.models import Product
    client.post("/admin/login", data={"email": "admin@test.local", "password": "TestOnly-123!"})
    r = client.post("/admin/products/bulk-price", data={"store_id": 1, "percent": 10}, follow_redirects=False)
    assert r.status_code == 303 and "ok=prices" in r.headers["location"]
    with SessionLocal() as db:
        assert db.query(Product).filter_by(name="Coca Cola").one().price == Decimal("2200.00")


def test_login_limit_ignores_spoofed_forwarded_for(client):
    from app.routers import admin
    for i in range(admin.account_limiter.limit):
        r = client.post("/admin/login", data={"email": "victima@test.local", "password": "mala"}, headers={"X-Forwarded-For": f"10.0.0.{i}"})
        assert r.status_code == 401
    r = client.post("/admin/login", data={"email": "victima@test.local", "password": "mala"}, headers={"X-Forwarded-For": "10.9.9.9"})
    assert r.status_code == 429


def _delivered_order(first_name="Lucía", last_name="gómez"):
    from app.db import SessionLocal
    from app.models import Customer, Order, OrderStatus
    from app.routers.public import order_token
    with SessionLocal() as db:
        order = Order(store_id=1, customer=Customer(first_name=first_name, last_name=last_name, phone="1"), delivery_method="retiro", subtotal=1000, shipping=0, total=1000, status=OrderStatus.ENTREGADO)
        db.add(order); db.commit()
        return order.id, order_token(order.id)


def _store():
    from app.db import SessionLocal
    from app.models import Store
    with SessionLocal() as db:
        s = db.get(Store, 1)
        return float(s.rating_avg), s.rating_count


def test_review_flow(client):
    from app.db import SessionLocal
    from app.models import Review
    oid, t = _delivered_order()
    assert client.post(f"/pedido/{oid}/review", data={"t": t, "rating": 9}).status_code == 200  # fuera de rango: se ignora
    assert _store()[1] == 0
    client.post(f"/pedido/{oid}/review", data={"t": t, "rating": 4, "comment": "  Muy rico <script>x</script> "})
    client.post(f"/pedido/{oid}/review", data={"t": t, "rating": 1})  # doble envio: no pisa ni duplica
    assert _store() == (4.0, 1)
    oid2, t2 = _delivered_order("Pedro", "")
    client.post(f"/pedido/{oid2}/review", data={"t": t2, "rating": 1})
    assert _store() == (2.5, 2)

    html = client.get("/tienda/burger-mix").text
    assert 'id="opiniones"' in html and "Lucía G." in html and "&lt;script&gt;" in html and "<script>x" not in html
    page = client.get("/tienda/burger-mix/opiniones").text
    assert "Pedro" in page and "2.5" in page
    assert "Calificar" not in client.get("/mis-pedidos").text  # pedidos de esta sesion no entregados

    with SessionLocal() as db:
        rid = db.query(Review).filter_by(order_id=oid2).one().id
    client.post("/admin/login", data={"email": "admin@test.local", "password": "TestOnly-123!"})
    assert "Sin responder (2)" in client.get("/admin/reviews").text
    client.post(f"/admin/reviews/{rid}/reply", data={"reply": "Perdón, lo vamos a mejorar"})
    assert "Sin responder (1)" in client.get("/admin/reviews").text
    assert "Respuesta del local" in client.get("/tienda/burger-mix/opiniones").text
    for f in ["sin_respuesta", "con_comentario", "negativas", "ocultas"]:
        assert client.get(f"/admin/reviews?filter={f}").status_code == 200
    client.post(f"/admin/reviews/{rid}/hide")  # moderada: deja de contar en el promedio
    assert _store() == (4.0, 1)
    assert "Pedro" not in client.get("/tienda/burger-mix/opiniones").text
    client.post(f"/admin/reviews/{rid}/hide")
    assert _store() == (2.5, 2)


def test_store_admin_can_reply_but_not_hide(client):
    from fastapi.testclient import TestClient
    from app.db import SessionLocal
    from app.main import app
    from app.models import Review, Role, User
    from app.services.auth import hash_password
    with SessionLocal() as db:
        db.add(User(email="local@test.local", password_hash=hash_password("Local-123!"), role=Role.STORE_ADMIN, store_id=1)); db.commit()
        rid = db.query(Review).filter(Review.hidden.is_(False)).first().id
    owner = TestClient(app)
    owner.post("/admin/login", data={"email": "local@test.local", "password": "Local-123!"})
    assert "Ocultar (moderar)" not in owner.get("/admin/reviews").text
    owner.post(f"/admin/reviews/{rid}/hide")
    owner.post(f"/admin/reviews/{rid}/reply", data={"reply": "¡Gracias!"})
    with SessionLocal() as db:
        r = db.get(Review, rid)
        assert r.hidden is False and r.reply == "¡Gracias!"


def _new_order(client_, delivery="retiro", **extra):
    """Pedido real por el checkout (asi se registra el evento inicial)."""
    from app.db import SessionLocal
    from app.models import Product
    with SessionLocal() as db:
        coca = db.query(Product).filter_by(name="Coca Cola").one().id
    client_.post("/api/cart/clear")
    client_.post("/api/cart/add", json={"product_id": coca})
    data = {"first_name": "Rita", "last_name": "Luz", "phone": "+54 9 291 555-0000", "delivery_method": delivery, "address": "Calle 1", "notes": "Sin hielo", **extra}
    tracking = client_.post("/checkout", data=data, follow_redirects=False).headers["location"]
    return int(tracking.split("/pedido/")[1].split("?")[0]), tracking


def _status(oid):
    from app.db import SessionLocal
    from app.models import Order
    with SessionLocal() as db:
        o = db.get(Order, oid)
        return o.status.value, [e.status for e in o.events]


def test_order_status_flow(client):
    from fastapi.testclient import TestClient
    from app.main import app
    shopper = TestClient(app)
    oid, tracking = _new_order(shopper)
    assert _status(oid) == ("PENDIENTE", ["PENDIENTE"])
    client.post("/admin/login", data={"email": "admin@test.local", "password": "TestOnly-123!"})

    board = client.get("/admin/orders").text
    assert f"#{oid}" in board and "Sin hielo" in board and "Confirmar pedido" in board and "wa.me/5492915550000?text=" not in board  # pendiente: sin mensaje sugerido
    # saltar etapas no se permite
    r = client.post(f"/admin/orders/{oid}/status", data={"status": "ENTREGADO"}, follow_redirects=False)
    assert "error=status" in r.headers["location"] and _status(oid)[0] == "PENDIENTE"
    # avance via fetch (tablero sin recarga)
    r = client.post(f"/admin/orders/{oid}/status", data={"status": "CONFIRMADO"}, headers={"X-Requested-With": "fetch"})
    assert r.status_code == 200 and r.json()["ok"]
    r = client.post(f"/admin/orders/{oid}/status", data={"status": "LISTO"}, headers={"X-Requested-With": "fetch"})
    assert r.status_code == 409 and not r.json()["ok"]
    # deshacer un clic equivocado
    client.post(f"/admin/orders/{oid}/status", data={"status": "PREPARANDO"})
    client.post(f"/admin/orders/{oid}/status", data={"status": "CONFIRMADO"})
    assert _status(oid)[0] == "CONFIRMADO"
    detail = client.get(f"/admin/orders/{oid}").text
    assert "Historial del pedido" in detail and "Volver a «Pendiente»" in detail and "/pedido/" in detail and "wa.me/5492915550000?text=" in detail
    for st in ["PREPARANDO", "LISTO", "ENTREGADO"]:  # retiro: no pasa por "En camino"
        client.post(f"/admin/orders/{oid}/status", data={"status": st})
    assert _status(oid) == ("ENTREGADO", ["PENDIENTE", "CONFIRMADO", "PREPARANDO", "CONFIRMADO", "PREPARANDO", "LISTO", "ENTREGADO"])
    client.post(f"/admin/orders/{oid}/status", data={"status": "CANCELADO"})  # pedido cerrado: no se reabre
    assert _status(oid)[0] == "ENTREGADO"
    assert 'class="step-time"' in shopper.get(tracking).text  # el cliente ve la hora de cada etapa

    pending = client.get("/admin/orders/pending").json()
    assert set(pending) == {"pending", "latest", "stamp"} and pending["latest"] >= oid


def test_order_history_filters(client):
    client.post("/admin/login", data={"email": "admin@test.local", "password": "TestOnly-123!"})
    from app.db import SessionLocal
    from app.models import Order, OrderStatus
    with SessionLocal() as db:
        delivered = db.query(Order).filter(Order.status == OrderStatus.ENTREGADO).first().id
    def hist(**params):
        return client.get("/admin/orders", params=params).text.split('id="history"')[1]
    assert f"#{delivered}" in hist(q=f"#{delivered}")
    assert f"#{delivered}" not in hist(status="CANCELADO")
    assert "No hay pedidos con esos filtros" in hist(q="nadie-se-llama-asi")
    assert "No hay pedidos con esos filtros" in hist(date_from="2001-01-01", date_to="2001-01-02")
    assert "No hay pedidos con esos filtros" not in hist(date_from="2001-01-01", date_to="2099-12-31", page="1")


def test_customer_message():
    from types import SimpleNamespace as NS
    from app.models import OrderStatus
    from app.services.orders import customer_message
    o = NS(id=7, status=OrderStatus.LISTO, delivery_method="retiro", customer=NS(first_name="ana maría"), store=NS(name="Burger Mix"))
    assert customer_message(o) == "Hola Ana, tu pedido #7 está listo. ¡Te esperamos en Burger Mix!"
    o.delivery_method = "delivery"
    assert "sale en breve" in customer_message(o)
    o.status = OrderStatus.PENDIENTE
    assert customer_message(o) is None


def test_comandas_mode(client):
    from fastapi.testclient import TestClient
    from app.main import app
    anon = TestClient(app)
    r = anon.get("/admin/comandas", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/login?next=%2Fadmin%2Fcomandas"
    r = anon.post("/admin/login?next=%2Fadmin%2Fcomandas", data={"email": "admin@test.local", "password": "TestOnly-123!"}, follow_redirects=False)
    assert r.headers["location"] == "/admin/comandas"  # vuelve a la pantalla de comandas
    assert anon.get("/admin/comandas/board").status_code == 200

    shopper = TestClient(app)
    oid, _ = _new_order(shopper, delivery="delivery", reference="Timbre 3B")
    page = anon.get("/admin/comandas").text
    assert 'rel="manifest" href="/admin/comandas/manifest.webmanifest"' in page and "Empezar a recibir pedidos" in page
    board = anon.get("/admin/comandas/board")
    assert board.headers["cache-control"] == "no-store"
    assert 'data-pending="' in board.text and str(oid) in board.text.split('data-pending="')[1].split('"')[0]
    assert "Aceptar pedido" in board.text and "Timbre 3B" in board.text and "Sin hielo" in board.text

    ticket = anon.get(f"/admin/comandas/ticket/{oid}").text
    assert f"#{oid}" in ticket and "DELIVERY" in ticket and "Sin hielo" in ticket and "80mm" in ticket
    assert anon.get("/admin/comandas/ticket/999999").status_code == 404

    manifest = anon.get("/admin/comandas/manifest.webmanifest").json()
    assert manifest["start_url"] == "/admin/comandas" and manifest["display"] == "standalone"
    for icon in manifest["icons"]:
        assert anon.get(icon["src"]).status_code == 200
    sw = anon.get("/admin/comandas/sw.js")
    assert sw.headers["service-worker-allowed"] == "/admin/comandas" and "notificationclick" in sw.text


def test_login_next_is_only_internal(client):
    from app.routers.admin import safe_next
    assert safe_next("/admin/comandas") == "/admin/comandas"
    for bad in ["https://evil.com", "//evil.com", "/admin//evil.com", "/admin\\\\evil", "/tienda/x", "/admin/login", None, ""]:
        assert safe_next(bad) == "/admin"


def test_money_format_and_dashboard(client):
    from app.services.formatting import money
    assert [money(166500), money("2000.00"), money(1234.5), money(-150), money(None)] == ["$166.500", "$2.000", "$1.234,50", "-$150", "$0"]
    client.post("/admin/login", data={"email": "admin@test.local", "password": "TestOnly-123!"})
    html = client.get("/admin").text
    assert "Ventas de los últimos 7 días" in html and 'href="/admin/comandas"' in html and "Inicio" in html
    assert "{:,.0f}" not in html and "$2000.00" not in client.get("/admin/products").text


def test_public_design_helpers(client):
    from app.services.formatting import visual
    assert visual("Burger Mix", "Restaurante")["emoji"] == "🍔"
    assert visual("Restaurante")["emoji"] == "🍽️"  # "te" no matchea dentro de "restaurante"
    assert visual("Algo raro")["emoji"] == "🏪" and visual("X")["hue"] == visual("X")["hue"]
    html = client.get("/tienda/burger-mix").text
    import re
    assert re.search(r"\$\d{1,3}\.\d{3}", html) and not re.search(r"\$\d{4,}", html)  # $11.000, nunca $11000
    assert 's-cover ph' in html
    checkout = client.get("/checkout").text
    assert "on-checkout" in checkout  # la barra flotante del carrito no tapa el boton de confirmar
    assert "No encontramos nada" in client.get("/buscar?q=zzzz").text
