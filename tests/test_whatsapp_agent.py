"""Agente de WhatsApp de cada local: lo habilita el superadmin, webhook firmado, agente acotado al menu del local,
link al checkout (tambien programado), avisos al dueño, tomar y devolver la charla. Sin salir a internet."""
import hashlib
import hmac
import itertools
import json
import os
import sys
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

ADMIN = {"email": "admin@test.local", "password": "TestOnly-123!"}
OWNER = {"email": "dueno-wa@test.local", "password": "Dueno-1234"}
OTHER = {"email": "otro-wa@test.local", "password": "Otro-12345"}
SECRET = "app-secret-de-prueba"
PHONE_ID = "1111222233"


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("wa") / "wa.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["ENVIRONMENT"] = "development"
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]
    from app import seed
    from app.config import settings
    from app.db import Base, SessionLocal, engine
    from app.models import Product, Role, Store, User
    from app.services import wa_agent
    from app.services.auth import hash_password
    Base.metadata.create_all(engine)
    seed.ADMIN_EMAIL = ADMIN["email"]
    seed.settings.admin_password = ADMIN["password"]
    seed.run_seed()
    settings.meta_app_id, settings.meta_app_secret = "999", SECRET
    settings.whatsapp_verify_token, settings.whatsapp_signup_config_id = "verificar-123", "cfg-1"
    settings.whatsapp_cloud_token, settings.whatsapp_cloud_phone_id = "token-de-prueba", PHONE_ID
    wa_agent.SYNC = True
    with SessionLocal() as db:
        mix = db.query(Store).filter_by(slug="burger-mix").one()
        other = Store(name="Otro Local", slug="otro-local", status=mix.status, account_status="activo", city_id=mix.city_id, delivery_enabled=True)
        db.add(other); db.flush()
        db.add(Product(store_id=other.id, name="Pizza del otro", price=Decimal("9000")))
        db.add(User(email=OWNER["email"], password_hash=hash_password(OWNER["password"]), role=Role.STORE_ADMIN, store_id=mix.id, active=True))
        db.add(User(email=OTHER["email"], password_hash=hash_password(OTHER["password"]), role=Role.STORE_ADMIN, store_id=other.id, active=True))
        db.commit()
    yield
    wa_agent.SYNC = False
    engine.dispose()


def client():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services import ratelimit
    ratelimit.order_limiter.clear()
    return TestClient(app)


def login(who):
    c = client()
    assert c.post("/admin/login", data=who, follow_redirects=False).status_code == 303
    return c


def ids():
    from app.db import SessionLocal
    from app.models import Product, Store
    with SessionLocal() as db:
        mix = db.query(Store).filter_by(slug="burger-mix").one()
        return {"mix": mix.id, "other": db.query(Store).filter_by(slug="otro-local").one().id,
                "clasica": db.query(Product).filter_by(name="Hamburguesa Clásica").one().id,
                "pizza": db.query(Product).filter_by(name="Pizza del otro").one().id}


OUT = itertools.count(1)


class Meta:
    """Graph API falsa: guarda lo que Trappi le manda a Meta."""
    def __init__(self):
        self.sent = []

    def post(self, url, **kw):
        self.sent.append((url, kw.get("json"), kw.get("headers")))
        n = next(OUT)
        return type("R", (), {"status_code": 200, "text": "", "json": lambda s: {"messages": [{"id": f"wamid.out{n}"}]}})()

    def texts(self):
        return [(j.get("text") or {}).get("body") or j["interactive"]["body"]["text"] for _, j, _ in self.sent if j and j.get("to")]


@pytest.fixture
def meta(env, monkeypatch):
    from app.services import wa_agent
    m = Meta()
    monkeypatch.setattr(wa_agent.httpx, "post", m.post)
    return m


class Scripted:
    name = "fake"

    def __init__(self, *steps):
        self.steps, self.seen = list(steps), []

    def chat(self, messages, tools):
        self.seen.append((messages, tools))
        return self.steps.pop(0)(messages)


def call(name, **args):
    from app.ai.providers import AIReply, ToolCall
    return lambda messages: AIReply(tool_calls=[ToolCall(id=f"c_{name}", name=name, arguments=args)])


