"""Trappi AI: proveedores, herramientas validadas por el backend, conversacion y endpoints (sin salir a internet)."""
import json
import os
import sys
from decimal import Decimal

import httpx
import pytest

ADMIN = {"email": "admin@test.local", "password": "TestOnly-123!"}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("ai") / "ai.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["ENVIRONMENT"] = "development"
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]
    from app import seed
    from app.db import Base, SessionLocal, engine
    from app.models import ModifierGroup, ModifierOption, Product, Store, StoreHour
    Base.metadata.create_all(engine)
    seed.ADMIN_EMAIL = ADMIN["email"]
    seed.settings.admin_password = ADMIN["password"]
    seed.run_seed()
    with SessionLocal() as db:
        mix = db.query(Store).filter_by(slug="burger-mix").one()
        house = Store(name="Burger House", slug="burger-house", description="Hamburguesas de autor", status=mix.status, account_status="activo",
                      city_id=mix.city_id, rating_avg=Decimal("4.8"), rating_count=120, estimated_minutes=20, delivery_enabled=True)
        closed = Store(name="Pizza Noche", slug="pizza-noche", status=mix.status, account_status="activo", city_id=mix.city_id)
        db.add_all([house, closed]); db.flush()
        db.add_all([StoreHour(store_id=closed.id, weekday=d, open_time="03:00", close_time="03:00", closed=True) for d in range(7)])
        doble = Product(store_id=house.id, name="Hamburguesa doble cheddar", description="Doble carne, cheddar", price=Decimal("12500"))
        coca = Product(store_id=house.id, name="Coca-Cola 500 ml", price=Decimal("2500"), previous_price=Decimal("3000"))
        pizza = Product(store_id=closed.id, name="Pizza muzzarella", price=Decimal("9000"))
        db.add_all([doble, coca, pizza]); db.flush()
        g = ModifierGroup(product_id=doble.id, name="Punto de la carne", required=True, min_select=1, max_select=1)
        db.add(g); db.flush()
        db.add_all([ModifierOption(group_id=g.id, name="A punto"), ModifierOption(group_id=g.id, name="Bien cocida", price_extra=Decimal("0"))])
        db.commit()
    yield
    engine.dispose()


def ids():
    from app.db import SessionLocal
    from app.models import ModifierOption, Product, Store
    with SessionLocal() as db:
        return {
            "house": db.query(Store).filter_by(slug="burger-house").one().id, "mix": db.query(Store).filter_by(slug="burger-mix").one().id,
            "doble": db.query(Product).filter_by(name="Hamburguesa doble cheddar").one().id,
            "coca": db.query(Product).filter_by(name="Coca-Cola 500 ml").one().id,
            "clasica": db.query(Product).filter_by(name="Hamburguesa Clásica").one().id,
            "pizza": db.query(Product).filter_by(name="Pizza muzzarella").one().id,
            "a_punto": db.query(ModifierOption).filter_by(name="A punto").one().id,
        }


class Scripted:
    """Modelo falso: cada paso es una funcion (mensajes) -> AIReply. Guarda lo que vio."""
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


def last_tool(messages) -> dict:
    return json.loads([m for m in messages if m["role"] == "tool"][-1]["content"])


@pytest.fixture
def fake(env):
    from app.ai import providers
    from app.services import ratelimit
    ratelimit.PersistentRateLimiter("ai").clear()

    def install(*steps):
        p = Scripted(*steps)
        providers.set_override(p)
        return p
    yield install
    providers.set_override(None)


def client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def test_sin_modelo_el_asistente_no_aparece(env):
    c = client()
    assert c.get("/api/v1/config").json()["ai"]["available"] is False
    assert c.post("/api/v1/ai/chat", json={"message": "hola"}).status_code == 503


