"""Cuentas de clientes (ingreso con codigo por email), pedidos con cuenta obligatoria y paginas legales."""
import os
import re
import sys
import time
from urllib.parse import parse_qs, urlsplit

import pytest

ADMIN = {"email": "admin@test.local", "password": "TestOnly-123!"}


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
def mail(env):
    """Envio de emails configurado: los emails quedan en una lista (sin salir a internet)."""
    from app.services import accounts, email
    outbox = []
    email.set_outbox(outbox)
    for limiter in (accounts.code_requests_by_email, accounts.code_requests_by_ip, accounts.code_failures):
        limiter_clear(limiter)
    yield outbox
    email.set_outbox(None)


def limiter_clear(limiter):
    from sqlalchemy import delete
    from app.db import SessionLocal
    from app.models import AuthAttempt
    with SessionLocal() as db:
        db.execute(delete(AuthAttempt).where(AuthAttempt.key.like(limiter.name + ":%")))
        db.commit()


def code_of(outbox) -> str:
    return re.search(r"\b(\d{6})\b", outbox[-1]["text"]).group(1)


def email_login(c, email, next_url="/", **app):
    page = c.get("/ingresar?" + "&".join(f"{k}={v}" for k, v in {"next": next_url, **app}.items()))
    assert page.status_code == 200 and 'action="/ingresar/email"' in page.text
    data = {"email": email, "next": next_url, **app}
    return c.post("/ingresar/email", data=data, follow_redirects=False)


def client():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services import ratelimit
    ratelimit.order_limiter.clear()
    return TestClient(app)


def login(c, outbox, email="ana@gmail.com", next_url="/", **app):
    """Ingreso completo con codigo: devuelve la respuesta de /ingresar/codigo (sin seguir la redireccion)."""
    assert email_login(c, email, next_url, **app).headers["location"] == "/ingresar/codigo"
    return c.post("/ingresar/codigo", data={"code": code_of(outbox)}, follow_redirects=False)


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


def test_sin_email_se_sigue_pidiendo_como_invitado(env):
    c = client()
    c.post("/api/cart/add", json={"product_id": product_id(), "quantity": 1})
    assert c.get("/checkout", follow_redirects=False).status_code == 200
    r = c.post("/checkout", data={"first_name": "Invitado", "last_name": "X", "phone": "1", "delivery_method": "retiro"}, follow_redirects=False)
    assert r.headers["location"].startswith("/pedido/")
    assert c.get("/api/v1/config").json()["account"] == {"required": False, "available": False, "login_path": "/ingresar?app=1", "methods": [],
                                                         "terms_url": "/terminos", "privacy_url": "/privacidad", "withdrawal_url": "/arrepentimiento"}


def test_web_pedido_con_cuenta(mail):
    c = client()
    c.post("/api/cart/add", json={"product_id": product_id(), "quantity": 2})
    # con la cuenta obligatoria, el checkout manda a ingresar
    r = c.get("/checkout", follow_redirects=False)
    assert r.headers["location"] == "/ingresar?next=/checkout"
    assert c.post("/checkout", data={"first_name": "A", "last_name": "B", "phone": "1", "delivery_method": "retiro"}, follow_redirects=False).headers["location"] == "/ingresar?next=/checkout"
    page = c.get("/ingresar?next=/checkout").text
    assert "Mandame el código" in page and "/terminos" in page and "/privacidad" in page and "Google" not in page
    r = login(c, mail, next_url="/checkout")
    assert r.headers["location"] == "/checkout" and "client" in session_data(c)
    a = account()
    assert a and a.email == "ana@gmail.com" and a.terms_version
    c.post("/cuenta", data={"first_name": "Ana", "last_name": "Paz", "phone": "", "address": "", "reference": ""})
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
    assert f"#{oid}" in page and "Eliminar mi cuenta" in page and "código por email" in page
    # mis pedidos desde otro dispositivo: con la misma cuenta los ve
    other = client()
    login(other, mail)
    assert f"#{oid}" in other.get("/mis-pedidos").text
    # guardar datos
    c.post("/cuenta", data={"first_name": "Ana", "last_name": "Paz", "phone": "2915550000", "address": "Alsina 1", "reference": ""})
    assert account().phone == "2915550000" and account().address == "Alsina 1"


