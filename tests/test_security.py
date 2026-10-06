"""Seguridad del panel: CSRF, encabezados, verificacion en dos pasos, sesiones y limites persistentes."""
import os
import re
import sys
import time

import pytest

ADMIN = {"email": "admin@test.local", "password": "TestOnly-123!"}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("security") / "security.db"
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


def login(email=ADMIN["email"], password=ADMIN["password"]):
    c = client()
    r = c.post("/admin/login", data={"email": email, "password": password}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return c, r


def make_user(email, password="Clave-1234", role="STORE_ADMIN"):
    from app.db import SessionLocal
    from app.models import Role, Store, User
    from app.services.auth import hash_password
    with SessionLocal() as db:
        if not db.query(User).filter_by(email=email).first():
            db.add(User(email=email, password_hash=hash_password(password), role=Role(role),
                        store_id=db.query(Store).first().id if role == "STORE_ADMIN" else None))
            db.commit()


def user(email):
    from app.db import SessionLocal
    from app.models import User
    with SessionLocal() as db:
        u = db.query(User).filter_by(email=email).one()
        db.expunge(u)
        return u


def test_csrf_frena_envios_sin_token_o_de_otro_sitio(env):
    from app.db import SessionLocal
    from app.models import Store
    c, _ = login()
    with SessionLocal() as db:
        sid = db.query(Store).first().id
        before = db.get(Store, sid).status
    url = f"/admin/stores/{sid}/open-close"
    # sin token: rechazado y no cambia nada
    r = c.post(url, data={}, headers={"x-no-csrf": "1"}, follow_redirects=False)
    assert r.status_code == 403 and "No se pudo guardar" in r.text
    # token equivocado
    assert c.post(url, data={"csrf_token": "falso"}, headers={"x-no-csrf": "1"}, follow_redirects=False).status_code == 403
    # desde otro sitio, aunque traiga el token
    assert c.post(url, headers={"Origin": "https://malo.example"}, follow_redirects=False).status_code == 403
    with SessionLocal() as db:
        assert db.get(Store, sid).status == before
    # el formulario del panel trae el token y funciona
    page = c.get("/admin/stores").text
    token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    assert 'meta name="csrf-token"' in page
    r = c.post(url, data={"csrf_token": token}, headers={"x-no-csrf": "1", "Origin": "http://testserver"}, follow_redirects=False)
    assert r.status_code == 303
    with SessionLocal() as db:
        assert db.get(Store, sid).status != before
    c.post(url)  # lo deja como estaba
    # por fetch con el encabezado
    assert c.post(url, headers={"X-CSRF-Token": token}, follow_redirects=False).status_code == 303
    # el login no necesita token, pero si viene de otro sitio se rechaza
    assert client().post("/admin/login", data=ADMIN, headers={"Origin": "https://malo.example"}, follow_redirects=False).status_code == 403


def test_encabezados_de_seguridad(env):
    c = client()
    for url in ("/", "/admin/login", "/api/v1/home"):
        h = c.get(url).headers
        assert h["x-content-type-options"] == "nosniff"
        assert h["x-frame-options"] == "SAMEORIGIN"
        assert "frame-ancestors 'self'" in h["content-security-policy"] and "object-src 'none'" in h["content-security-policy"]
        assert h["referrer-policy"] == "strict-origin-when-cross-origin"
        assert "camera=()" in h["permissions-policy"]
        assert "strict-transport-security" not in h  # solo en produccion (HTTPS)
    assert c.get("/admin/login").headers["cache-control"] == "no-store"
    assert "content-security-policy" not in c.get("/docs").headers  # la documentacion usa un CDN


def test_hsts_en_produccion(env, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "environment", "production")
    h = client().get("/health").headers
    assert "max-age=31536000" in h["strict-transport-security"]
    assert "upgrade-insecure-requests" in h["content-security-policy"]


def test_totp_codigos():
    from app.services import totp
    secret = "JBSWY3DPEHPK3PXP"
    # vector de prueba: el mismo calculo que Google Authenticator
    now = 1_700_000_000
    code = totp.code_at(secret, now // 30)
    assert len(code) == 6 and code.isdigit()
    step = totp.verify(secret, code, None, now=now)
    assert step == now // 30
    assert totp.verify(secret, code, step, now=now) is None  # no se puede reusar
    assert totp.verify(secret, totp.code_at(secret, now // 30 - 1), None, now=now) is not None  # 30 s de tolerancia
    assert totp.verify(secret, totp.code_at(secret, now // 30 - 3), None, now=now) is None
    assert totp.verify(secret, "12345", None, now=now) is None
    assert "otpauth://totp/Trappi:" in totp.provisioning_uri(secret, "a@b.c") and "<svg" in totp.qr_svg(totp.provisioning_uri(secret, "a@b.c"))


def _current_code(email):
    from app.services import totp
    return totp.code_at(totp.secret_of(user(email)), int(time.time() // 30))


def test_dos_pasos_para_un_local(env):
    from app.services import totp
    email = "dospasos@test.local"
    make_user(email)
    c, _ = login(email, "Clave-1234")
    assert "Activar la verificación en dos pasos" in c.get("/admin/account").text
    page = c.get("/admin/account/2fa").text
    assert "<svg" in page and "Google Authenticator" in page
    # codigo equivocado: no se activa
    c.post("/admin/account/2fa", data={"code": "000000"})
    assert not totp.enabled(user(email))
    r = c.post("/admin/account/2fa", data={"code": _current_code(email)}, follow_redirects=False)
    assert r.headers["location"] == "/admin/account"
    page = c.get("/admin/account").text
    codes = re.findall(r"<code>([0-9a-f]{6}-[0-9a-f]{6})</code>", page)
    assert len(codes) == 10 and "Se muestran una sola vez" in page
    assert "<code>" not in c.get("/admin/account").text  # no se vuelven a mostrar
    assert totp.enabled(user(email)) and user(email).recovery_codes and codes[0] not in user(email).recovery_codes  # guardados como hash

    # entrar: despues de la contrasena pide el codigo, y sin el no hay sesion
    c2, r = login(email, "Clave-1234")
    assert r.headers["location"] == "/admin/login/2fa"
    assert c2.get("/admin/orders", follow_redirects=False).headers["location"].startswith("/admin/login")
    assert c2.post("/admin/login/2fa", data={"code": "111111"}).status_code == 401
    # el mismo codigo que ya se uso al activar no sirve (puede que el reloj ya haya avanzado: entonces vale el nuevo)
    r = c2.post("/admin/login/2fa", data={"code": _current_code(email)}, follow_redirects=False)
    if r.status_code == 401:
        time.sleep(31 - time.time() % 30)
        r = c2.post("/admin/login/2fa", data={"code": _current_code(email)}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin"
    assert c2.get("/admin/orders").status_code == 200

    # con un codigo de recuperacion (una sola vez)
    c3, _ = login(email, "Clave-1234")
    r = c3.post("/admin/login/2fa", data={"code": codes[0]}, follow_redirects=False)
    assert r.headers["location"] == "/admin/account" and totp.recovery_left(user(email)) == 9
    c4, _ = login(email, "Clave-1234")
    assert c4.post("/admin/login/2fa", data={"code": codes[0]}).status_code == 401

    # el superadmin se la puede quitar (perdio el celular y los codigos)
    admin, _ = login()
    assert "Quitar dos pasos" in admin.get("/admin/users").text
    admin.post(f"/admin/users/{user(email).id}/reset-2fa")
    assert not totp.enabled(user(email)) and user(email).totp_secret_enc is None
    assert c2.get("/admin/orders", follow_redirects=False).status_code == 303  # y se le cerro la sesion


def test_codigo_de_dos_pasos_con_limite(env):
    from app.routers import admin
    from app.services import crypto, totp
    from app.db import SessionLocal
    from app.models import User
    from datetime import datetime
    email = "limite2fa@test.local"
    make_user(email)
    with SessionLocal() as db:
        u = db.query(User).filter_by(email=email).one()
        u.totp_secret_enc, u.totp_enabled_at = crypto.encrypt(totp.new_secret()), datetime.utcnow()
        db.commit()
    c, _ = login(email, "Clave-1234")
    for _ in range(admin.totp_limiter.limit):
        assert c.post("/admin/login/2fa", data={"code": "000000"}).status_code == 401
    assert c.post("/admin/login/2fa", data={"code": _current_code(email)}).status_code == 429


def test_superadmin_tiene_que_configurar_dos_pasos(env, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "admin_2fa_required", True)
    email = "super2@test.local"
    make_user(email, role="SUPERADMIN")
    c, r = login(email, "Clave-1234")
    assert r.headers["location"] == "/admin/account/2fa"
    # no puede usar nada del panel hasta activarla
    for url in ("/admin", "/admin/comercios", "/admin/users"):
        assert c.get(url, follow_redirects=False).headers["location"] == "/admin/account/2fa"
    assert "hace falta la verificación en dos pasos" in c.get("/admin/account/2fa").text
    assert c.get("/admin/orders/pending").status_code == 401  # tampoco la consulta de comandas
    c.post("/admin/account/2fa", data={"code": _current_code(email)})
    assert c.get("/admin/comercios", follow_redirects=False).status_code == 200
    # y no la puede desactivar
    page = c.get("/admin/account").text
    assert "Para el superadmin es obligatoria" in page and "/admin/account/2fa/desactivar" not in page


def test_cambiar_contrasena_cierra_las_otras_sesiones(env):
    email = "sesiones@test.local"
    make_user(email, "Vieja-1234")
    phone, _ = login(email, "Vieja-1234")
    pc, _ = login(email, "Vieja-1234")
    assert phone.get("/admin/orders").status_code == 200
    r = pc.post("/admin/account/password", data={"current": "Vieja-1234", "new": "Nueva-1234", "confirm": "Nueva-1234"}, follow_redirects=False)
    assert r.headers["location"] == "/admin/account"
    assert pc.get("/admin/orders").status_code == 200  # esta sesion sigue
    assert phone.get("/admin/orders", follow_redirects=False).headers["location"].startswith("/admin/login")  # la otra no
    # cerrar las demas a mano
    other, _ = login(email, "Nueva-1234")
    pc.post("/admin/account/sessions")
    assert other.get("/admin/orders", follow_redirects=False).status_code == 303
    assert pc.get("/admin/orders").status_code == 200
    # desactivado por el superadmin: afuera
    admin, _ = login()
    admin.post(f"/admin/users/{user(email).id}/toggle")
    assert pc.get("/admin/orders", follow_redirects=False).status_code == 303


def test_limite_de_intentos_queda_en_la_base(env):
    from app.db import SessionLocal
    from app.models import AuthAttempt
    from app.services.ratelimit import PersistentRateLimiter
    lim = PersistentRateLimiter("prueba", limit=3, window_seconds=60)
    for _ in range(3):
        assert lim.check("1.2.3.4")
    assert not lim.check("1.2.3.4") and lim.retry_after("1.2.3.4") > 1
    # otra instancia (otro proceso o despues de desplegar) ve los mismos intentos
    assert PersistentRateLimiter("prueba", limit=3, window_seconds=60).blocked("1.2.3.4")
    assert not lim.blocked("5.6.7.8")
    with SessionLocal() as db:
        assert db.query(AuthAttempt).filter(AuthAttempt.key == "prueba:1.2.3.4").count() == 3
    lim.reset("1.2.3.4")
    assert not lim.blocked("1.2.3.4")


def test_consola_quita_dos_pasos(env):
    from datetime import datetime
    from app import reset_2fa
    from app.db import SessionLocal
    from app.models import User
    from app.services import crypto, totp
    email = "perdio@test.local"
    make_user(email)
    with SessionLocal() as db:
        u = db.query(User).filter_by(email=email).one()
        u.totp_secret_enc, u.totp_enabled_at = crypto.encrypt(totp.new_secret()), datetime.utcnow()
        db.commit()
    assert reset_2fa.main(["x", email.upper()]) == 0
    assert not totp.enabled(user(email))
    assert reset_2fa.main(["x", "nadie@test.local"]) == 1


def test_variable_de_dos_pasos_vacia_no_rompe_el_arranque(monkeypatch):
    from app.config import Settings
    monkeypatch.setenv("ADMIN_2FA_REQUIRED", "")
    assert Settings().admin_2fa_required is None
    monkeypatch.setenv("ADMIN_2FA_REQUIRED", "false")
    assert Settings().admin_2fa_required is False
