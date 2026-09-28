import logging
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import text
from .config import settings
from .db import engine
from .routers import public, admin, api

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

app.mount('/static', StaticFiles(directory=BASE / 'static'), name='static')
app.include_router(public.router)
app.include_router(admin.router, prefix='/admin')
app.include_router(api.router, prefix='/api')


@app.exception_handler(404)
async def not_found_handler(request, exc):
    if request.url.path.startswith(('/api', '/static')):
        return JSONResponse({'error': 'not_found'}, status_code=404)
    return public.templates.TemplateResponse('public/404.html', {'request': request, 'message': 'No encontramos la página que buscás.'}, status_code=404)


@app.get('/health')
def health():
    try:
        with engine.connect() as connection:
            connection.execute(text('SELECT 1'))
        return {'status': 'ok', 'database': 'ok'}
    except Exception:
        logger.exception('Health check database failed')
        return JSONResponse({'status': 'degraded', 'database': 'error'}, status_code=503)
