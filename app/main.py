from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from .config import settings
from .routers import public, admin, api

BASE = Path(__file__).resolve().parent
app = FastAPI(title="PidoMix", version="1.1.0", description="Marketplace local multi-tienda")
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, max_age=60*60*24*7, same_site="lax", https_only=False)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
app.include_router(public.router)
app.include_router(admin.router, prefix="/admin")
app.include_router(api.router, prefix="/api")