def test_cuenta_bloqueada_no_puede_pedir(mail):
    c = client()
    login(c, mail, "bloqueo@gmail.com")
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
    r = login(c, mail, "bloqueo@gmail.com")
    assert r.headers["location"] == "/ingresar" and "bloqueada" in c.get("/ingresar").text
    admin.post(f"/admin/customers/accounts/{a.id}/block")  # desbloquear
    assert account("bloqueo@gmail.com").active


def test_eliminar_cuenta_web(mail):
    c = client()
    login(c, mail, "borrar@gmail.com")
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


def test_app_ingreso_con_pkce_y_pedido(mail):
    from app.services import accounts
    verifier, challenge = accounts.new_pkce()
    c = client()
    # solo vuelve a la app (esquema trappi://), nunca a otro sitio
    assert c.get(f"/ingresar?app=1&challenge={challenge}&redirect=https://malo.example/x").status_code == 400
    app = {"app": "1", "challenge": challenge, "redirect": "trappi://auth"}
    r = login(c, mail, "app@gmail.com", **app)
    assert r.headers["location"].startswith("trappi://auth?code=")
    code = parse_qs(urlsplit(r.headers["location"]).query)["code"][0]
    assert "client" not in session_data(c)  # el navegador no queda logueado: solo la app
    api = client()
    assert api.post("/api/v1/auth/exchange", json={"code": code, "verifier": accounts.new_pkce()[0]}).status_code == 400  # otro verifier
    r = api.post("/api/v1/auth/exchange", json={"code": code, "verifier": verifier})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    # el codigo es de un solo uso: no sirve para sacar otro token
    again = api.post("/api/v1/auth/exchange", json={"code": code, "verifier": verifier})
    assert again.status_code == 400 and "ya se usó" in again.json()["error"]
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
    r = login(c, mail, "app@gmail.com", **app)
    code = parse_qs(urlsplit(r.headers["location"]).query)["code"][0]
    token = api.post("/api/v1/auth/exchange", json={"code": code, "verifier": verifier}).json()["token"]
    assert api.delete("/api/v1/me", headers={"Authorization": f"Bearer {token}"}).json() == {"ok": True}
    assert account("app@gmail.com") is None


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


def test_web_ingreso_con_codigo_por_email(mail):
    c = client()
    assert c.get("/api/v1/config").json()["account"]["methods"] == ["email"]
    page = c.get("/ingresar")
    assert "Mandame el código" in page.text and "Continuar con Google" not in page.text
    bad = c.post("/ingresar/email", data={"email": "no-es-un-email"}, follow_redirects=False)
    assert bad.status_code == 400 and "Revisá el email" in bad.text and not mail
    r = email_login(c, "  Lu@Gmail.com ", next_url="/checkout")
    assert r.status_code == 303 and r.headers["location"] == "/ingresar/codigo"
    assert mail[-1]["to"] == "lu@gmail.com" and "código para entrar" in mail[-1]["subject"]
    code = code_of(mail)
    assert code not in c.cookies.get("session", "") and code not in str(session_data(c))  # en la cookie solo va el HMAC
    assert "lu@gmail.com" in c.get("/ingresar/codigo").text
    wrong = "000000" if code != "000000" else "111111"
    r = c.post("/ingresar/codigo", data={"code": wrong}, follow_redirects=False)
    assert r.headers["location"] == "/ingresar/codigo" and "no es correcto" in c.get("/ingresar/codigo").text
    r = c.post("/ingresar/codigo", data={"code": code[:3] + " " + code[3:]}, follow_redirects=False)
    assert r.headers["location"] == "/checkout" and "client" in session_data(c)
    acct = account("lu@gmail.com")
    assert acct.terms_version and acct.last_login_at
    # el codigo es de un solo uso
    other = client()
    other.get("/ingresar")
    assert other.post("/ingresar/codigo", data={"code": code}, follow_redirects=False).headers["location"] == "/ingresar"
    # con la cuenta abierta se puede pedir (la cuenta es obligatoria apenas hay una forma de entrar)
    c.post("/api/cart/add", json={"product_id": product_id(), "quantity": 1})
    r = c.post("/checkout", data={"first_name": "Lu", "last_name": "X", "phone": "1", "delivery_method": "retiro"}, follow_redirects=False)
    assert r.headers["location"].startswith("/pedido/")
    guest = client()
    guest.post("/api/cart/add", json={"product_id": product_id(), "quantity": 1})
    assert guest.get("/checkout", follow_redirects=False).headers["location"] == "/ingresar?next=/checkout"
    # entrar de nuevo con el mismo email abre la misma cuenta
    again = client()
    email_login(again, "lu@gmail.com")
    again.post("/ingresar/codigo", data={"code": code_of(mail)})
    assert account("lu@gmail.com").id == acct.id


