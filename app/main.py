import logging
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from .config import settings
from .db import engine
from .routers import public, admin, api, comandas, mobile_api

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
logger = logging.getLogger('pidomix')
BASE = Path(__file__).resolve().parent
app = FastAPI(title='Trappi', version='1.2.0', description='Marketplace local multi-tienda')

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    max_age=60 * 60 * 24 * 7,
    same_site='lax',
    https_only=settings.is_production,
)
if settings.cors_origins:
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=['GET','POST','PUT','PATCH','DELETE'], allow_headers=['*'])

app.add_middleware(GZipMiddleware, minimum_size=1024)


class CachedStaticFiles(StaticFiles):
    """Los assets se piden con '?v=ASSET_VERSION' (cambia en cada deploy), asi que el
    navegador puede cachearlos un año sin riesgo de quedarse con una version vieja."""
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            versioned = b'v=' in scope.get('query_string', b'')
            response.headers['Cache-Control'] = 'public, max-age=31536000, immutable' if versioned else 'public, max-age=3600'
        return response


app.mount('/static', CachedStaticFiles(directory=BASE / 'static'), name='static')
app.include_router(public.router)
app.include_router(comandas.router, prefix='/admin/comandas')
app.include_router(admin.router, prefix='/admin')
app.include_router(mobile_api.router, prefix='/api/v1', tags=['app movil'])
app.include_router(api.router, prefix='/api')


@app.exception_handler(404)
async def not_found_handler(request, exc):
    if request.url.path.startswith(('/api', '/static')):
        return JSONResponse({'error': 'not_found'}, status_code=404)
    return public.templates.TemplateResponse(request, 'public/404.html', {'message': 'No encontramos la página que buscás.'}, status_code=404)


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    """Red de contencion: ningun error de una ruta deja ver la pantalla en blanco de
    'Internal Server Error'. Si es un problema de base de datos (la causa mas comun,
    normalmente una migracion que falta aplicar), lo dice explicitamente."""
    logger.exception('Error no manejado en %s', request.url.path)
    is_db_error = isinstance(exc, SQLAlchemyError)
    db_hint = ' Puede ser que falte aplicar una migración reciente en el servidor.' if is_db_error else ''
    if request.url.path.startswith('/api'):
        return JSONResponse({'ok': False, 'error': f'Ocurrió un error inesperado ({type(exc).__name__}).{db_hint}'}, status_code=500)
    if request.url.path.startswith('/admin'):
        try:
            return admin.templates.TemplateResponse(request, 'admin/login.html', {'error': f'Ocurrió un error inesperado.{db_hint} ({type(exc).__name__})'}, status_code=500)
        except Exception:
            pass
    message = f'Algo salió mal de nuestro lado.{db_hint} Probá de nuevo en un momento, o volvé al inicio.'
    try:
        return public.templates.TemplateResponse(request, 'public/404.html', {'message': message}, status_code=500)
    except Exception:
        return HTMLResponse(f'<h1>Error</h1><p>{message}</p><p><a href="/">Volver al inicio</a></p>', status_code=500)


@app.get('/health')
def health():
    try:
        with engine.connect() as connection:
            connection.execute(text('SELECT 1'))
        return {'status': 'ok', 'database': 'ok'}
    except Exception:
        logger.exception('Health check database failed')
        return JSONResponse({'status': 'degraded', 'database': 'error'}, status_code=503)
