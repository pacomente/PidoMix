import os

# los tests nunca salen a internet: sin proveedor de rutas real (cada test pone uno falso si lo necesita)
os.environ.setdefault("ROUTING_PROVIDER", "none")
os.environ.setdefault("MERCADOPAGO_API_URL", "https://mp.invalid")


# ---------- CSRF en los tests ----------
# El panel exige el token CSRF de la sesion en cada envio. Los tests que no lo prueban a proposito lo
# mandan solos: se lee de la cookie de sesion (base64 + firma; el contenido se puede leer, no cambiar).
import base64
import json

from starlette.testclient import TestClient

_original_request = TestClient.request


def _session_token(client):
    raw = client.cookies.get("session")
    if not raw:
        return None
    try:
        data = raw.split(".")[0]
        return json.loads(base64.b64decode(data + "=" * (-len(data) % 4))).get("csrf")
    except ValueError:
        return None


def _request_with_csrf(self, method, url, *args, **kwargs):
    headers = dict(kwargs.pop("headers", None) or {})
    if method.upper() not in ("GET", "HEAD", "OPTIONS") and not headers.pop("x-no-csrf", None):
        if "x-csrf-token" not in {k.lower() for k in headers}:
            token = _session_token(self)
            if token is None and str(url).startswith("/admin") and not str(url).startswith("/admin/login"):
                _original_request(self, "GET", "/admin/account")  # crea el token en la sesion
                token = _session_token(self)
            if token:
                headers["X-CSRF-Token"] = token
    return _original_request(self, method, url, *args, headers=headers or None, **kwargs)


TestClient.request = _request_with_csrf
