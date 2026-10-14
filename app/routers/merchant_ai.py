"""Panel: IA del local (recomendaciones con sus datos y textos con IA) y limpieza de imágenes en Cloudinary."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai import merchant
from ..db import get_db
from ..models import Banner, Category, Product, Role, Store
from ..services import cloudinary_service
from ..services.forms import form_int
from .admin import can_manage_store, guard, templates

router = APIRouter()


def _store(request: Request, db: Session, u) -> Store | None:
    if u.role == Role.SUPERADMIN:
        sid = form_int(request.query_params.get('store'))
        return db.get(Store, sid) if sid else None
    return db.get(Store, u.store_id) if u.store_id else None


@router.get('/ia', response_class=HTMLResponse)
def merchant_ai_page(request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    on = merchant.enabled(db)
    if not on and u.role != Role.SUPERADMIN:
        return RedirectResponse('/admin', 303)
    s = _store(request, db, u)
    stores = db.scalars(select(Store).order_by(Store.name)).all() if u.role == Role.SUPERADMIN else []
    data = merchant.insights(db, s) if (on and s) else None
    return templates.TemplateResponse(request, 'admin/merchant_ai.html', {'user': u, 'on': on, 's': s, 'stores': stores, 'data': data})


def _product(db: Session, u, product_id: int) -> Product | None:
    p = db.get(Product, product_id)
    return p if p and not p.deleted and can_manage_store(u, p.store_id) else None


@router.post('/ia/descripcion/{product_id}')
def write_description(product_id: int, request: Request, save: str = '', db: Session = Depends(get_db)):
    """Escribe la descripción con IA. Desde la lista de productos solo la propone (el local la revisa y guarda);
    desde "IA del local" (save=1) la guarda directamente."""
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    p = _product(db, u, product_id)
    if not p or not merchant.enabled(db):
        return JSONResponse({'ok': False, 'error': 'No disponible.'}, status_code=404)
    text = merchant.write_description(p, db.get(Store, p.store_id))
    if save == '1':
        p.description = text
        db.commit()
        return RedirectResponse('/admin/ia' + (f'?store={p.store_id}&' if u.role == Role.SUPERADMIN else '?') + 'ok=ai_desc', 303)
    return {'ok': True, 'text': text}


# ---------- imágenes que quedaron en Cloudinary sin usarse ----------

def _used_ids(db: Session) -> set[str]:
    ids = set()
    for col in (Store.logo_public_id, Store.cover_public_id, Product.image_public_id, Category.image_public_id, Banner.image_public_id):
        ids.update(x for x in db.scalars(select(col).where(col.is_not(None))).all() if x)
    return ids


def orphans(db: Session) -> list[dict]:
    from datetime import datetime, timedelta, timezone
    used = _used_ids(db)
    limit = datetime.now(timezone.utc) - timedelta(days=1)  # las recién subidas pueden estar guardándose
    out = []
    for r in cloudinary_service.list_resources('pidomix/'):
        created = datetime.fromisoformat(r.get('created_at', '').replace('Z', '+00:00')) if r.get('created_at') else limit
        if r.get('public_id') not in used and created < limit:
            out.append(r)
    return out


@router.get('/imagenes', response_class=HTMLResponse)
def images_page(request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin', 303)
    error, rows = None, []
    if not cloudinary_service.configured():
        error = 'Cloudinary no está configurado en Render.'
    else:
        try:
            rows = orphans(db)
        except Exception as exc:  # credenciales o red
            error = f'No se pudo leer Cloudinary: {exc}'
    size = sum(r.get('bytes', 0) for r in rows)
    return templates.TemplateResponse(request, 'admin/images_cleanup.html', {'user': u, 'rows': rows[:60], 'count': len(rows), 'mb': round(size / 1048576, 1), 'error': error,
                                                                             'test': request.session.pop('white_bg_test', None)})


def _sample_photo() -> bytes:
    """Una "foto" de prueba: un objeto sobre un fondo gris con manchas (como una foto de celular)."""
    import io
    from PIL import Image, ImageDraw
    img = Image.new('RGB', (900, 900), (120, 110, 100))
    d = ImageDraw.Draw(img)
    for i in range(0, 900, 60):
        d.rectangle([i, 0, i + 30, 900], fill=(100, 95, 90))
    d.ellipse([250, 250, 650, 650], fill=(230, 120, 30), outline=(120, 50, 10), width=12)
    d.rectangle([380, 150, 520, 300], fill=(60, 140, 60))
    out = io.BytesIO(); img.save(out, 'JPEG', quality=90)
    return out.getvalue()


@router.post('/imagenes/probar-fondo')
def white_bg_test(request: Request, db: Session = Depends(get_db)):
    """Sube una foto de prueba, intenta ponerle fondo blanco y muestra el resultado (o el motivo exacto)."""
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin', 303)
    result = {'ok': False, 'reason': None, 'url': None}
    try:
        url, pid = cloudinary_service.upload(_sample_photo(), 'pidomix/tests')
        white, reason = cloudinary_service.with_white_background(url, pid)
        result.update(ok=bool(white), url=white or url, reason=None if white else cloudinary_service.explain(reason), raw=None if white else (reason or '')[:300])
    except Exception as exc:
        result['reason'] = f'No se pudo subir la foto de prueba: {exc}'[:300]
    request.session['white_bg_test'] = result
    return RedirectResponse('/admin/imagenes', 303)


@router.post('/imagenes/limpiar')
def images_cleanup(request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    if u.role != Role.SUPERADMIN: return RedirectResponse('/admin', 303)
    n = 0
    for r in orphans(db):  # se vuelve a calcular: nunca se borra algo que se empezó a usar recién
        if cloudinary_service.delete(r.get('public_id')):
            n += 1
    return RedirectResponse(f'/admin/imagenes?ok=images_cleaned&n={n}', 303)
