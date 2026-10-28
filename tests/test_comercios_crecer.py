"""Herramientas para que el comercio crezca: link para compartir, tarjeta de sellos y resumen semanal por mail."""
import os
import sys
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

ADMIN = {"email": "admin@test.local", "password": "TestOnly-123!"}
OWNER = {"email": "dueno-crece@test.local", "password": "Dueno-1234"}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("crece") / "crece.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["ENVIRONMENT"] = "development"
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]
    from app import seed
    from app.db import Base, SessionLocal, engine
    from app.models import Role, Store, User
    from app.services.auth import hash_password
    Base.metadata.create_all(engine)
    seed.ADMIN_EMAIL = ADMIN["email"]
    seed.settings.admin_password = ADMIN["password"]
    seed.run_seed()
    with SessionLocal() as db:
        mix = db.query(Store).filter_by(slug="burger-mix").one()
        db.add(User(email=OWNER["email"], password_hash=hash_password(OWNER["password"]), role=Role.STORE_ADMIN, store_id=mix.id, active=True))
        db.commit()
    yield
    engine.dispose()


def client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def login(who):
    c = client()
    assert c.post("/admin/login", data=who, follow_redirects=False).status_code == 303
    return c


def test_link_para_compartir_con_vista_previa(env):
    c = client()
    r = c.get("/tienda/burger-mix/compartir.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content[:8] == b"\x89PNG\r\n\x1a\n"
    from PIL import Image
    import io
    assert Image.open(io.BytesIO(r.content)).size == (1200, 630)
    assert c.get("/tienda/no-existe/compartir.png").status_code == 404
    page = c.get("/tienda/burger-mix").text
    assert 'property="og:image" content="http://testserver/tienda/burger-mix/compartir.png"' in page
    assert 'name="twitter:card" content="summary_large_image"' in page and 'property="og:url" content="http://testserver/tienda/burger-mix"' in page
    home = login(OWNER).get("/admin").text
    assert "Compartí tu local" in home and "https://wa.me/?text=" in home and "/tienda/burger-mix/compartir.png" in home
