import logging
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from .config import settings
from .db import engine
from .routers import public, admin, api, comandas, courier_api, mobile_api
from .services.monitoring import init_sentry
from .services.ratelimit import api_limiter, client_ip, web_limiter

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
logger = logging.getLogger('pidomix')
init_sentry()  # antes de crear la app, para que Sentry instrumente FastAPI
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
app.include_router(courier_api.router, prefix='/api/courier/v1', tags=['app repartidor'])
app.include_router(api.router, prefix='/api')


@app.exception_handler(404)
async def not_found_handler(request, exc):
    if request.url.path.startswith(('/api', '/static')):
        return JSONResponse({'error': 'not_found'}, status_code=404)
    return public.templates.TemplateResponse(request, 'public/404.html', {'message': 'No encontramos la página que buscás.'}, status_code=404)


FIELD_LABELS = {'price': 'Precio', 'previous_price': 'Precio anterior', 'stock': 'Stock', 'store_id': 'Tienda', 'discount_value': 'Valor del descuento',
                'percent': 'Porcentaje', 'name': 'Nombre', 'email': 'Email', 'password': 'Contraseña', 'code': 'Código', 'slug': 'Identificador'}


@app.exception_handler(courier_api.AuthError)
async def courier_auth_error(request: Request, exc: courier_api.AuthError):
    return JSONResponse({'ok': False, 'error': 'Tu sesión expiró. Volvé a entrar.'}, status_code=401)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """La API sigue respondiendo JSON (la app lo usa); en el panel y la web un formulario mal cargado
    muestra un mensaje entendible en vez del JSON crudo de FastAPI."""
    if request.url.path.startswith('/api'):
        return await request_validation_exception_handler(request, exc)
    fields = sorted({FIELD_LABELS.get(str(e['loc'][-1]), str(e['loc'][-1])) for e in exc.errors() if e.get('loc') and e['loc'][0] == 'body'})
    detail = f" Revisá: {', '.join(fields)}." if fields else ''
    message = f'Algún dato del formulario no es válido.{detail} Volvé atrás, corregilo y guardá de nuevo.'
    if not request.url.path.startswith('/admin'):
        try:
            return public.templates.TemplateResponse(request, 'public/404.html', {'message': message}, status_code=400)
        except Exception:
            pass
    return HTMLResponse('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                        '<div style="font-family:system-ui,sans-serif;max-width:520px;margin:15vh auto;padding:24px">'
                        f'<h2>No se pudo guardar</h2><p>{message}</p><p><a href="javascript:history.back()">← Volver al formulario</a></p></div>', status_code=400)


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


# Paginas que no cuentan para el limite general: archivos estaticos, salud y el panel (ya pide login)
RATE_LIMIT_EXEMPT = ('/static', '/health', '/admin', '/favicon')


@app.middleware('http')
async def rate_limit(request: Request, call_next):
    path = request.url.path
    if path.startswith(RATE_LIMIT_EXEMPT) and not (path == '/admin/login' and request.method == 'POST'):
        return await call_next(request)
    ip = client_ip(request)
    limiter = api_limiter if path.startswith('/api') else web_limiter
    if not limiter.check(ip):
        headers = {'Retry-After': str(limiter.retry_after(ip))}
        logger.warning('Rate limit: %s superó el límite en %s', ip, path)
        if path.startswith('/api'):
            return JSONResponse({'ok': False, 'error': 'Demasiadas consultas seguidas. Esperá un momento y probá de nuevo.'}, status_code=429, headers=headers)
        return HTMLResponse('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                            '<div style="font-family:system-ui,sans-serif;max-width:520px;margin:15vh auto;padding:24px">'
                            '<h2>Demasiadas visitas seguidas</h2><p>Esperá un minuto y volvé a cargar la página.</p></div>', status_code=429, headers=headers)
    return await call_next(request)


@app.get('/health/ip')
def health_ip(request: Request):
    """Diagnostico: que IP usa el servidor para los limites (solo muestra los datos de quien consulta)."""
    return {'ip': client_ip(request), 'via_cloudflare': bool(request.headers.get('cf-connecting-ip')),
            'proxy': request.client.host if request.client else None}


@app.get('/health')
def health():
    try:
        with engine.connect() as connection:
            connection.execute(text('SELECT 1'))
        return {'status': 'ok', 'database': 'ok'}
    except Exception:
        logger.exception('Health check database failed')
        return JSONResponse({'status': 'degraded', 'database': 'error'}, status_code=503)
