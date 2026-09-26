import cloudinary
import cloudinary.uploader
from ..config import settings


def configured():
    return bool(settings.cloudinary_cloud_name and settings.cloudinary_api_key and settings.cloudinary_api_secret)


def _configure():
    if not configured():
        raise RuntimeError('Cloudinary no está configurado')
    cloudinary.config(cloud_name=settings.cloudinary_cloud_name, api_key=settings.cloudinary_api_key, api_secret=settings.cloudinary_api_secret, secure=True)


def upload(file, folder='pidomix'):
    _configure()
    result = cloudinary.uploader.upload(file, folder=folder, resource_type='image')
    return result.get('secure_url'), result.get('public_id')


def delete(public_id: str | None):
    if not public_id or not configured():
        return False
    _configure()
    result = cloudinary.uploader.destroy(public_id, resource_type='image', invalidate=True)
    return result.get('result') in {'ok', 'not found'}
