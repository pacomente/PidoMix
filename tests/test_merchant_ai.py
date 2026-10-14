"""IA para comercios, fotos con Cloudinary (mejora, fondo blanco y borrado) y "se piden juntos"."""
import os
import re
import sys
from decimal import Decimal

import pytest

ADMIN = {"email": "admin@test.local", "password": "TestOnly-123!"}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("mai") / "mai.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["ENVIRONMENT"] = "development"
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]
    from app import seed
    from app.db import Base, engine
    Base.metadata.create_all(engine)
    seed.ADMIN_EMAIL = ADMIN["email"]
    seed.settings.admin_password = ADMIN["password"]
    seed.run_seed()
    yield
    engine.dispose()


def client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def login(email, password):
    c = client()
    assert c.post("/admin/login", data={"email": email, "password": password}, follow_redirects=False).status_code == 303
    return c


def owner():
    from app.db import SessionLocal
    from app.models import Store, User
    from app.services.auth import hash_password
    with SessionLocal() as db:
        s = db.query(Store).filter_by(slug="burger-mix").one()
        if not db.query(User).filter_by(email="dueno@mai.test").first():
            db.add(User(email="dueno@mai.test", password_hash=hash_password("Dueno-1234"), store_id=s.id)); db.commit()
        return s.id, login("dueno@mai.test", "Dueno-1234")


def setting(**values):
    from app.db import SessionLocal
    from app.models import Setting
    from app.services import platform
    with SessionLocal() as db:
        for k, v in values.items():
            row = db.query(Setting).filter_by(key=k).first()
            v = "1" if v is True else "0" if v is False else str(v)
            if row: row.value = v
            else: db.add(Setting(key=k, value=v))
        db.commit()
    platform.invalidate()


def token(c, path="/admin/products"):
    return re.search(r'name="csrf_token" value="([^"]+)"', c.get(path).text).group(1)


def test_urls_de_cloudinary(env):
    from app.services.images import cdn, upload_transformation, white_background
    u = "https://res.cloudinary.com/demo/image/upload/v17/pidomix/products/abc.jpg"
    assert cdn(u) == "https://res.cloudinary.com/demo/image/upload/f_auto,q_auto,c_limit,w_720/v17/pidomix/products/abc.jpg"
    w = white_background(u)
    assert "e_background_removal/b_white,c_pad,w_1200,h_1200/v17/" in w
    # la edicion guardada queda primero y despues el tamaño para mostrar
    assert cdn(w, "thumb").endswith("e_background_removal/b_white,c_pad,w_1200,h_1200/f_auto,q_auto,c_limit,w_160/v17/pidomix/products/abc.jpg")
    assert cdn(cdn(u)) == cdn(u) and white_background(w) == w
    assert {"effect": "improve"} in upload_transformation("pidomix/products", enhance=True)
    assert {"effect": "improve"} not in upload_transformation("pidomix/stores/logos", enhance=True)


def test_foto_con_fondo_blanco_y_borrado_en_cloudinary(env, monkeypatch):
    from app.db import SessionLocal
    from app.models import Banner, OrderItem, Product
    from app.routers import admin
    from app.services import cloudinary_service
    calls, deleted = [], []
    monkeypatch.setattr(admin, "upload", lambda content, folder, enhance=False: (calls.append((folder, enhance)) or
                        (f"https://res.cloudinary.com/demo/image/upload/v1/{folder}/f{len(calls)}.jpg", f"{folder}/f{len(calls)}")))
    monkeypatch.setattr(cloudinary_service, "with_white_background", lambda url, wait_seconds=25: cloudinary_service.white_background(url))
    monkeypatch.setattr(admin, "delete", lambda pid: deleted.append(pid) or True)
    setting(photo_enhance=True, photo_white_bg=True)
    sid, c = owner()
    png = ("foto.png", b"\x89PNG fake", "image/png")
    r = c.post("/admin/products", data={"name": "Burger nueva", "price": "5000", "store_id": str(sid), "csrf_token": token(c)}, files={"file": png}, follow_redirects=False)
    assert r.status_code == 303
    with SessionLocal() as db:
        p = db.query(Product).filter_by(name="Burger nueva").one()
        assert "e_background_removal/b_white" in p.image_url and calls[-1] == ("pidomix/products", True)
        pid, first = p.id, p.image_public_id
    # el local puede mantener el fondo; la foto anterior se borra de Cloudinary
    c.post(f"/admin/products/{pid}/edit", data={"name": "Burger nueva", "price": "5000", "store_id": str(sid), "keep_bg": "1", "csrf_token": token(c)}, files={"file": png})
    with SessionLocal() as db:
        p = db.get(Product, pid)
        assert "e_background_removal" not in p.image_url and first in deleted
    # producto vendido: se oculta, pero la foto se borra igual de Cloudinary
    from app.models import Order, OrderStatus
    with SessionLocal() as db:
        o = Order(store_id=sid, delivery_method="retiro", subtotal=Decimal("5000"), shipping=Decimal("0"), total=Decimal("5000"), status=OrderStatus.ENTREGADO)
        db.add(o); db.flush()
        db.add(OrderItem(order_id=o.id, product_id=pid, product_name="Burger nueva", unit_price=Decimal("5000"), quantity=1)); db.commit()
        current = db.get(Product, pid).image_public_id
    c.post(f"/admin/products/{pid}/delete", data={"csrf_token": token(c)})
    with SessionLocal() as db:
        p = db.get(Product, pid)
        assert p.deleted and p.image_url is None and current in deleted
    # banners: se pueden eliminar y se va la imagen
    a = login(**ADMIN)
    with SessionLocal() as db:
        b = Banner(image_url="https://res.cloudinary.com/demo/image/upload/v1/pidomix/banners/b.jpg", image_public_id="pidomix/banners/b", title="Promo")
        db.add(b); db.commit(); bid = b.id
    assert a.post(f"/admin/banners/{bid}/delete", data={"csrf_token": token(a, "/admin/banners")}, follow_redirects=False).headers["location"].endswith("ok=deleted")
    with SessionLocal() as db:
        assert db.get(Banner, bid) is None and "pidomix/banners/b" in deleted
    setting(photo_white_bg=False)


