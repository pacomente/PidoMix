import cloudinary
import cloudinary.uploader
from ..config import settings

def configured(): return bool(settings.cloudinary_cloud_name and settings.cloudinary_api_key and settings.cloudinary_api_secret)

def upload(file, folder="pidomix"):
    if not configured():
        raise RuntimeError("Cloudinary no está configurado")
    cloudinary.config(cloud_name=settings.cloudinary_cloud_name, api_key=settings.cloudinary_api_key, api_secret=settings.cloudinary_api_secret, secure=True)
    result=cloudinary.uploader.upload(file, folder=folder)
    return result.get("secure_url"), result.get("public_id")