def test_recomienda_con_datos_reales(fake):
    seen = {}

    def answer(messages):
        from app.ai.providers import AIReply
        seen["result"] = last_tool(messages)
        return AIReply(text="🍔 Encontré Burger House ⭐ 4,8")
    p = fake(call("buscar_comercios", texto="hamburguesas", orden="valoracion", inventado="x"), answer)
    r = client().post("/api/v1/ai/chat", json={"message": "¿Me recomendás locales que tengan buenas hamburguesas?"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["mode"] == "ai" and data["reply"].startswith("🍔")
    found = seen["result"]["comercios"]
    names = [s["nombre"] for s in found]
    assert names[0] == "Burger House" and "Burger Mix" in names and "Pizza Noche" not in names  # por valoracion; sin hamburguesas no aparece
    assert found[0]["valoracion"] == 4.8 and found[0]["cantidad_resenas"] == 120 and found[0]["distancia_km"] is None
    assert "Hamburguesa doble cheddar" in found[0]["productos_que_coinciden"]
    assert seen["result"]["nota"]  # sin ubicacion lo dice
    assert {c["store"]["slug"] for c in data["cards"] if c["type"] == "store"} == {"burger-house", "burger-mix"}
    # el sistema le da las reglas y el contexto; las herramientas son solo las del cliente
    system, tools_offered = p.seen[0][0][0]["content"], {t["name"] for t in p.seen[0][1]}
    assert "Nunca inventes" in system and "NO compartió su ubicación" in system
    assert tools_offered == {"buscar_comercios", "buscar_productos", "buscar_promociones", "ver_comercio", "ver_producto", "ver_carrito",
                             "agregar_al_carrito", "actualizar_cantidad", "eliminar_del_carrito", "mis_pedidos", "consultar_pedido", "recomendados_para_mi"}


def test_pedido_completo_hasta_el_carrito(fake):
    i = ids()
    c = client()
    # 1. busca la hamburguesa y la coca en Burger House
    fake(call("buscar_productos", texto="hamburguesa doble con cheddar", comercio_id=i["house"]), say("Encontré la Hamburguesa doble cheddar a $12.500. ¿La agrego?"))
    r = c.post("/api/v1/ai/chat", json={"message": "Quiero una hamburguesa doble con cheddar de Burger House"}).json()
    assert [x["product"]["name"] for x in r["cards"] if x["type"] == "product"][0] == "Hamburguesa doble cheddar"
    state = r["state"]
    # 2. "sí": sin la opcion obligatoria el backend no la agrega y le dice al modelo que pregunte
    seen = {}

    def check(messages):
        from app.ai.providers import AIReply
        seen["err"] = last_tool(messages)["error"]
        return AIReply(text="¿Cómo querés la carne?")
    p = fake(call("agregar_al_carrito", producto_id=i["doble"], cantidad=1), check)
    r = c.post("/api/v1/ai/chat", json={"message": "Sí", "state": state}).json()
    assert "Punto de la carne" in seen["err"] and r["cart_changed"] is False
    assert any(m.get("content") == "Quiero una hamburguesa doble con cheddar de Burger House" for m in p.seen[0][0])  # recuerda la charla
    # 3. con la opcion y la coca: carrito real con precios actuales
    from app.ai.providers import AIReply, ToolCall
    fake(lambda m: AIReply(tool_calls=[ToolCall("a", "agregar_al_carrito", {"producto_id": i["doble"], "opciones_ids": [i["a_punto"]]}),
                                       ToolCall("b", "agregar_al_carrito", {"producto_id": i["coca"], "cantidad": 2})]),
         say("Listo, agregué todo. Confirmalo en Mi pedido."))
    r = c.post("/api/v1/ai/chat", json={"message": "A punto, y dos cocas", "state": r["state"]}).json()
    assert r["cart_changed"] is True
    cart = {x["name"]: x for x in r["cart"]}
    assert cart["Hamburguesa doble cheddar"]["modifiers"] == [i["a_punto"]] and cart["Hamburguesa doble cheddar"]["store_slug"] == "burger-house"
    assert cart["Coca-Cola 500 ml"]["quantity"] == 2 and cart["Coca-Cola 500 ml"]["unit_price"] == 2500
    items = [{"product_id": x["product_id"], "quantity": x["quantity"], "modifiers": x["modifiers"]} for x in r["cart"]]
    # 4. cambiar cantidad y sacar una linea
    fake(call("actualizar_cantidad", linea=2, cantidad=1), say("Dejé una sola Coca."))
    r = c.post("/api/v1/ai/chat", json={"message": "mejor una coca", "items": items}).json()
    assert {x["name"]: x["quantity"] for x in r["cart"]} == {"Hamburguesa doble cheddar": 1, "Coca-Cola 500 ml": 1}
    # 5. otro comercio: no reemplaza sin permiso
    seen.clear()
    fake(call("agregar_al_carrito", producto_id=i["clasica"]), check)
    r = c.post("/api/v1/ai/chat", json={"message": "sumá una clásica de Burger Mix", "items": items}).json()
    assert "Burger House" in seen["err"] and r["cart_changed"] is False


def test_validaciones_del_backend(fake):
    from app.ai import tools
    from app.ai.tools import ToolContext
    from app.db import SessionLocal
    i = ids()
    with SessionLocal() as db:
        ctx = ToolContext(db=db)
        run = lambda name, **a: json.loads(tools.run(ctx, name, a))  # noqa: E731
        assert "cerrado" in run("agregar_al_carrito", producto_id=i["pizza"])["error"]
        assert "no existe" in run("agregar_al_carrito", producto_id=999999)["error"]
        assert "no corresponde" in run("agregar_al_carrito", producto_id=i["doble"], opciones_ids=[123456])["error"]
        assert "no existe" in run("borrar_base_de_datos")["error"]
        assert "no inició sesión" in run("mis_pedidos")["error"]
        assert run("agregar_al_carrito", producto_id=i["coca"], cantidad=500)["carrito"]["lineas"][0]["cantidad"] == 20  # tope
        assert "no existe" in run("eliminar_del_carrito", linea=9)["error"]
        assert run("buscar_productos", precio_max=3000)["productos"][0]["precio_numero"] <= 3000
        promos = run("buscar_promociones")["productos"]
        assert [p["nombre"] for p in promos] == ["Coca-Cola 500 ml"] and promos[0]["precio_anterior"] == "$3.000"
        detail = run("ver_producto", producto_id=i["doble"])
        assert detail["grupos_de_opciones"][0]["obligatorio"] is True and detail["disponible_ahora"] is True
        assert run("ver_producto", producto_id=i["pizza"])["disponible_ahora"] is False
        assert [s["nombre"] for s in run("buscar_comercios", abierto_ahora=True, limite=8)["comercios"]].count("Pizza Noche") == 0
        assert run("ver_comercio", comercio_id=i["house"])["menu"][0]["precio"].startswith("$")


def test_pedidos_solo_del_usuario(fake):
    from app.ai import tools
    from app.ai.tools import ToolContext
    from app.db import SessionLocal
    from app.models import ClientAccount, Customer, Order, OrderStatus
    i = ids()
    with SessionLocal() as db:
        mine, other = ClientAccount(email="yo@x.com"), ClientAccount(email="otro@x.com")
        db.add_all([mine, other]); db.flush()
        def order(acct, status):
            o = Order(store_id=i["house"], customer=Customer(first_name="X", last_name="Y", phone="1"), delivery_method="retiro", subtotal=1, shipping=0,
                      total=Decimal("12500"), status=status, account_id=acct.id)
            db.add(o); db.flush()
            return o.id
        mine_id, other_id = order(mine, OrderStatus.PREPARANDO), order(other, OrderStatus.ENTREGADO)
        db.commit()
        ctx = ToolContext(db=db, account=db.get(ClientAccount, mine.id))
        run = lambda name, **a: json.loads(tools.run(ctx, name, a))  # noqa: E731
        assert [p["pedido_id"] for p in run("mis_pedidos")["pedidos"]] == [mine_id]
        assert run("consultar_pedido")["estado"] == "en preparación"
        assert "No encontramos" in run("consultar_pedido", pedido_id=other_id)["error"]
        assert "phone" not in json.dumps(run("consultar_pedido", pedido_id=mine_id))


def test_si_el_modelo_falla_responde_en_modo_basico(fake):
    from app.ai.providers import AIUnavailable

    def broken(messages):
        raise AIUnavailable("timeout")
    fake(broken)
    r = client().post("/api/v1/ai/chat", json={"message": "coca cola"}).json()
    assert r["mode"] == "basic" and "no está disponible" in r["reply"]
    assert {c["product"]["name"] for c in r["cards"]} >= {"Coca-Cola 500 ml", "Coca Cola"}


def test_estado_firmado_y_limite(fake):
    from app.ai import assistant
    assert assistant.load_state("falso") == [] and assistant.load_state(None) == []
    hist = [{"role": "assistant", "content": "x"}] + [{"role": "user", "content": str(n)} for n in range(40)]
    assert len(assistant.trim(hist)) == assistant.MAX_HISTORY and assistant.trim(hist)[0]["role"] == "user"
    from app.services import platform
    from app.db import SessionLocal
    from app.models import Setting
    with SessionLocal() as db:
        db.add(Setting(key="ai_messages_per_hour", value="2")); db.commit()
    platform.invalidate()
    fake(say("1"), say("2"), say("3"))
    c = client()
    assert c.post("/api/v1/ai/chat", json={"message": "a"}).status_code == 200
    assert c.post("/api/v1/ai/chat", json={"message": "b"}).status_code == 200
    assert c.post("/api/v1/ai/chat", json={"message": "c"}).status_code == 429
    with SessionLocal() as db:
        db.query(Setting).filter_by(key="ai_messages_per_hour").delete()
        db.add(Setting(key="ai_enabled", value="0")); db.commit()
    platform.invalidate()
    assert c.get("/api/v1/config").json()["ai"]["available"] is False
    with SessionLocal() as db:
        db.query(Setting).filter_by(key="ai_enabled").delete(); db.commit()
    platform.invalidate()


def test_chat_web_usa_el_carrito_de_la_sesion(fake):
    i = ids()
    c = client()
    fake(call("agregar_al_carrito", producto_id=i["coca"], cantidad=3), say("Agregué 3 Coca-Cola."))
    r = c.post("/api/ai/chat", json={"message": "agregame 3 cocas de burger house"})
    assert r.status_code == 200 and r.json()["cart_count"] == 3 and "cart" not in r.json()
    assert c.get("/api/cart").json()["count"] == 3
    assert c.post("/api/ai/chat", json={"message": "x"}, headers={"Origin": "https://malo.example"}).status_code == 403
    assert "Trappi AI" in c.get("/asistente").text


def test_ollama_traduce_mensajes_y_herramientas():
    from app.ai.providers import OllamaProvider
    sent = {}

    def handler(request):
        sent.update(json.loads(request.content), url=str(request.url))
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "<think>razono</think>",
                                                     "tool_calls": [{"function": {"name": "buscar_comercios", "arguments": {"texto": "pizza"}}}]}})
    p = OllamaProvider(base_url="http://ia:11434/", model="qwen2.5:7b", transport=httpx.MockTransport(handler))
    reply = p.chat([{"role": "system", "content": "s"}, {"role": "user", "content": "pizza"},
                    {"role": "assistant", "content": "", "tool_calls": [{"id": "1", "name": "ver_carrito", "arguments": {}}]},
                    {"role": "tool", "tool_call_id": "1", "name": "ver_carrito", "content": "{}"}], [{"name": "buscar_comercios", "description": "d", "parameters": {}}])
    assert sent["url"] == "http://ia:11434/api/chat" and sent["model"] == "qwen2.5:7b" and sent["stream"] is False
    assert sent["tools"][0]["function"]["name"] == "buscar_comercios"
    assert sent["messages"][2]["tool_calls"][0]["function"]["name"] == "ver_carrito" and sent["messages"][3]["tool_name"] == "ver_carrito"
    assert reply.text == "" and reply.tool_calls[0].name == "buscar_comercios" and reply.tool_calls[0].arguments == {"texto": "pizza"}


