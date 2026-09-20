from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from .config import settings
from .routers import public, admin, api

BASE=Path(__file__).resolve().parent
app=FastAPI(title="PidoMix", version="1.0.0")
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, max_age=60*60*24*7)
app.mount("/static", StaticFiles(directory=BASE/"static"), name="static")
app.include_router(public.router)
app.include_router(admin.router, prefix="/admin")
app.include_router(api.router, prefix="/api")
