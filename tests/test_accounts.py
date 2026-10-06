"""Cuentas de clientes (ingreso con Google), pedidos con cuenta obligatoria y paginas legales."""
import os
import re
import sys
import time
from urllib.parse import parse_qs, urlsplit

import pytest

ADMIN = {"email": "admin@test.local", "password": "TestOnly-123!"}
GOOGLE = {"sub": "1001", "email": "ana@gmail.com", "email_verified": True, "name": "Ana Paz", "given_name": "Ana", "family_name": "Paz",
          "picture": "https://lh3.googleusercontent.com/a/x"}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("accounts") / "accounts.db"
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


@pytest.fixture
def google(env, monkeypatch):
    """Google configurado y un intercambio de codigo falso (sin salir a internet)."""
    from app.config import settings
    from app.services import google_auth
    monkeypatch.setattr(settings, "google_client_id", "cliente.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "google_client_secret", "secreto-de-prueba")
    claims = dict(GOOGLE)
    seen = {}

    def fake_exchange(code, *, verifier, redirect_uri, nonce):
        seen.update(code=code, verifier=verifier, redirect_uri=redirect_uri, nonce=nonce)
        if code == "malo":
            raise google_auth.GoogleAuthError("Google rechazó el ingreso. Probá de nuevo.")
        return dict(claims)
    monkeypatch.setattr(google_auth, "exchange_code", fake_exchange)
    return claims, seen


def client():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services import ratelimit
    ratelimit.order_limiter.clear()
    return TestClient(app)


def google_login(c, next_url="/", code="ok"):
    r = c.get(f"/ingresar/google?next={next_url}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("https://accounts.google.com/")
    q = parse_qs(urlsplit(r.headers["location"]).query)
    assert q["code_challenge_method"] == ["S256"] and q["scope"] == ["openid email profile"] and q["client_id"] == ["cliente.apps.googleusercontent.com"]
    return c.get(f"/cuenta/google/callback?code={code}&state={q['state'][0]}", follow_redirects=False)


def session_data(c) -> dict:
    import base64, json
    raw = c.cookies.get("session", "").split(".")[0]
    return json.loads(base64.b64decode(raw + "=" * (-len(raw) % 4))) if raw else {}


def product_id(name="Coca Cola"):
    from app.db import SessionLocal
    from app.models import Product
    with SessionLocal() as db:
        return db.query(Product).filter_by(name=name).one().id


def account(email="ana@gmail.com"):
    from app.db import SessionLocal
    from app.models import ClientAccount
    with SessionLocal() as db:
        a = db.query(ClientAccount).filter_by(email=email).first()
        if a: db.expunge(a)
        return a


def test_sin_google_se_sigue_pidiendo_como_invitado(env):
    c = client()
    c.post("/api/cart/add", json={"product_id": product_id(), "quantity": 1})
    assert c.get("/checkout", follow_redirects=False).status_code == 200
    r = c.post("/checkout", data={"first_name": "Invitado", "last_name": "X", "phone": "1", "delivery_method": "retiro"}, follow_redirects=False)
    assert r.headers["location"].startswith("/pedido/")
    assert c.get("/api/v1/config").json()["account"] == {"required": False, "available": False, "login_path": "/ingresar/google?app=1",
                                                         "terms_url": "/terminos", "privacy_url": "/privacidad", "withdrawal_url": "/arrepentimiento"}


def test_web_ingreso_con_google_y_pedido_con_cuenta(google):
    claims, seen = google
    c = client()
    c.post("/api/cart/add", json={"product_id": product_id(), "quantity": 2})
    # con la cuenta obligatoria, el checkout manda a ingresar
    r = c.get("/checkout", follow_redirects=False)
    assert r.headers["location"] == "/ingresar?next=/checkout"
    assert c.post("/checkout", data={"first_name": "A", "last_name": "B", "phone": "1", "delivery_method": "retiro"}, follow_redirects=False).headers["location"] == "/ingresar?next=/checkout"
    page = c.get("/ingresar?next=/checkout").text
    assert "Continuar con Google" in page and "/terminos" in page and "/privacidad" in page
    # el state tiene que coincidir
    assert c.get("/cuenta/google/callback?code=ok&state=otro", follow_redirects=False).headers["location"] == "/ingresar"
    r = google_login(c, "/checkout")
    assert r.headers["location"] == "/checkout" and "client" in session_data(c)
    assert seen["redirect_uri"].endswith("/cuenta/google/callback") and len(seen["verifier"]) >= 43
    a = account()
    assert a and a.google_sub == "1001" and a.first_name == "Ana" and a.terms_version
    page = c.get("/checkout").text
    assert "Pedís como" in page and 'value="Ana"' in page
    r = c.post("/checkout", data={"first_name": "Ana", "last_name": "Paz", "phone": "2914001122", "address": "", "delivery_method": "retiro"}, follow_redirects=False)
    assert r.headers["location"].startswith("/pedido/")
    oid = int(r.headers["location"].split("/")[2].split("?")[0])
    from app.db import SessionLocal
    from app.models import Order
    with SessionLocal() as db:
        o = db.get(Order, oid)
        assert o.account_id == a.id and o.customer.email == "ana@gmail.com"
    assert account().phone == "2914001122"  # queda para la proxima
    page = c.get("/cuenta").text
    assert f"#{oid}" in page and "Eliminar mi cuenta" in page
    # mis pedidos desde otro dispositivo: con la misma cuenta los ve
    other = client()
    google_login(other)
    assert f"#{oid}" in other.get("/mis-pedidos").text
    # guardar datos
    c.post("/cuenta", data={"first_name": "Ana", "last_name": "Paz", "phone": "2915550000", "address": "Alsina 1", "reference": ""})
    assert account().phone == "2915550000" and account().address == "Alsina 1"
    # error de Google: vuelve a ingresar con el mensaje
    third = client()
    r = google_login(third, code="malo")
    assert r.headers["location"] == "/ingresar" and "Google rechazó" in third.get("/ingresar").text


def test_cuenta_bloqueada_no_puede_pedir(google):
    claims, _ = google
    claims.update(sub="2002", email="bloqueo@gmail.com", name="Bloqueo")
    c = client()
    google_login(c)
    a = account("bloqueo@gmail.com")
    admin = client()
    admin.post("/admin/login", data=ADMIN)
    page = admin.get("/admin/customers").text
    assert "bloqueo@gmail.com" in page and "Cuentas de clientes" in page
    admin.post(f"/admin/customers/accounts/{a.id}/block", data={"reason": "pedidos falsos"})
    assert not account("bloqueo@gmail.com").active
    # la sesion ya no vale y no puede volver a entrar
    c.post("/api/cart/add", json={"product_id": product_id(), "quantity": 1})
    assert c.get("/checkout", follow_redirects=False).headers["location"] == "/ingresar?next=/checkout"
    r = google_login(c)
    assert r.headers["location"] == "/ingresar" and "bloqueada" in c.get("/ingresar").text
    admin.post(f"/admin/customers/accounts/{a.id}/block")  # desbloquear
    assert account("bloqueo@gmail.com").active


def test_eliminar_cuenta_web(google):
    claims, _ = google
    claims.update(sub="3003", email="borrar@gmail.com", name="Borrar")
    c = client()
    google_login(c)
    c.post("/api/cart/add", json={"product_id": product_id(), "quantity": 1})
    r = c.post("/checkout", data={"first_name": "B", "last_name": "C", "phone": "1", "delivery_method": "retiro"}, follow_redirects=False)
    oid = int(r.headers["location"].split("/")[2].split("?")[0])
    c.get("/cuenta")
    c.post("/cuenta/eliminar", data={})  # sin confirmar no borra
    assert account("borrar@gmail.com")
    r = c.post("/cuenta/eliminar", data={"confirm": "si"})
    assert "Cuenta eliminada" in r.text and account("borrar@gmail.com") is None
    from app.db import SessionLocal
    from app.models import Order
    with SessionLocal() as db:
        o = db.get(Order, oid)
        assert o is not None and o.account_id is None and o.customer.email is None  # el pedido queda, sin la cuenta
    assert c.get("/cuenta", follow_redirects=False).headers["location"].startswith("/ingresar")


def test_app_ingreso_con_pkce_y_pedido(google):
    from app.services import google_auth
    claims, _ = google
    claims.update(sub="4004", email="app@gmail.com", name="App User")
    verifier, challenge = google_auth.new_pkce()
    c = client()
    # solo vuelve a la app (esquema trappi://), nunca a otro sitio
    assert c.get(f"/ingresar/google?app=1&challenge={challenge}&redirect=https://malo.example/x", follow_redirects=False).status_code == 400
    r = c.get(f"/ingresar/google?app=1&challenge={challenge}&redirect=trappi://auth", follow_redirects=False)
    state = parse_qs(urlsplit(r.headers["location"]).query)["state"][0]
    r = c.get(f"/cuenta/google/callback?code=ok&state={state}", follow_redirects=False)
    assert r.headers["location"].startswith("trappi://auth?code=")
    code = parse_qs(urlsplit(r.headers["location"]).query)["code"][0]
    assert "client" not in session_data(c)  # el navegador no queda logueado: solo la app
    api = client()
    assert api.post("/api/v1/auth/exchange", json={"code": code, "verifier": google_auth.new_pkce()[0]}).status_code == 400  # otro verifier
    r = api.post("/api/v1/auth/exchange", json={"code": code, "verifier": verifier})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    auth = {"Authorization": f"Bearer {token}"}
    assert api.get("/api/v1/me", headers=auth).json()["account"]["email"] == "app@gmail.com"
    assert api.get("/api/v1/me", headers={"Authorization": "Bearer falso"}).status_code == 401
    assert api.get("/api/v1/config").json()["account"]["required"] is True
    body = {"items": [{"product_id": product_id(), "quantity": 1}], "delivery_method": "retiro", "first_name": "App", "phone": "2914000000"}
    r = api.post("/api/v1/orders", json=body)  # una app vieja (sin token)
    assert r.status_code == 401 and r.json()["login_required"] and "actualizá la app" in r.json()["error"]
    r = api.post("/api/v1/orders", json=body, headers=auth)
    assert r.status_code == 200, r.text
    oid = r.json()["id"]
    mine = api.get("/api/v1/me/orders", headers=auth).json()["orders"]
    assert mine[0]["id"] == oid and mine[0]["token"]
    r = api.put("/api/v1/me", json={"phone": "2916667777", "address": "Mitre 5"}, headers=auth)
    assert r.json()["account"]["phone"] == "2916667777"
    # salir de todos lados invalida el token
    api.post("/api/v1/me/logout", json={"everywhere": True}, headers=auth)
    assert api.get("/api/v1/me", headers=auth).status_code == 401
    # entrar de nuevo y eliminar la cuenta desde la app
    r = c.get(f"/ingresar/google?app=1&challenge={challenge}&redirect=trappi://auth", follow_redirects=False)
    state = parse_qs(urlsplit(r.headers["location"]).query)["state"][0]
    code = parse_qs(urlsplit(c.get(f"/cuenta/google/callback?code=ok&state={state}", follow_redirects=False).headers["location"]).query)["code"][0]
    token = api.post("/api/v1/auth/exchange", json={"code": code, "verifier": verifier}).json()["token"]
    assert api.delete("/api/v1/me", headers={"Authorization": f"Bearer {token}"}).json() == {"ok": True}
    assert account("app@gmail.com") is None


def test_app_cancelado_en_google_vuelve_a_la_app(google):
    from app.services import google_auth
    _, challenge = google_auth.new_pkce()
    c = client()
    r = c.get(f"/ingresar/google?app=1&challenge={challenge}&redirect=trappi://auth", follow_redirects=False)
    state = parse_qs(urlsplit(r.headers["location"]).query)["state"][0]
    r = c.get(f"/cuenta/google/callback?error=access_denied&state={state}", follow_redirects=False)
    assert r.headers["location"] == "trappi://auth?error=cancelado"


def test_id_token_se_valida(env, monkeypatch):
    """Firma, audiencia, emisor, vencimiento y nonce del id_token de Google."""
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    from app.config import settings
    from app.services import google_auth
    monkeypatch.setattr(settings, "google_client_id", "cliente.apps.googleusercontent.com")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class Keys:
        def get_signing_key_from_jwt(self, token):
            return type("K", (), {"key": key.public_key()})()
    monkeypatch.setattr(google_auth, "_keys", lambda: Keys())
    now = int(time.time())
    base = {"iss": "https://accounts.google.com", "aud": "cliente.apps.googleusercontent.com", "sub": "1", "email": "a@b.c", "email_verified": True,
            "iat": now, "exp": now + 600, "nonce": "n1"}
    sign = lambda **kw: jwt.encode({**base, **kw}, key, algorithm="RS256")
    assert google_auth.verify_id_token(sign(), "n1")["sub"] == "1"
    for bad in (dict(aud="otro"), dict(iss="https://malo.example"), dict(exp=now - 3600), dict(nonce="otro")):
        with pytest.raises(google_auth.GoogleAuthError):
            google_auth.verify_id_token(sign(**bad), "n1")
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(google_auth.GoogleAuthError):
        google_auth.verify_id_token(jwt.encode(base, other, algorithm="RS256"), "n1")


def test_paginas_legales_y_arrepentimiento(env):
    from app.db import SessionLocal
    from app.models import Setting, WithdrawalRequest
    from app.services import platform
    with SessionLocal() as db:
        for k, v in {"legal_name": "Trappi SAS", "legal_cuit": "30-12345678-9", "legal_address": "Alsina 100, Bahía Blanca", "legal_email": "legal@trappi.test"}.items():
            db.add(Setting(key=k, value=v))
        db.commit()
    platform.invalidate()
    c = client()
    home = c.get("/").text
    for link in ("/terminos", "/privacidad", "/arrepentimiento", "defensadelconsumidor"):
        assert link in home
    terms = c.get("/terminos").text
    assert "Trappi SAS" in terms and "30-12345678-9" in terms and "Ley 24.240" in terms
    privacy = c.get("/privacidad").text
    assert "Ley 25.326" in privacy and "AGENCIA DE ACCESO A LA INFORMACIÓN PÚBLICA" in privacy and "legal@trappi.test" in privacy
    assert "/privacidad" in c.get("/sitemap.xml").text
    page = c.get("/arrepentimiento").text
    token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    assert "Completá tu nombre" in c.post("/arrepentimiento", data={"csrf_token": token, "name": "Ana"}).text
    r = c.post("/arrepentimiento", data={"csrf_token": token, "name": "Ana Paz", "email": "ana@x.com", "order_ref": "12", "detail": "No lo quiero"})
    code = re.search(r"(ARR-[0-9A-F]{6})", r.text).group(1)
    with SessionLocal() as db:
        assert db.query(WithdrawalRequest).filter_by(code=code).one().order_ref == "12"
    # sin token (otro sitio): rechazado
    assert c.post("/arrepentimiento", data={"name": "X", "email": "x@x.com"}, headers={"x-no-csrf": "1"}).status_code == 403
    admin = client()
    admin.post("/admin/login", data=ADMIN)
    page = admin.get("/admin/customers").text
    assert code in page and "Pedidos de arrepentimiento" in page
    with SessionLocal() as db:
        wid = db.query(WithdrawalRequest).filter_by(code=code).one().id
    admin.post(f"/admin/customers/arrepentimiento/{wid}")
    with SessionLocal() as db:
        assert db.get(WithdrawalRequest, wid).status == "resuelto"