def test_openai_compatible_y_errores():
    from app.ai.providers import AIUnavailable, OpenAICompatibleProvider
    sent = {}

    def handler(request):
        sent.update(json.loads(request.content), auth=request.headers.get("authorization"), url=str(request.url))
        return httpx.Response(200, json={"choices": [{"message": {"content": None, "tool_calls": [
            {"id": "x1", "type": "function", "function": {"name": "ver_producto", "arguments": "{\"producto_id\": 5}"}},
            {"id": "x2", "type": "function", "function": {"name": "ver_carrito", "arguments": "no es json"}}]}}]})
    p = OpenAICompatibleProvider(base_url="https://api.groq.com/openai/v1", model="llama-3.3-70b", api_key="clave", transport=httpx.MockTransport(handler))
    reply = p.chat([{"role": "user", "content": "hola"}, {"role": "assistant", "content": "", "tool_calls": [{"id": "t", "name": "ver_carrito", "arguments": {"a": 1}}]},
                    {"role": "tool", "tool_call_id": "t", "name": "ver_carrito", "content": "{}"}], [])
    assert sent["url"].endswith("/chat/completions") and sent["auth"] == "Bearer clave" and sent["tool_choice"] == "auto"
    assert sent["messages"][1]["tool_calls"][0]["function"]["arguments"] == "{\"a\": 1}" and sent["messages"][2]["tool_call_id"] == "t"
    assert reply.tool_calls[0].arguments == {"producto_id": 5} and reply.tool_calls[1].arguments == {}
    assert sent["messages"][1]["content"] == "" and sent["max_tokens"] == 2048  # Workers AI: sin null y con largo suficiente
    cut = OpenAICompatibleProvider(base_url="http://x", model="m", transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"choices": [{"message": {"content": None}, "finish_reason": "length"}]})))
    with pytest.raises(AIUnavailable, match="AI_MAX_TOKENS"):
        cut.chat([{"role": "user", "content": "hola"}], [])
    down = OpenAICompatibleProvider(base_url="http://x", model="m", transport=httpx.MockTransport(lambda r: httpx.Response(500, text="boom")))
    with pytest.raises(AIUnavailable):
        down.chat([{"role": "user", "content": "hola"}], [])


