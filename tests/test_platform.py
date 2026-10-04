"""Configuración de la plataforma: apagar apps, pausar pedidos, repartidores y mapas."""
import os
import sys

import pytest


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("platform") / "platform.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["ENVIRONMENT"] = "development"
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]
    from fastapi.testclient import TestClient
    from app import seed
    from app.db import Base, engine
    from app.main import app
    Base.metadata.create_all(engine)
    seed.ADMIN_EMAIL = "admin@test.local"
    seed.settings.admin_password = "TestOnly-123!"
    seed.run_seed()
    c = TestClient(app)
    c.post("/admin/login", data={"email": "admin@test.local", "password": "TestOnly-123!"})
    yield c
    engine.dispose()


def save(c, **changes):
    from app.services import platform
    form = {}
    for o in platform.OPTIONS:
        if o.kind == "bool":  # los checkbox apagados no se mandan; los no tocados quedan como estaban
            if changes.get(o.key, _current(o.key)):
                form[o.key] = "1"
        elif o.key in changes:
            form[o.key] = str(changes[o.key])
    r = c.post("/admin/settings", data=form, follow_redirects=False)
    assert r.status_code == 303
    platform.invalidate()


def _current(key):
    from app.services import platform
    return platform.current()[key]


def test_pagina_y_valores_por_defecto(env):
    page = env.get("/admin/settings").text
    for txt in ("Apps y mantenimiento", "Repartidores", "Mapas y direcciones", "App de repartidores activa", "Segundos para aceptar una oferta"):
        assert txt in page
    cfg = env.get("/api/v1/config").json()
    assert cfg["app"]["enabled"] and cfg["app"]["min_version"] == "1.0.0" and cfg["orders"]["enabled"]
    drv = env.get("/api/courier/v1/config").json()
    assert drv["app"]["enabled"] and drv["map_style"].startswith("https://tiles.openfreemap.org/") and drv["pulse_seconds"] == 4


def test_apagar_apps_y_web(env):
    save(env, app_clientes_enabled=False, app_clientes_message="Volvemos a las 15 hs", app_repartidor_enabled=False, web_enabled=False, app_clientes_min_version="1.3.0")
    r = env.get("/api/v1/home")
    assert r.status_code == 503 and r.json() == {"ok": False, "maintenance": True, "error": "Volvemos a las 15 hs"}
    cfg = env.get("/api/v1/config").json()  # /config sigue respondiendo para que la app muestre el aviso
    assert not cfg["app"]["enabled"] and cfg["app"]["min_version"] == "1.3.0" and cfg["min_app_version"] == "1.3.0"
    assert env.post("/api/courier/v1/login", json={"phone": "1", "pin": "1"}).status_code == 503
    assert not env.get("/api/courier/v1/config").json()["app"]["enabled"]
    web = env.get("/")
    assert web.status_code == 503 and "mantenimiento" in web.text.lower()
    assert env.get("/admin/settings").status_code == 200  # el panel sigue andando
    save(env, app_clientes_enabled=True, app_repartidor_enabled=True, web_enabled=True)
    assert env.get("/api/v1/home").status_code == 200 and env.get("/").status_code == 200


def test_pausar_pedidos(env):
    from app.db import SessionLocal
    from app.models import Product
    with SessionLocal() as db:
        coca = db.query(Product).filter_by(name="Coca Cola").one().id
    save(env, orders_enabled=False, orders_message="Pausamos los pedidos por lluvia")
    r = env.post("/api/v1/orders", json={"items": [{"product_id": coca}], "delivery_method": "retiro", "first_name": "Ana", "phone": "1"})
    assert r.status_code == 400 and r.json()["error"] == "Pausamos los pedidos por lluvia"
    save(env, orders_enabled=True)
    r = env.post("/api/v1/orders", json={"items": [{"product_id": coca}], "delivery_method": "retiro", "first_name": "Ana", "phone": "1"})
    assert r.status_code == 200


def test_reglas_de_repartidores_y_mapas(env):
    from decimal import Decimal
    from app.services import platform
    save(env, dispatch_offer_seconds="20", dispatch_radius_km="3,5", courier_pay_mode="percent", courier_pay_value="80",
         driver_map_style="custom", driver_map_style_url="https://api.maptiler.com/maps/streets/style.json?key=x", web_tiles_url="https://tiles.ejemplo.com/{z}/{x}/{y}.png")
    cfg = platform.current()
    assert cfg["dispatch_offer_seconds"] == 20 and cfg["dispatch_radius_km"] == 3.5
    assert platform.courier_pay(cfg, Decimal("1500")) == Decimal("1200.00")
    assert env.get("/api/courier/v1/config").json()["map_style"] == "https://api.maptiler.com/maps/streets/style.json?key=x"
    assert 'data-tiles="https://tiles.ejemplo.com/{z}/{x}/{y}.png"' in env.get("/").text
    save(env, dispatch_offer_seconds="999", courier_pay_mode="fixed", courier_pay_value="1.000")  # fuera de rango: se ajusta al máximo
    cfg = platform.current()
    assert cfg["dispatch_offer_seconds"] == 120 and platform.courier_pay(cfg, Decimal("1500")) == Decimal("1000.00")
