"""Panel del superadmin: Trappi Mandados por ciudad (el local interno, su Mercado Pago y cuántos mandados hubo)."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Order, OrderStatus
from ..services import audit, cities, errands, mercadopago, platform
from ..services.forms import form_int
from ..services.ratelimit import client_ip
from .admin import templates
from .logistics_admin import superadmin

router = APIRouter()


@router.get('/mandados', response_class=HTMLResponse)
def page(request: Request, db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse): return u
    rows = []
    for c in [None] + cities.all_cities(db):
        cid = c.id if c else None
        hub = errands.hub_of(db, cid)
        if c is None and hub is None:
            continue  # sin ciudad solo si ya se usó
        acct = mercadopago.account_for(db, hub.id) if hub else None
        counts = dict(db.execute(select(Order.status, func.count(Order.id)).where(Order.store_id == hub.id).group_by(Order.status)).all()) if hub else {}
        rows.append({'city': c.name if c else 'Sin ciudad', 'city_id': cid, 'hub': hub, 'mp': bool(acct and acct.status == 'connected'),
                     'on': errands.enabled(db, cid), 'delivered': counts.get(OrderStatus.ENTREGADO, 0), 'total': sum(counts.values())})
    return templates.TemplateResponse(request, 'admin/errands.html', {'user': u, 'rows': rows, 'mp_configured': mercadopago.configured(),
                                                                       'enabled': platform.get_all(db)['errands_enabled']})


@router.post('/mandados/crear')
async def create_hub(request: Request, db: Session = Depends(get_db)):
    """Crea el local interno de una ciudad (para poder conectarle Mercado Pago antes del primer mandado)."""
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse): return u
    form = await request.form()
    cid = form_int(form.get('city_id'))
    if cid is not None and cities.get(db, cid) is None:
        return RedirectResponse('/admin/mandados', 303)
    hub = errands.hub(db, cid)
    audit.log(db, 'errands.hub', 'store', hub.id, user=u, ip=client_ip(request))
    db.commit()
    return RedirectResponse('/admin/mandados', 303)
