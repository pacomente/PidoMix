"""Proteccion CSRF del panel: cada formulario lleva un token secreto de la sesion.

Una pagina de otro sitio no puede leer el token, asi que no puede mandar formularios al panel en
nombre de un admin logueado (aunque el navegador le mande la cookie). Ademas, si el navegador
informa el origen (Origin), tiene que ser este mismo sitio.

- En las plantillas: {{ csrf_input() }} dentro de cada <form method="post">.
- Por fetch: el campo del formulario (FormData) o el encabezado X-CSRF-Token.
"""
import hmac
import secrets
from urllib.parse import urlsplit

from fastapi import Request
from jinja2 import pass_context
from markupsafe import Markup

SESSION_KEY = 'csrf'
FIELD = 'csrf_token'
HEADER = 'x-csrf-token'
SAFE_METHODS = {'GET', 'HEAD', 'OPTIONS'}
# antes de iniciar sesion no hay nada que proteger con el token (solo se mira el origen)
TOKEN_EXEMPT = ('/admin/login',)


class CSRFError(Exception):
    pass


def token(request: Request) -> str:
    value = request.session.get(SESSION_KEY)
    if not value:
        value = secrets.token_urlsafe(32)
        request.session[SESSION_KEY] = value
    return value


@pass_context
def csrf_input(context) -> Markup:
    request = context.get('request')
    if request is None:
        return Markup('')
    return Markup(f'<input type="hidden" name="{FIELD}" value="{token(request)}">')


@pass_context
def csrf_meta(context) -> Markup:
    request = context.get('request')
    return Markup(f'<meta name="csrf-token" content="{token(request)}">') if request is not None else Markup('')


def same_origin(request: Request) -> bool:
    """Sin encabezado Origin (navegadores viejos, herramientas) se acepta: el token es la proteccion principal."""
    origin = request.headers.get('origin')
    if not origin:
        return True
    if origin == 'null':
        return False
    return (urlsplit(origin).netloc or '').lower() == (request.headers.get('host') or '').lower()


async def protect(request: Request) -> None:
    """Dependencia de los routers del panel: frena los envios que no vienen del propio panel."""
    if request.method in SAFE_METHODS:
        return
    if not same_origin(request):
        raise CSRFError()
    if request.url.path.startswith(TOKEN_EXEMPT):
        return
    expected = request.session.get(SESSION_KEY)
    sent = request.headers.get(HEADER)
    if not sent and 'form' in (request.headers.get('content-type') or ''):
        sent = (await request.form()).get(FIELD)
    if not expected or not sent or not hmac.compare_digest(str(sent), str(expected)):
        raise CSRFError()