def test_codigo_por_email_con_limites(mail):
    c = client()
    email_login(c, "limite@gmail.com")
    code = code_of(mail)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        c.post("/ingresar/codigo", data={"code": wrong})
    r = c.post("/ingresar/codigo", data={"code": code}, follow_redirects=False)  # ni el correcto: hay que esperar y pedir otro
    assert r.headers["location"] == "/ingresar" and account("limite@gmail.com") is None
    # pedir codigos: 3 cada 10 minutos por email
    for _ in range(2):
        assert email_login(c, "muchos@gmail.com").status_code == 303
    c.post("/ingresar/codigo/reenviar", follow_redirects=False)
    assert "Te mandamos un código nuevo" in c.get("/ingresar/codigo").text
    r = email_login(c, "muchos@gmail.com")
    assert r.status_code == 400 and "varios códigos" in r.text and len([m for m in mail if m["to"] == "muchos@gmail.com"]) == 3
    # el codigo vence
    from app.services import accounts
    import time as _time
    data = session_data(c)
    assert data[accounts.EMAIL_FLOW_KEY]["exp"] <= _time.time() + accounts.EMAIL_CODE_MINUTES * 60 + 1


def test_app_ingreso_con_codigo_por_email(mail):
    from app.services import accounts
    verifier, challenge = accounts.new_pkce()
    c = client()
    # la app 1.5 abre /ingresar/google: ya no hay Google: se la manda al ingreso con email, con sus datos
    r = c.get(f"/ingresar/google?app=1&challenge={challenge}&redirect=trappi://auth", follow_redirects=False)
    loc = urlsplit(r.headers["location"])
    assert loc.path == "/ingresar" and parse_qs(loc.query)["challenge"] == [challenge]
    assert c.get(f"/ingresar?app=1&challenge={challenge}&redirect=https://malo.example").status_code == 400
    c.get("/ingresar")
    assert c.post("/ingresar/email", data={"email": "x@gmail.com", "app": "1", "challenge": challenge, "redirect": "https://malo.example"}).status_code == 400
    r = email_login(c, "appmail@gmail.com", app="1", challenge=challenge, redirect="trappi://auth")
    assert r.headers["location"] == "/ingresar/codigo"
    r = c.post("/ingresar/codigo", data={"code": code_of(mail)}, follow_redirects=False)
    assert r.headers["location"].startswith("trappi://auth?code=")
    assert "client" not in session_data(c)  # el navegador no queda logueado: solo la app
    code = parse_qs(urlsplit(r.headers["location"]).query)["code"][0]
    res = client().post("/api/v1/auth/exchange", json={"code": code, "verifier": verifier})
    assert res.status_code == 200 and res.json()["account"]["email"] == "appmail@gmail.com"


