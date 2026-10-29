"""Menú en 3D: "Ver en tu mesa" (realidad aumentada desde el navegador, sin instalar nada).

- Lo habilita el superadmin por comercio (stores.ar_enabled). Sin eso el local no ve la opción y el cliente no ve nada.
- El local escanea el plato con una app gratis (RealityScan, KIRI Engine, Polycam...) y sube el archivo:
  .glb (Android, PC y también iPhone: el visor lo convierte solo) y, si quiere, el .usdz que da la app para iPhone.
- Los archivos se revisan acá antes de guardarlos (formato real, tamaño, sin compresiones que piden bajar
  decodificadores de afuera, sin texturas o datos en otros sitios) y se guardan en Cloudinary tal cual ("raw").
- El visor (model-viewer de Google, licencia Apache 2.0) está copiado en /static/vendor/model-viewer: no se carga
  nada de otros sitios y solo se descarga cuando el cliente toca "3D".
"""
import io
import json
import secrets
import struct
import zipfile

from sqlalchemy.orm import Session

from ..models import Product, Store

MAX_BYTES = 10 * 1024 * 1024  # el limite de archivos "raw" del plan gratis de Cloudinary
FOLDER = 'pidomix/models'
# extensiones de glTF que necesitan bajar un decodificador de otro sitio (la pagina no lo permite)
NEEDS_DECODER = {'KHR_draco_mesh_compression': 'Draco', 'EXT_meshopt_compression': 'Meshopt', 'KHR_meshopt_compression': 'Meshopt',
                 'KHR_texture_basisu': 'KTX2/Basis'}
KINDS = {'glb': ('model_url', 'model_public_id'), 'usdz': ('model_ios_url', 'model_ios_public_id')}


class Model3DError(Exception):
    pass


def enabled(store: Store | None) -> bool:
    return bool(store is not None and store.ar_enabled)


def visible(product: Product) -> bool:
    """El cliente ve el boton 3D de este plato."""
    return bool(product.model_url and product.model_visible and enabled(product.store))


def _size(data: bytes) -> None:
    if not data:
        raise Model3DError('El archivo está vacío.')
    if len(data) > MAX_BYTES:
        raise Model3DError(f'El archivo pesa {len(data) / 1024 / 1024:.1f} MB y el máximo es 10 MB. '
                           'Exportalo de nuevo con menos calidad de textura (2K o 1K).')


def check_glb(data: bytes) -> dict:
    """Valida un .glb (glTF 2.0 binario, todo adentro del archivo). Devuelve un resumen."""
    _size(data)
    if len(data) < 20 or data[:4] != b'glTF':
        raise Model3DError('Ese archivo no es un modelo .glb. En la app de escaneo elegí exportar como "GLB" (o "glTF binario").')
    version, length = struct.unpack_from('<II', data, 4)
    if version != 2:
        raise Model3DError('El .glb tiene que ser glTF versión 2.')
    if length != len(data):
        raise Model3DError('El archivo .glb está incompleto o dañado. Exportalo y subilo de nuevo.')
    chunk_len, chunk_type = struct.unpack_from('<II', data, 12)
    if chunk_type != 0x4E4F534A or 20 + chunk_len > len(data):  # 'JSON'
        raise Model3DError('El archivo .glb está dañado. Exportalo y subilo de nuevo.')
    try:
        gltf = json.loads(data[20:20 + chunk_len].decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as exc:
        raise Model3DError('El archivo .glb está dañado. Exportalo y subilo de nuevo.') from exc
    if not isinstance(gltf, dict) or not gltf.get('meshes'):
        raise Model3DError('El .glb no tiene ningún objeto 3D adentro.')
    used = set(gltf.get('extensionsRequired') or []) | set(gltf.get('extensionsUsed') or [])
    for ext, name in NEEDS_DECODER.items():
        if ext in used:
            raise Model3DError(f'El .glb viene comprimido con {name}. Exportalo sin compresión (en la app: desactivá "{name}" o "compresión de malla").')
    for key in ('buffers', 'images'):
        for item in gltf.get(key) or []:
            uri = item.get('uri') if isinstance(item, dict) else None
            if uri and not uri.startswith('data:'):
                raise Model3DError('El modelo usa archivos aparte (texturas o datos). Exportalo como un solo .glb, con todo adentro.')
    return {'meshes': len(gltf['meshes']), 'textures': len(gltf.get('images') or [])}


def check_usdz(data: bytes) -> dict:
    """Valida un .usdz (el formato de iPhone: un zip sin comprimir que arranca con la escena .usdc/.usda)."""
    _size(data)
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        infos = z.infolist()
    except (zipfile.BadZipFile, ValueError) as exc:
        raise Model3DError('Ese archivo no es un modelo .usdz. En la app de escaneo elegí exportar como "USDZ".') from exc
    if not infos or not infos[0].filename.lower().endswith(('.usdc', '.usda')):
        raise Model3DError('Ese .usdz no tiene la escena 3D al principio. Exportalo de nuevo desde la app de escaneo.')
    for i in infos:
        name = i.filename
        if name.startswith('/') or '..' in name.split('/') or '\\' in name:
            raise Model3DError('El .usdz tiene archivos con nombres inválidos.')
        if i.compress_type != zipfile.ZIP_STORED:
            raise Model3DError('El .usdz está comprimido y el iPhone no lo abre así. Exportalo de nuevo desde la app de escaneo.')
    return {'files': len(infos)}


def save(db: Session, product: Product, kind: str, data: bytes) -> None:
    """Revisa y guarda el archivo del plato (reemplaza el anterior)."""
    from . import cloudinary_service
    if kind not in KINDS:
        raise Model3DError('Tipo de archivo desconocido.')
    (check_glb if kind == 'glb' else check_usdz)(data)
    if not cloudinary_service.configured():
        raise Model3DError('Falta configurar Cloudinary para guardar los modelos 3D.')
    try:
        url, pid = cloudinary_service.upload_raw(data, FOLDER, f'p{product.id}-{secrets.token_hex(5)}.{kind}')
    except RuntimeError as exc:
        raise Model3DError('No se pudo guardar el archivo. Probá de nuevo en un rato.') from exc
    url_attr, pid_attr = KINDS[kind]
    old = getattr(product, pid_attr)
    setattr(product, url_attr, url)
    setattr(product, pid_attr, pid)
    if old:
        cloudinary_service.delete(old, resource_type='raw')


def remove(db: Session, product: Product, kind: str | None = None) -> None:
    """Saca el modelo del plato (uno de los dos archivos, o los dos)."""
    from . import cloudinary_service
    for k in ([kind] if kind else list(KINDS)):
        url_attr, pid_attr = KINDS[k]
        if getattr(product, pid_attr):
            cloudinary_service.delete(getattr(product, pid_attr), resource_type='raw')
        setattr(product, url_attr, None)
        setattr(product, pid_attr, None)