def say(text):
    from app.ai.providers import AIReply
    return lambda messages: AIReply(text=text)


@pytest.fixture
def model(env):
    from app.ai import providers

    def install(*steps):
        p = Scripted(*steps)
        providers.set_override(p)
        return p
    yield install
    providers.set_override(None)


def payload(text, wid, phone_id=PHONE_ID, who="5492914556677", name="Marta"):
    return {"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": phone_id}, "contacts": [{"wa_id": who, "profile": {"name": name}}],
                                              "messages": [{"id": wid, "from": who, "type": "text", "text": {"body": text}}]}}]}]}


def hook(c, data, secret=SECRET):
    raw = json.dumps(data).encode()
    sig = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return c.post("/api/whatsapp/webhook", content=raw, headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"})


def conv():
    from app.db import SessionLocal
    from app.models import WaConversation
    with SessionLocal() as db:
        c = db.query(WaConversation).filter_by(wa_id="5492914556677").one()
        db.expunge(c)
        return c


def test_solo_lo_ve_el_local_que_el_superadmin_habilita(env):
    i = ids()
    owner = login(OWNER)
    assert owner.get("/admin/whatsapp", follow_redirects=False).headers["location"] == "/admin"  # sin habilitar no hay nada
    assert "/admin/whatsapp" not in owner.get("/admin/products").text
    # el dueño no se lo puede prender solo
    owner.post(f"/admin/whatsapp/habilitar?store={i['mix']}", data={"on": "1"}, follow_redirects=False)
    owner.post("/admin/whatsapp/prueba", follow_redirects=False)
    from app.db import SessionLocal
    from app.models import Store
    with SessionLocal() as db:
        assert db.get(Store, i["mix"]).wa_enabled is False and db.get(Store, i["mix"]).wa_phone_id is None
    admin = login(ADMIN)
    page = admin.get("/admin/whatsapp").text
    assert "Agente de WhatsApp por comercio" in page and "Burger Mix" in page and "No habilitado" in page
    assert admin.post(f"/admin/whatsapp/habilitar?store={i['mix']}&back=list", data={"on": "1"}, follow_redirects=False).status_code == 303
    page = owner.get("/admin/whatsapp")
    assert page.status_code == 200 and "Conectar WhatsApp" in page.text and "Nunca te vamos a pedir claves" in page.text
    assert "connect.facebook.net" in page.headers["content-security-policy"]
    assert "connect.facebook.net" not in owner.get("/admin/products").headers["content-security-policy"]  # el SDK de Meta solo en esa pagina
    assert "/admin/whatsapp" in owner.get("/admin/products").text  # ahora le aparece en el menu
    assert login(OTHER).get("/admin/whatsapp", follow_redirects=False).status_code == 303  # otro local, no habilitado
    # el superadmin lo prueba con el numero de prueba de Trappi
    assert admin.post(f"/admin/whatsapp/prueba?store={i['mix']}", follow_redirects=False).status_code == 303
    with SessionLocal() as db:
        s = db.get(Store, i["mix"])
        assert s.wa_phone_id == PHONE_ID and s.wa_token is None
    assert "token-de-prueba" not in owner.get("/admin/whatsapp").text and "Agente activo" in owner.get("/admin/whatsapp").text


def test_webhook_solo_con_la_firma_de_meta_y_sin_repetir(env, meta, model):
    c = client()
    assert c.get("/api/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "verificar-123", "hub.challenge": "42"}).text == "42"
    assert c.get("/api/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "otro", "hub.challenge": "42"}).status_code == 403
    data = payload("hola, ¿qué hamburguesas tienen?", "wamid.in1")
    assert c.post("/api/whatsapp/webhook", json=data).status_code == 403  # sin firma
    assert hook(c, data, secret="otro-secreto").status_code == 403
    p = model(call("ver_menu", texto="hamburguesa"), say("Tenemos la *Hamburguesa Clásica*. ¿Te anoto una?"))
    assert hook(c, data).json()["ok"]
    assert meta.texts()[-1].startswith("Tenemos la *Hamburguesa Clásica*")
    assert meta.sent[-1][0].endswith(f"/{PHONE_ID}/messages") and meta.sent[-1][2]["Authorization"] == "Bearer token-de-prueba"
    menu = json.loads([m for m in p.seen[1][0] if m["role"] == "tool"][-1]["content"])
    assert menu["local"] == "Burger Mix" and all(x["nombre"] != "Pizza del otro" for x in menu["productos"])
    assert "Burger Mix" in p.seen[0][0][0]["content"]  # las reglas son las de este local
    n = len(meta.sent)
    hook(c, data)  # Meta reintenta el mismo aviso: no se contesta dos veces
    assert len(meta.sent) == n
    hook(c, payload("hola", "wamid.x", phone_id="000"))  # numero que no es de ningun local
    assert len(meta.sent) == n
    from app.db import SessionLocal
    from app.models import WaMessage
    with SessionLocal() as db:
        assert db.query(WaMessage).filter_by(wa_message_id="wamid.in1").count() == 1
    assert conv().name == "Marta"


def test_el_agente_no_toca_productos_de_otro_local(env):
    from app.ai import tools, wa_tools  # noqa: F401
    from app.db import SessionLocal
    from app.models import Store, WaConversation
    i = ids()
    with SessionLocal() as db:
        s = db.get(Store, i["mix"])
        c = db.query(WaConversation).filter_by(store_id=s.id).first()
        ctx = tools.ToolContext(db=db, audience="whatsapp", extra={"store": s, "conv": c})
        assert "no es del menú" in json.loads(tools.run(ctx, "agregar_al_carrito", {"producto_id": i["pizza"]}))["error"]
        assert "no es del menú" in json.loads(tools.run(ctx, "ver_producto", {"producto_id": i["pizza"]}))["error"]
        assert "no existe" in json.loads(tools.run(ctx, "buscar_comercios", {}))["error"]  # las herramientas del marketplace no estan
        assert json.loads(tools.run(ctx, "agregar_al_carrito", {"producto_id": i["clasica"], "cantidad": 2}))["ok"]
        assert ctx.cart == [{"product_id": i["clasica"], "quantity": 2, "modifiers": []}]


def test_pedido_programado_por_link_y_avisos(env, meta, model, monkeypatch):
    from app.ai import wa_tools
    from app.db import SessionLocal
    from app.models import Order, OrderStatus, WaConversation
    from app.services import owner_alerts, schedule
    from app.services.orders import set_status
    from app.services.store_hours import local_now
    i = ids()
    day = local_now().date().isoformat()
    monkeypatch.setattr(schedule, "options", lambda store, now=None: [{"date": day, "label": "Hoy", "slots": ["21:00"]}])
    monkeypatch.setattr(wa_tools, "is_open", lambda store: False)  # el local esta cerrado: se programa
    c = client()
    model(call("agregar_al_carrito", producto_id=i["clasica"], cantidad=2),
          call("preparar_pedido", entrega="retiro", horario="ahora"),
          call("preparar_pedido", entrega="retiro", horario=f"{day}T21:00"),
          say("Listo, tu pedido para hoy a las 21:00 en Burger Mix."))
    hook(c, payload("quiero 2 clásicas para retirar a las 21", "wamid.in2"))
    text = meta.texts()[-1]
    assert "Listo, tu pedido" in text and "/wa/pedido/" in text  # el link se agrega aunque el modelo no lo copie
    link = "/wa/pedido/" + text.split("/wa/pedido/")[1].split()[0]
    assert "https://trappi.com.ar/wa/pedido/" in text
    assert c.get("/wa/pedido/inventado").status_code == 404
    r = c.get(link, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/checkout"
    page = c.get("/checkout").text
    assert "Hamburguesa Clásica" in page and f'value="{day}T21:00" selected' in page
    r = c.post("/checkout", data={"first_name": "Marta", "last_name": "Gómez", "phone": "2914556677", "delivery_method": "retiro",
                                  "payment_method": "efectivo", "scheduled_for": f"{day}T21:00"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/pedido/")
    with SessionLocal() as db:
        o = db.query(Order).order_by(Order.id.desc()).first()
        cv = db.query(WaConversation).filter_by(wa_id="5492914556677").one()
        assert o.origin == "whatsapp" and o.wa_conversation_id == cv.id and o.scheduled_for is not None
        assert cv.cart is None  # el proximo pedido arranca de cero
        oid = o.id
    assert meta.texts()[-1].startswith(f"📝 Recibimos tu pedido *#{oid}* para hoy a las 21:00")
    # al dueño le llega "pedido programado por WhatsApp"
    pushed = []
    monkeypatch.setattr(owner_alerts, "push_store", lambda db, sid, data: pushed.append(data) or 1)
    with SessionLocal() as db:
        owner_alerts.new_order(db, db.get(Order, oid))
    assert pushed[-1]["title"].startswith("📅 Pedido programado por WhatsApp")
    # el local lo confirma: al cliente le llega por el mismo chat
    with SessionLocal() as db:
        o = db.get(Order, oid)
        assert set_status(o, OrderStatus.CONFIRMADO)
        db.commit()
    assert meta.texts()[-1] == f"✅ Burger Mix confirmó tu pedido #{oid}. ¡Ya lo empezamos a preparar!"
    # el link viejo ya no sirve para repetir el pedido
    assert c.get(link).status_code == 404


def test_pide_una_persona_y_el_duenio_toma_la_charla(env, meta, model, monkeypatch):
    from app.services import owner_alerts
    pushed = []
    monkeypatch.setattr(owner_alerts, "push_store_later", lambda sid, data: pushed.append(data))
    c = client()
    model(call("pedir_persona", tipo="no_se", motivo="¿Tienen opciones sin TACC?"), say("Eso te lo confirma alguien del local."))
    hook(c, payload("¿tienen sin tacc?", "wamid.in3"))
    cv = conv()
    assert cv.mode == "human" and cv.needs == "unknown" and pushed[-1]["title"].startswith("⚠️ El agente de WhatsApp no supo")
    assert meta.texts()[-1] == "Eso te lo confirma alguien del local."
    # mientras atiende el dueño, el agente no contesta: al dueño le llega que le escribieron
    p = model(say("no deberia hablar"))
    n = len(meta.sent)
    hook(c, payload("¿y?", "wamid.in4"))
    assert len(meta.sent) == n and p.seen == [] and pushed[-1]["title"].startswith("💬 Marta te escribió")
    owner = login(OWNER)
    j = owner.get(f"/admin/whatsapp/c/{cv.id}").json()
    assert j["ok"] and j["mode"] == "human" and j["window"] and any(m["text"] == "¿y?" for m in j["messages"])
    assert login(OTHER).get(f"/admin/whatsapp/c/{cv.id}").status_code in (303, 404)  # otro local no la ve
    r = owner.post(f"/admin/whatsapp/c/{cv.id}/enviar", data={"text": "Sí, tenemos pan sin TACC."}).json()
    assert r["ok"] and r["needs"] is None and meta.texts()[-1] == "Sí, tenemos pan sin TACC."
    assert "Sí, tenemos pan sin TACC." in owner.get(f"/admin/whatsapp?c={cv.id}").text
    assert owner.post(f"/admin/whatsapp/c/{cv.id}/devolver").json()["mode"] == "agent"
    # pasadas las 24 h WhatsApp no deja escribir libre
    from app.db import SessionLocal
    from app.models import WaConversation
    with SessionLocal() as db:
        db.get(WaConversation, cv.id).last_in_at = datetime.utcnow() - timedelta(hours=25)
        db.commit()
    assert "24 h" in owner.post(f"/admin/whatsapp/c/{cv.id}/enviar", data={"text": "hola"}).json()["error"]
    # avisos: el dueño los elige
    owner.post("/admin/whatsapp/avisos", data={"a_order": "1"})
    from app.models import Store
    from app.services import wa_agent
    with SessionLocal() as db:
        assert wa_agent.alerts(db.get(Store, ids()["mix"])) == {"order": True, "person": False, "unknown": False, "summary": False}


def test_sin_modelo_no_inventa_y_pasa_al_duenio(env, meta, monkeypatch):
    from app.ai import providers
    from app.services import owner_alerts
    monkeypatch.setattr(owner_alerts, "push_store_later", lambda sid, data: None)
    providers.set_override(None)
    monkeypatch.setattr(providers, "get_provider", lambda: None)
    c = client()
    hook(c, payload("hola", "wamid.n1", who="5492915550000", name="Lucas"))
    assert "En un rato te responde alguien del local" in meta.texts()[-1]
    from app.db import SessionLocal
    from app.models import WaConversation
    with SessionLocal() as db:
        cv = db.query(WaConversation).filter_by(wa_id="5492915550000").one()
        assert cv.mode == "human" and cv.needs == "unknown"


def test_conectar_el_numero_del_local_sin_ver_el_token(env, monkeypatch):
    from app.services import wa_agent
    i = ids()
    owner = login(OWNER)
    owner.post("/admin/whatsapp/desconectar")

    def fake_get(url, **kw):
        if url.endswith("/oauth/access_token"):
            assert kw["params"]["client_secret"] == SECRET and kw["params"]["code"] == "codigo-meta"
            return type("R", (), {"status_code": 200, "json": lambda s: {"access_token": "token-del-local-secreto"}})()
        assert url.endswith("/555/phone_numbers") and kw["headers"]["Authorization"] == "Bearer token-del-local-secreto"
        return type("R", (), {"status_code": 200, "json": lambda s: {"data": [{"id": "777", "display_phone_number": "+54 9 291 400-1122"}]}})()
    monkeypatch.setattr(wa_agent.httpx, "get", fake_get)
    monkeypatch.setattr(wa_agent.httpx, "post", lambda url, **kw: type("R", (), {"status_code": 200, "json": lambda s: {"success": True}})())
    bad = owner.post("/admin/whatsapp/conectar", data={"code": "codigo-meta", "waba_id": "555", "phone_id": "888"}).json()
    assert not bad["ok"] and "no es de la cuenta" in bad["error"]
    r = owner.post("/admin/whatsapp/conectar", data={"code": "codigo-meta", "waba_id": "555", "phone_id": "777"}).json()
    assert r["ok"] and r["number"] == "+54 9 291 400-1122"
    from app.db import SessionLocal
    from app.models import Store
    from app.services import crypto
    with SessionLocal() as db:
        s = db.get(Store, i["mix"])
        assert s.wa_phone_id == "777" and s.wa_token != "token-del-local-secreto" and crypto.decrypt(s.wa_token) == "token-del-local-secreto"
    page = owner.get("/admin/whatsapp").text
    assert "token-del-local-secreto" not in page and "+54 9 291 400-1122" in page
    # el otro local no puede conectar el mismo numero
    admin = login(ADMIN)
    admin.post(f"/admin/whatsapp/habilitar?store={i['other']}", data={"on": "1"})
    other = login(OTHER)
    assert "otro local" in other.post("/admin/whatsapp/conectar", data={"code": "codigo-meta", "waba_id": "555", "phone_id": "777"}).json()["error"]
    # deshabilitado por el superadmin: el local deja de verlo y el webhook no lo atiende
    admin.post(f"/admin/whatsapp/habilitar?store={i['mix']}", data={"on": "0"})
    assert owner.get("/admin/whatsapp", follow_redirects=False).status_code == 303


def test_varios_mensajes_seguidos_una_sola_respuesta(env, meta, model):
    from app.db import SessionLocal
    from app.models import WaConversation
    with SessionLocal() as db:
        db.query(WaConversation).filter_by(wa_id="5492914556677").one().mode = "agent"
        db.commit()
    i = ids()
    from app.db import SessionLocal as S
    from app.models import Store
    with S() as db:
        s = db.get(Store, i["mix"])
        s.wa_enabled, s.wa_phone_id, s.wa_token = True, PHONE_ID, None
        db.commit()
    p = model(say("¡Dale! ¿Cuántas querés?"))
    data = payload("hola", "wamid.m1")
    data["entry"][0]["changes"][0]["value"]["messages"].append({"id": "wamid.m2", "from": "5492914556677", "type": "text", "text": {"body": "quiero hamburguesas"}})
    n = len(meta.sent)
    hook(client(), data)
    assert len(meta.sent) == n + 1 and len(p.seen) == 1
    assert p.seen[0][0][-1] == {"role": "user", "content": "hola\nquiero hamburguesas"}
    # un audio: el agente avisa que solo lee texto (sin gastar el modelo)
    audio = payload("x", "wamid.m3")
    audio["entry"][0]["changes"][0]["value"]["messages"][0] = {"id": "wamid.m3", "from": "5492914556677", "type": "audio"}
    hook(client(), audio)
    assert "leo solo mensajes de texto" in meta.texts()[-1] and len(p.seen) == 1


def test_cobro_por_mensaje_en_pesos(env, monkeypatch):
    from app.db import SessionLocal
    from app.models import LedgerEntry, Setting, Store, WaConversation, WaMessage
    from app.services import platform, wa_agent
    i = ids()
    admin = login(ADMIN)
    with SessionLocal() as db:
        s = db.get(Store, i["mix"])
        s.wa_enabled = True
        db.commit()
    # numero en la cuenta de Trappi: Meta lo reconoce con el token de Trappi
    monkeypatch.setattr(wa_agent.httpx, "get", lambda url, **kw: type("R", (), {"status_code": 200 if url.endswith("/5551") else 404,
                        "json": lambda self: {"display_phone_number": "+54 9 291 555-0001"}})())
    r = admin.post(f"/admin/whatsapp/numero-trappi?store={i['mix']}", data={"phone_id": "9999"})
    assert "Meta no reconoce ese número" in r.text
    admin.post(f"/admin/whatsapp/numero-trappi?store={i['mix']}", data={"phone_id": "5551"})
    with SessionLocal() as db:
        s = db.get(Store, i["mix"])
        assert s.wa_phone_id == "5551" and s.wa_trappi and s.wa_token is None and wa_agent.token_for(s) == "token-de-prueba"
    owner = login(OWNER)
    assert owner.post(f"/admin/whatsapp/precio?store={i['mix']}", data={"price": "1"}, follow_redirects=False).headers["location"] == "/admin"  # solo Trappi
    # cargo general $30; este local $25
    with SessionLocal() as db:
        db.add(Setting(key="wa_message_price", value="30")); db.commit()
    platform.invalidate()
    admin.post(f"/admin/whatsapp/precio?store={i['mix']}", data={"price": "25"})
    yesterday = datetime.utcnow() - timedelta(days=1, hours=2)
    with SessionLocal() as db:
        c = db.query(WaConversation).filter_by(store_id=i["mix"]).first()
        for st in ("sent", "sent", "sent", "failed", "skipped"):
            db.add(WaMessage(conversation_id=c.id, store_id=i["mix"], direction="out", author="agent", text="x", status=st, created_at=yesterday))
        db.add(WaMessage(conversation_id=c.id, store_id=i["mix"], direction="in", author="customer", text="hola", created_at=yesterday))
        db.add(WaMessage(conversation_id=c.id, store_id=i["mix"], direction="out", author="agent", text="hoy", status="sent", created_at=datetime.utcnow()))
        db.query(WaMessage).filter(WaMessage.created_at < yesterday - timedelta(hours=1)).update({"billed_at": datetime.utcnow()})  # lo de antes, ya cobrado
        db.commit()
        assert wa_agent.bill(db) == 1
        e = db.query(LedgerEntry).filter_by(account="merchant", kind="whatsapp", store_id=i["mix"]).one()
        assert e.amount == Decimal("-75.00") and "3 mensajes" in e.description  # solo los que salieron, solo los de ayer
        assert wa_agent.bill(db) == 0  # no se cobra dos veces
        assert db.query(WaMessage).filter_by(text="hoy").one().billed_at is None  # lo de hoy se cobra mañana
    page = owner.get("/admin/whatsapp").text
    assert "Cada mensaje que sale por tu WhatsApp cuesta $25" in page and "sin dólares" in page