def test_servidor_propio_detras_de_cloudflare_access():
    from app.ai.providers import AIUnavailable, OllamaProvider
    seen = {}

    def handler(request):
        seen.update(request.headers)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "hola"}})
    p = OllamaProvider(base_url="https://ia.trappi.test", model="qwen2.5:7b", transport=httpx.MockTransport(handler),
                       cf_access_id="id.access", cf_access_secret="secreto")
    assert p.chat([{"role": "user", "content": "hola"}], []).text == "hola"
    assert seen["cf-access-client-id"] == "id.access" and seen["cf-access-client-secret"] == "secreto" and "authorization" not in seen
    # sin el token, Cloudflare Access responde con su pagina de ingreso (HTML): se trata como modelo no disponible
    login = OllamaProvider(base_url="https://ia.trappi.test", model="m",
                           transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>Sign in</html>", headers={"content-type": "text/html"})))
    with pytest.raises(AIUnavailable):
        login.chat([{"role": "user", "content": "hola"}], [])


def test_una_vuelta_larga_no_borra_la_charla():
    from app.ai import assistant
    turn = [{"role": "user", "content": "quiero todo"}]
    for r in range(5):
        turn.append({"role": "assistant", "content": "", "tool_calls": [{"id": f"{r}{k}", "name": "ver_carrito", "arguments": {}} for k in range(4)]})
        turn += [{"role": "tool", "tool_call_id": f"{r}{k}", "name": "ver_carrito", "content": "{}"} for k in range(4)]
    turn.append({"role": "assistant", "content": "listo"})
    kept = assistant.trim([{"role": "user", "content": "viejo"}, {"role": "assistant", "content": "x"}] + turn)
    assert kept[0] == {"role": "user", "content": "quiero todo"} and kept[-1]["content"] == "listo"


def test_si_el_modelo_falla_a_mitad_no_toca_el_carrito(fake):
    from app.ai.providers import AIUnavailable
    i = ids()

    def timeout(messages):
        raise AIUnavailable("timeout")
    fake(call("agregar_al_carrito", producto_id=i["coca"]), timeout)
    r = client().post("/api/v1/ai/chat", json={"message": "agregame una coca"}).json()
    assert r["mode"] == "basic" and r["cart_changed"] is False and r["cart"] is None


def test_precios_que_manda_el_modelo():
    from app.ai.client_tools import _price
    assert [_price(x) for x in (15000, "15000.50", "15000.0", "15.000", "$15.000,50", "nada")] == [15000.0, 15000.5, 15000.0, 15000.0, 15000.5, None]


def test_modo_basico_entiende_lo_mas_comun(env):
    from app.ai import assistant
    from app.ai.tools import ToolContext
    from app.db import SessionLocal
    from app.models import ClientAccount, Customer, Order, OrderStatus
    i = ids()
    with SessionLocal() as db:
        def ask(text, account=None):
            ctx = ToolContext(db=db, account=account)
            return assistant.basic(ctx, text, [{"role": "user", "content": text}]), ctx
        r, _ = ask("¿Dónde está mi pedido?")
        assert "entrá con tu cuenta" in r["reply"] and r["cards"] == []
        acct = ClientAccount(email="basic@x.com")
        db.add(acct); db.flush()
        r, _ = ask("¿Dónde está mi pedido?", acct)
        assert "Todavía no hiciste pedidos" in r["reply"]
        o = Order(store_id=i["house"], customer=Customer(first_name="X", last_name="Y", phone="1"), delivery_method="retiro", subtotal=1, shipping=0,
                  total=Decimal("12500"), status=OrderStatus.PREPARANDO, account_id=acct.id)
        db.add(o); db.commit()
        r, _ = ask("¿Dónde está mi pedido?", acct)
        assert f"#{o.id} de Burger House" in r["reply"] and "en preparación" in r["reply"]
        r, _ = ask("¿Qué está abierto ahora?")
        names = {c["store"]["name"] for c in r["cards"] if c["type"] == "store"}
        assert "Burger House" in names and "Pizza Noche" not in names and "abiertos ahora" in r["reply"]
        r, _ = ask("Mostrame opciones por menos de $15.000")
        prices = [c["product"]["price"] for c in r["cards"] if c["type"] == "product"]
        assert prices and all(p <= 15000 for p in prices) and "$15.000" in r["reply"]
        r, _ = ask("Buscame hamburguesas cerca")
        assert any(c["type"] == "store" and c["store"]["name"] == "Burger House" for c in r["cards"])
        r, _ = ask("promociones")
        assert any(c["type"] == "product" and c["product"]["name"] == "Coca-Cola 500 ml" for c in r["cards"])
        for text in ("hola", "¿Qué me recomendás?", "tengo hambre", "¿cuál es la capital de Francia?"):
            r, _ = ask(text)
            names = {c["store"]["name"] for c in r["cards"] if c["type"] == "store"}
            assert "Burger House" in names and "Pizza Noche" not in names, text  # siempre algo real de Trappi, y abierto
            assert "recomendados" in r["reply"], text


def test_diagnostico_de_la_conexion(env):
    from app.ai import providers

    def run(handler):
        p = providers.OllamaProvider(base_url="https://ia.x", model="qwen2.5:7b", transport=httpx.MockTransport(handler))
        providers.set_override(p)
        try:
            return providers.diagnose()
        finally:
            providers.set_override(None)
    ok = run(lambda req: httpx.Response(200, json={"message": {"content": "ok"}}))
    assert ok["ok"] and "ok" in ok["detail"]
    missing = run(lambda req: httpx.Response(404, json={"error": "model 'qwen2.5:7b' not found"}))
    assert not missing["ok"] and "ollama pull" in missing["hint"]
    login = run(lambda req: httpx.Response(200, text="<html>login</html>", headers={"content-type": "text/html"}))
    assert "Cloudflare Access" in login["hint"]

    def down(req):
        raise httpx.ConnectError("no")
    assert "AI_BASE_URL" in run(down)["hint"]
    assert providers.diagnose()["detail"] == "Sin configurar."


def test_charla_de_prueba_del_panel(fake):
    from app.ai import assistant
    from app.ai.providers import AIUnavailable
    from app.db import SessionLocal

    def rejected(messages):
        raise AIUnavailable("openai: HTTP 400 bad tool message")
    fake(call("buscar_comercios", abierto_ahora=True), rejected)
    with SessionLocal() as db:
        r = assistant.diagnose_chat(db)
        assert not r["ok"] and r["detail"].startswith("vuelta 2 de la charla") and "HTTP 400" in r["detail"]
        fake(call("buscar_comercios", abierto_ahora=True), say("Burger House está abierto 🍔"))
        r = assistant.diagnose_chat(db)
        assert r["ok"] and not r["hint"] and "Burger House" in r["detail"]
        fake(say("Hay muchos comercios"))
        assert "herramientas" in assistant.diagnose_chat(db)["hint"]


def test_panel_prueba_la_ia(env):
    c = client()
    c.post("/admin/login", data=ADMIN)
    page = c.post("/admin/settings/ai-test")
    assert page.status_code == 200 and "No responde" in page.text and "Sin configurar." in page.text
    assert client().post("/admin/settings/ai-test", follow_redirects=False).status_code in (303, 403)
