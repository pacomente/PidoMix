import cloudinary
import cloudinary.uploader
from ..config import settings
import logging
import time

from .images import WHITE_BG, upload_transformation, white_background

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


def upload_raw(data: bytes, folder: str, public_id: str) -> tuple[str, str]:
    """Archivo tal cual (modelos 3D): Cloudinary lo guarda y lo sirve sin tocarlo. public_id lleva la extension."""
    _configure()
    try:
        result = cloudinary.uploader.upload(data, folder=folder, public_id=public_id, resource_type='raw', overwrite=False)
    except Exception as exc:
        raise RuntimeError(f'No se pudo subir el archivo a Cloudinary: {exc}') from exc
    return result.get('secure_url'), result.get('public_id')


def delete(public_id: str | None, resource_type: str = 'image'):
    if not public_id or not configured():
        return False
    _configure()
    try:
        result = cloudinary.uploader.destroy(public_id, resource_type=resource_type, invalidate=True)
    except Exception:
        return False
    return result.get('result') in {'ok', 'not found'}


def with_white_background(url: str | None, public_id: str | None = None, wait_seconds: float = 40) -> tuple[str | None, str | None]:
    """Foto sin fondo, centrada sobre blanco. Devuelve (url, None) si Cloudinary la generó, o (None, motivo).

    1) Se le pide a Cloudinary que la genere ya (explicit + eager, firmado: anda aunque la cuenta tenga
       "transformaciones estrictas"). 2) Si eso no anda, se pide la URL y se espera mientras responde 423 (procesando)."""
    target = white_background(url)
    if not target or target == url:
        return None, 'La imagen no está en Cloudinary.'
    reason = None
    if public_id:
        try:
            _configure()
            res = cloudinary.uploader.explicit(public_id, type='upload', resource_type='image',
                                               eager=[WHITE_BG], eager_async=False)
            eager = (res.get('eager') or [{}])[0]
            if eager.get('secure_url'):
                return target, None  # misma transformacion que la URL: ya quedo generada
            reason = eager.get('reason') or eager.get('status')
        except Exception as exc:
            reason = str(exc)
    import httpx
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            r = httpx.get(target, timeout=20, follow_redirects=True)
        except httpx.HTTPError as exc:
            return None, reason or f'No se pudo pedir la foto a Cloudinary: {exc}'
        if r.status_code == 200 and r.headers.get('content-type', '').startswith('image/'):
            return target, None
        if r.status_code != 423 or time.monotonic() > deadline:
            why = r.headers.get('x-cld-error') or f'HTTP {r.status_code}'
            if r.status_code == 423:
                why = 'Cloudinary todavía la está procesando (probá de nuevo en un minuto).'
            log.warning('Cloudinary no hizo el fondo blanco: %s / %s', reason, why)
            return None, reason or why
        time.sleep(2)


def explain(reason: str | None) -> str:
    """El motivo de Cloudinary, en criollo."""
    r = (reason or '').lower()
    if 'add-on' in r or 'addon' in r or 'not enabled' in r or 'subscribe' in r or 'background_removal' in r and 'not' in r:
        return 'tu cuenta de Cloudinary no tiene activada la eliminación de fondo (Background Removal). Activala en Cloudinary → Add-ons.'
    if 'quota' in r or 'limit' in r or 'credits' in r:
        return 'se terminó el cupo de tu plan de Cloudinary para quitar fondos este mes.'
    if '401' in r or 'strict' in r or 'unauthorized' in r:
        return 'tu cuenta de Cloudinary no permite esa transformación (revisá "Strict transformations" en Settings → Security).'
    return reason or 'Cloudinary no respondió.'


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