def test_google_ya_no_existe(mail):
    c = client()
    assert c.get("/cuenta/google/callback?code=x&state=y").status_code == 404
    from app.config import settings
    assert not hasattr(settings, "google_client_id")


def test_proveedores_de_email(env, monkeypatch):
    import httpx
    from app.config import settings
    from app.services import email
    sent = []

    def fake_post(url, **kw):
        sent.append((url, kw))
        return httpx.Response(201 if "brevo" in url else 200, json={"id": "x"}, request=httpx.Request("POST", url))
    monkeypatch.setattr(email.httpx, "post", fake_post)
    monkeypatch.setattr(settings, "email_from", "hola@trappi.test")
    monkeypatch.setattr(settings, "email_api_key", "clave-de-prueba")
    for provider in ("brevo", "resend"):
        monkeypatch.setattr(settings, "email_provider", provider)
        assert settings.email_configured and email.configured()
        email.send("ana@gmail.com", "123456 es tu código", "Tu código es 123456")
    (brevo_url, brevo), (resend_url, resend) = sent
    assert brevo_url == "https://api.brevo.com/v3/smtp/email" and brevo["headers"]["api-key"] == "clave-de-prueba"
    assert brevo["json"]["to"] == [{"email": "ana@gmail.com"}] and brevo["json"]["sender"]["email"] == "hola@trappi.test"
    assert resend_url == "https://api.resend.com/emails" and resend["headers"]["Authorization"] == "Bearer clave-de-prueba"
    assert resend["json"]["from"] == "Trappi <hola@trappi.test>" and "123456" in resend["json"]["html"]
    monkeypatch.setattr(email.httpx, "post", lambda url, **kw: httpx.Response(401, text="bad key", request=httpx.Request("POST", url)))
    with pytest.raises(email.EmailError):
        email.send("ana@gmail.com", "x", "y")
    monkeypatch.setattr(settings, "email_provider", "console")
    monkeypatch.setattr(settings, "environment", "production")
    assert not settings.email_configured  # el modo "console" nunca vale en produccion


def test_panel_prueba_el_envio_de_email(env, monkeypatch):
    import httpx
    from app.config import settings
    from app.services import email
    admin = client()
    admin.post("/admin/login", data=ADMIN)
    page = admin.post("/admin/settings/email-test").text
    assert "No anda" in page and "Faltan en Render: EMAIL_PROVIDER" in page
    monkeypatch.setattr(settings, "email_provider", "brevo")
    page = admin.post("/admin/settings/email-test").text
    assert "EMAIL_API_KEY" in page and "EMAIL_FROM" in page
    monkeypatch.setattr(settings, "email_api_key", "xkeysib-prueba")
    monkeypatch.setattr(settings, "email_from", "hola@trappi.test")
    sent = []
    monkeypatch.setattr(email.httpx, "post", lambda url, **kw: sent.append(kw) or httpx.Response(
        401, json={"code": "unauthorized", "message": "We have detected you are using an unrecognised IP address 1.2.3.4"}, request=httpx.Request("POST", url)))
    page = admin.post("/admin/settings/email-test").text
    assert "No anda" in page and "unrecognised IP" in page and "Authorized IPs" in page and "xkeysib-prueba" not in page
    monkeypatch.setattr(email.httpx, "post", lambda url, **kw: sent.append(kw) or httpx.Response(201, json={"messageId": "x"}, request=httpx.Request("POST", url)))
    page = admin.post("/admin/settings/email-test").text
    assert "Funciona" in page and ADMIN["email"] in page and sent[-1]["json"]["to"] == [{"email": ADMIN["email"]}]
    monkeypatch.setattr(settings, "email_api_key", "xsmtpsib-prueba")
    monkeypatch.setattr(email.httpx, "post", lambda url, **kw: httpx.Response(401, json={"message": "Key not found"}, request=httpx.Request("POST", url)))
    assert "clave SMTP" in admin.post("/admin/settings/email-test").text
    assert client().post("/admin/settings/email-test", follow_redirects=False).status_code in (303, 403)
