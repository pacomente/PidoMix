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


def with_meta_signup(response):
    parts = []
    for part in CSP.split('; '):
        name = part.split(' ', 1)[0]
        parts.append(f'{part} {META_SIGNUP[name]}' if name in META_SIGNUP else part)
    response.headers['Content-Security-Policy'] = '; '.join(parts) + ('; upgrade-insecure-requests' if settings.is_production else '')
    return response
