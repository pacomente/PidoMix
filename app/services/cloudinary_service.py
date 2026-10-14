import cloudinary
import cloudinary.uploader
from ..config import settings
import logging
import time

from .images import upload_transformation, white_background

log = logging.getLogger('pidomix.cloudinary')


def configured():
    return bool(settings.cloudinary_cloud_name and settings.cloudinary_api_key and settings.cloudinary_api_secret)


def _configure():
    if not configured():
        raise RuntimeError('Cloudinary no está configurado')
    cloudinary.config(cloud_name=settings.cloudinary_cloud_name, api_key=settings.cloudinary_api_key, api_secret=settings.cloudinary_api_secret, secure=True)


def upload(file, folder='pidomix', enhance=False):
    _configure()
    try:
        result = cloudinary.uploader.upload(file, folder=folder, resource_type='image', transformation=upload_transformation(folder, enhance))
    except RuntimeError:
        raise
    except Exception as exc:
        # Cualquier error real de Cloudinary (credenciales invalidas, red, cuota)
        # se convierte en RuntimeError para que los routers de admin.py, que ya
        # atrapan (ValueError, RuntimeError), lo muestren como mensaje claro en
        # vez de un 500 sin explicacion.
        raise RuntimeError(f'No se pudo subir la imagen a Cloudinary: {exc}') from exc
    return result.get('secure_url'), result.get('public_id')


def delete(public_id: str | None):
    if not public_id or not configured():
        return False
    _configure()
    try:
        result = cloudinary.uploader.destroy(public_id, resource_type='image', invalidate=True)
    except Exception:
        return False
    return result.get('result') in {'ok', 'not found'}


def with_white_background(url: str | None, wait_seconds: float = 25) -> str | None:
    """Pide a Cloudinary la foto con fondo blanco y devuelve esa URL si la pudo generar; si no, None.
    La primera vez Cloudinary la procesa (responde 423 mientras tanto): se espera un rato."""
    target = white_background(url)
    if not target or target == url:
        return None
    import httpx
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            r = httpx.get(target, timeout=15, follow_redirects=True)
        except httpx.HTTPError as exc:
            log.warning('No se pudo pedir la foto con fondo blanco: %s', exc)
            return None
        if r.status_code == 200 and r.headers.get('content-type', '').startswith('image/'):
            return target
        if r.status_code != 423 or time.monotonic() > deadline:
            log.warning('Cloudinary no hizo el fondo blanco (HTTP %s %s)', r.status_code, r.headers.get('x-cld-error', ''))
            return None
        time.sleep(2)


def list_resources(prefix: str = 'pidomix/') -> list[dict]:
    """Todas las imágenes guardadas bajo la carpeta (para limpiar las que ya no se usan)."""
    import cloudinary.api
    _configure()
    out, cursor = [], None
    while True:
        res = cloudinary.api.resources(type='upload', resource_type='image', prefix=prefix, max_results=500, next_cursor=cursor)
        out += res.get('resources', [])
        cursor = res.get('next_cursor')
        if not cursor:
            return out
