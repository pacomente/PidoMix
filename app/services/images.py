"""Imágenes livianas con Cloudinary.

- Al subir: la foto se achica a un máximo según para qué se usa y se recomprime (q_auto:good),
  así una foto de 12 MP del celular no ocupa 5 MB en el almacenamiento.
- Al mostrar: cdn() pide a Cloudinary la imagen al ancho en que se ve y en el formato más liviano
  que acepte el navegador o el celular (f_auto: AVIF/WebP), con calidad automática (q_auto).
Las URLs que no son de Cloudinary (o ya transformadas) se devuelven igual.
"""
import re

# ancho (en píxeles reales, ya contemplando pantallas de alta densidad) para cada uso
SIZES = {
    'thumb': 160,      # miniaturas del panel
    'logo': 256,       # logos de los comercios
    'category': 240,   # íconos de categorías
    'product': 720,    # fotos de productos (tarjetas, filas del menú, detalle en la app)
    'card': 1080,      # portadas en las tarjetas de comercios
    'cover': 1600,     # portada grande en la página del comercio
    'banner': 1600,    # banners del inicio
}

# tamaño máximo con el que se guarda cada tipo de imagen (lado más largo)
UPLOAD_MAX = {
    'pidomix/stores/logos': 512,
    'pidomix/stores/covers': 2000,
    'pidomix/products': 1600,
    'pidomix/categories': 800,
    'pidomix/banners': 2400,
}

_UPLOAD = '/image/upload/'
_ALREADY = re.compile(r'^(?:[a-z]{1,3}_[^/]+,?)+/')  # la URL ya trae transformaciones (w_..., f_..., etc.)


def cdn(url: str | None, size: str | int = 'product') -> str | None:
    if not url or 'res.cloudinary.com' not in url or _UPLOAD not in url:
        return url
    head, tail = url.split(_UPLOAD, 1)
    if _ALREADY.match(tail):
        return url
    width = size if isinstance(size, int) else SIZES.get(size, SIZES['product'])
    return f'{head}{_UPLOAD}f_auto,q_auto,c_limit,w_{width}/{tail}'


def upload_transformation(folder: str) -> list[dict]:
    side = UPLOAD_MAX.get(folder, 1600)
    return [{'width': side, 'height': side, 'crop': 'limit', 'quality': 'auto:good'}]
