"""Trappi Repartidor en el navegador: trappi.com.ar/repartidor.

Es la misma app de repartidores (compilada para web con `npm run export:web` en driver/), para quien tiene iPhone y no la
instala desde una tienda: la abre en Safari y la agrega a la pantalla de inicio. Usa la misma API que la app (/api/courier/v1).
"""
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse

router = APIRouter()
ROOT = Path(__file__).resolve().parent.parent / 'driver_web'
HASHED = ('_expo/', 'assets/')  # nombres con hash: se pueden guardar en el celular para siempre


@router.get('/repartidor', include_in_schema=False)
def home():
    return RedirectResponse('/repartidor/', 308)


@router.get('/repartidor/{path:path}', include_in_schema=False)
def files(path: str):
    index = ROOT / 'index.html'
    if not index.is_file():
        return PlainTextResponse('La versión web de Trappi Repartidor todavía no está publicada.', status_code=404)
    target = (ROOT / path).resolve()
    if path and target.is_file() and target.is_relative_to(ROOT):
        cache = 'public, max-age=31536000, immutable' if path.startswith(HASHED) else 'public, max-age=3600'
        return FileResponse(target, headers={'Cache-Control': cache})
    # cualquier otra ruta es una pantalla de la app (login, menu, viaje...): la resuelve la app
    return FileResponse(index, media_type='text/html', headers={'Cache-Control': 'no-cache'})