def test_limpieza_de_imagenes_sin_usar(env, monkeypatch):
    from app.routers import merchant_ai
    from app.services import cloudinary_service
    gone = []
    monkeypatch.setattr(cloudinary_service, "configured", lambda: True)
    monkeypatch.setattr(cloudinary_service, "list_resources", lambda prefix="pidomix/": [
        {"public_id": "pidomix/products/huerfana", "created_at": "2020-01-01T00:00:00Z", "bytes": 2048, "secure_url": "https://res.cloudinary.com/d/image/upload/v1/x.jpg"},
        {"public_id": "pidomix/products/recien", "created_at": "2999-01-01T00:00:00Z", "bytes": 10, "secure_url": "x"}])
    monkeypatch.setattr(cloudinary_service, "delete", lambda pid: gone.append(pid) or True)
    a = login(**ADMIN)
    page = a.get("/admin/imagenes").text
    assert "<b>1</b> imágenes sin usar" in page
    r = a.post("/admin/imagenes/limpiar", data={"csrf_token": token(a, "/admin/imagenes")}, follow_redirects=False)
    assert r.headers["location"].endswith("n=1") and gone == ["pidomix/products/huerfana"]
    _, c = owner()
    assert c.get("/admin/imagenes", follow_redirects=False).status_code == 303  # solo el superadmin


def test_ia_del_local(env):
    from app.db import SessionLocal
    from app.models import Order, OrderItem, OrderStatus, Product, ProductStatus
    sid, c = owner()
    setting(merchant_ai_enabled=False)
    assert c.get("/admin/ia", follow_redirects=False).status_code == 303  # apagada: el local no la ve
    assert "está apagada" in login(**ADMIN).get("/admin/ia").text
    setting(merchant_ai_enabled=True)
    with SessionLocal() as db:
        ps = db.query(Product).filter_by(store_id=sid, deleted=False, status=ProductStatus.ACTIVO).all()
        a, b = ps[0], ps[1]
        a.description = ""
        for _ in range(3):  # se piden juntos
            o = Order(store_id=sid, delivery_method="retiro", subtotal=Decimal("1"), shipping=Decimal("0"), total=Decimal("1000"), status=OrderStatus.ENTREGADO)
            db.add(o); db.flush()
            db.add_all([OrderItem(order_id=o.id, product_id=a.id, product_name=a.name, unit_price=Decimal("1"), quantity=1),
                        OrderItem(order_id=o.id, product_id=b.id, product_name=b.name, unit_price=Decimal("1"), quantity=1)])
        db.commit(); aid, aname, bname = a.id, a.name, b.name
    page = c.get("/admin/ia").text
    assert "Recomendaciones para" in page and "Armá un combo" in page and aname in page and "sin descripción" in page
    # escribir con IA (sin modelo: plantilla) — propone sin guardar, o guarda desde "IA del local"
    r = c.post(f"/admin/ia/descripcion/{aid}", headers={"X-CSRF-Token": token(c)}).json()
    assert r["ok"] and aname in r["text"] and "$" not in r["text"]
    c.post(f"/admin/ia/descripcion/{aid}?save=1", data={"csrf_token": token(c)})
    with SessionLocal() as db:
        assert aname in db.get(Product, aid).description
    # "los que pidieron esto también llevaron"
    from app.services import recommendations
    with SessionLocal() as db:
        assert [p.name for p in recommendations.bought_together(db, sid, [aid])][0] == bname
    setting(merchant_ai_enabled=False)
