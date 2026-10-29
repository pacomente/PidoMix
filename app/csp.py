"""Content-Security-Policy del sitio (lo arma el middleware de app/main.py)."""
from .config import settings

CSP = '; '.join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline'",  # los scripts son propios; hay codigo inline en las plantillas
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' data: https://fonts.gstatic.com",
    "img-src 'self' data: blob: https:",  # fotos de Cloudinary, mapas
    "connect-src 'self' https:",  # buscador de direcciones (Nominatim)
    "worker-src 'self' blob:",
    "frame-src 'self'",
    "frame-ancestors 'self'",
    "base-uri 'self'",
    "object-src 'none'",
])

# Registro insertado de Meta (conectar el WhatsApp del local): solo en esa pagina se permite el SDK de Facebook.
META_SIGNUP = {'script-src': 'https://connect.facebook.net', 'frame-src': 'https://www.facebook.com https://web.facebook.com',
               'connect-src': 'https://graph.facebook.com https://www.facebook.com'}
# Visor 3D (menu en 3D): compila WebAssembly propio (no permite eval de JavaScript). Solo en las paginas que lo usan.
VIEWER_3D = {'script-src': "'wasm-unsafe-eval'"}


def with_extra(response, extra: dict):
    parts = []
    for part in CSP.split('; '):
        name = part.split(' ', 1)[0]
        parts.append(f'{part} {extra[name]}' if name in extra else part)
    response.headers['Content-Security-Policy'] = '; '.join(parts) + ('; upgrade-insecure-requests' if settings.is_production else '')
    return response


def with_meta_signup(response):
    return with_extra(response, META_SIGNUP)


def with_3d_viewer(response):
    return with_extra(response, VIEWER_3D)
