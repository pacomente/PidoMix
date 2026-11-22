"""Panel: "Cómo funciona" (tutorial), botón de Ayuda en cada pantalla, recorrido guiado y menú lateral ordenado."""
import os
import sys

import pytest


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("help") / "help.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["ENVIRONMENT"] = "development"
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]
    from app import seed
    from app.db import Base, SessionLocal, engine
    from app.models import Role, Store, User
    from app.services.auth import hash_password
    Base.metadata.create_all(engine)
    seed.ADMIN_EMAIL = "admin@test.local"
    seed.settings.admin_password = "TestOnly-123!"
    seed.run_seed()
    with SessionLocal() as db:
        store = db.query(Store).filter_by(slug="burger-mix").one()
        db.add(User(email="dueno@help.local", password_hash=hash_password("Dueno-1234"), role=Role.STORE_ADMIN, store_id=store.id, active=True))
        db.add(User(email="cajero@help.local", password_hash=hash_password("Cajero-1234"), role=Role.STORE_STAFF, store_id=store.id, active=True))
        db.commit()
    yield
    engine.dispose()


def login(email, password):
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    assert c.post("/admin/login", data={"email": email, "password": password}, follow_redirects=False).status_code == 303
    return c


def test_el_dueno_ve_el_tutorial_completo(env):
    c = login("dueno@help.local", "Dueno-1234")
    r = c.get("/admin/ayuda")
    assert r.status_code == 200
    for anchor in ("primeros-pasos", "pedidos", "menu", "pagos", "clientes", "reportes", "equipo", "preguntas"):
        assert f'id="{anchor}"' in r.text
    assert "/admin?recorrido=1" in r.text and "/admin/menu/importar" in r.text


def test_cada_pantalla_tiene_su_ayuda_y_el_menu_esta_ordenado(env):
    c = login("dueno@help.local", "Dueno-1234")
    page = c.get("/admin/products").text
    assert 'href="/admin/ayuda#menu"' in page  # el botón Ayuda lleva a la parte del menú
    assert 'href="/admin/ayuda#pagos"' in c.get("/admin/pagos").text
    nav = page[page.index('<nav class="admin-nav">'):page.index("</nav>")]
    groups = [g.split("</h4>")[0] for g in nav.split("<h4>")[1:]]
    assert groups == ["Mi local", "Menú", "Clientes", "Números"]
    assert "Cargar desde planilla" in nav and "QR del menú" in nav and "Comercios y planes" not in nav
    home = c.get("/admin").text
    assert "/static/js/tour.js" in home  # el recorrido guiado de la primera vez


def test_el_personal_ve_solo_lo_suyo(env):
    c = login("cajero@help.local", "Cajero-1234")
    r = c.get("/admin/ayuda")
    assert r.status_code == 200 and 'id="pedidos"' in r.text
    assert 'id="pagos"' not in r.text and 'id="menu"' not in r.text and "recorrido" not in r.text


def test_superadmin_conserva_su_menu(env):
    c = login("admin@test.local", "TestOnly-123!")
    page = c.get("/admin/products").text
    nav = page[page.index('<nav class="admin-nav">'):page.index("</nav>")]
    groups = [g.split("</h4>")[0] for g in nav.split("<h4>")[1:]]
    assert groups == ["Comercios", "Menú", "Clientes", "Números", "Sistema"]
    assert "Solicitudes de comercios" in nav and "Configuración" in nav
    assert "/static/js/tour.js" not in c.get("/admin").text
