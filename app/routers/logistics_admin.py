"""Panel de logistica y finanzas de Trappi.

Superadmin
  /admin/logistica                    resumen
  /admin/logistica/zonas              zonas de la flota en el mapa (radio o poligono) con su tarifa por km
  /admin/logistica/configuracion      flota, costo operativo, pago a repartidores, efectivo
  /admin/logistica/rentabilidad       envio cobrado vs pago al cadete y costo operativo (por pedido y por zona)
  /admin/configuracion/comisiones     comision por plan y por comercio
  /admin/finanzas                     saldos de comercios y repartidores
  /admin/finanzas/rendiciones         efectivo que rinden los repartidores
  /admin/finanzas/liquidaciones       a comercios y a repartidores
  /admin/finanzas/pagos               pagos online (y devoluciones)
  /admin/finanzas/auditoria           registro de cambios sensibles
  /admin/repartidores/{id}/pago       datos de cobro, limite de efectivo
Comercio
  /admin/pagos                        Mercado Pago, saldo, movimientos y liquidaciones; flota o entrega propia
"""
import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from ..config import settings
from ..db import get_db
from ..models import (AuditLog, CashRemittance, Courier, CourierPayoutAccount, CourierSettlement, LedgerEntry, LogisticsZone, LogisticsZoneVersion,
                      MercadoPagoAccount, MerchantSettlement, Order, OrderStatus, Payment, PaymentEvent, Role, Store)
from ..services import audit, finance, logistics, mercadopago, plans
from ..services import platform as platform_settings
from ..services.forms import form_float, form_int
from ..services.ratelimit import client_ip
from ..services.store_hours import local_day_start_utc, to_local
from . import payments_api
from .admin import form_data, guard, settings_form, settings_store, templates

router = APIRouter()
logger = logging.getLogger('trappi.mercadopago')
templates.env.globals['finance'] = finance


def _fromjson(value):
    try:
        return json.loads(value or '{}')
    except ValueError:
        return {}


templates.env.filters['fromjson'] = _fromjson
templates.env.globals['logistics'] = logistics
templates.env.globals.setdefault('to_local', to_local)


def superadmin(request: Request, db: Session):
    u = guard(request, db)
    if isinstance(u, RedirectResponse):
        return u
    return u if u.role == Role.SUPERADMIN else RedirectResponse('/admin/pagos', 303)


def flash(request: Request, kind: str, text: str) -> None:
    request.session['finance_flash'] = [kind, text]


def pop_flash(request: Request):
    return request.session.pop('finance_flash', None)


def go(path: str) -> RedirectResponse:
    return RedirectResponse(path, 303)


def dec(value, default=None):
    number = form_float(value, None)
    return default if number is None else Decimal(str(number))


# ==================== logistica ====================

@router.get('/logistica', response_class=HTMLResponse)
def logistics_home(request: Request, db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse): return u
    zones = logistics.zones(db, include_inactive=True)
    fleet_stores = db.scalars(select(Store).where(Store.logistics == 'trappi').order_by(Store.name)).all()
    since = local_day_start_utc(29)
    agg = db.execute(select(func.count(Order.id), func.coalesce(func.sum(Order.shipping), 0), func.coalesce(func.sum(Order.courier_pay), 0),
                            func.coalesce(func.sum(Order.operating_cost), 0)).where(Order.delivery_mode == 'trappi', Order.status == OrderStatus.ENTREGADO,
                                                                                    Order.created_at >= since)).one()
    couriers = db.scalars(select(Courier).where(Courier.store_id.is_(None), Courier.active.is_(True)).order_by(Courier.name)).all()
    cfg = platform_settings.get_all(db)
    return templates.TemplateResponse(request, 'admin/logistics_home.html', {
        'user': u, 'zones': zones, 'fleet_stores': fleet_stores, 'agg': agg, 'couriers': couriers, 'cfg': cfg,
        'boxes': {c.id: finance.courier_box(db, c) for c in couriers}, 'fleet_open': logistics.fleet_open(cfg)})


def zone_json(z: LogisticsZone) -> dict:
    return {'id': z.id, 'name': z.name, 'color': z.color, 'kind': z.kind, 'active': z.active, 'priority': z.priority,
            'center': [z.center_lat, z.center_lng] if z.center_lat is not None else None, 'radius_km': z.radius_km,
            'polygon': logistics.polygon_points(z), 'max_km': z.max_km}


@router.get('/logistica/zonas', response_class=HTMLResponse)
def zones_page(request: Request, edit: int = 0, db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse): return u
    zones = logistics.zones(db, include_inactive=True)
    stores = db.scalars(select(Store).where(Store.lat.is_not(None)).order_by(Store.name)).all()
    inside = {z.id: [s for s in stores if logistics.contains(z, s.lat, s.lng)] for z in zones}
    current = next((z for z in zones if z.id == edit), None)
    history = db.scalars(select(LogisticsZoneVersion).options(joinedload(LogisticsZoneVersion.user)).where(LogisticsZoneVersion.zone_id == edit)
                         .order_by(LogisticsZoneVersion.id.desc()).limit(30)).all() if current else []
    center = [float(x) for x in settings.map_default_center.split(',')]
    return templates.TemplateResponse(request, 'admin/logistics_zones.html', {
        'user': u, 'zones': zones, 'zones_json': json.dumps([zone_json(z) for z in zones]), 'stores_json': json.dumps([{'name': s.name, 'lat': s.lat, 'lng': s.lng} for s in stores]),
        'inside': inside, 'overlaps': logistics.overlaps(zones), 'current': current, 'history': [(h, json.loads(h.data)) for h in history],
        'center': center, 'tiles': platform_settings.get_all(db)['web_tiles_url'], 'flash': pop_flash(request)})


def _apply_zone(z: LogisticsZone, form) -> None:
    def f(name, default=None):
        return form_float(form.get(name), default)
    z.name = (form.get('name') or '').strip()[:120] or 'Zona'
    z.description = (form.get('description') or '').strip() or None
    z.active = form.get('active') in ('1', 'on', 'true')
    color = (form.get('color') or '#6C2BD9').strip()
    z.color = color if len(color) in (4, 7) and color.startswith('#') else '#6C2BD9'
    z.priority = form_int(form.get('priority'), 0) or 0
    z.kind = 'polygon' if form.get('kind') == 'polygon' else 'radius'
    if z.kind == 'polygon':
        try:
            pts = [[float(p[0]), float(p[1])] for p in json.loads(form.get('polygon') or '[]')]
        except (ValueError, TypeError, IndexError):
            pts = []
        if len(pts) < 3:
            raise ValueError('El polígono necesita al menos 3 puntos (tocá el mapa para agregarlos).')
        if any(not (-90 <= a <= 90 and -180 <= b <= 180) for a, b in pts):
            raise ValueError('Hay puntos fuera del mapa.')
        z.polygon = json.dumps(pts)
        z.center_lat = sum(p[0] for p in pts) / len(pts)
        z.center_lng = sum(p[1] for p in pts) / len(pts)
        z.radius_km = None
    else:
        def coord(name):  # coordenadas: siempre con punto decimal (no son importes)
            try:
                return float(str(form.get(name) or '').replace(',', '.'))
            except ValueError:
                return None
        lat, lng, radius = coord('center_lat'), coord('center_lng'), f('radius_km')
        if lat is not None and not (-90 <= lat <= 90 and -180 <= (lng or 0) <= 180):
            raise ValueError('El centro está fuera del mapa.')
        if lat is None or lng is None or not radius or radius <= 0:
            raise ValueError('Marcá el centro en el mapa y poné un radio mayor a 0.')
        if radius > 100:
            raise ValueError('El radio es demasiado grande (máximo 100 km).')
        z.center_lat, z.center_lng, z.radius_km, z.polygon = lat, lng, radius, None
    max_km = f('max_km')
    z.max_km = max_km if max_km and max_km > 0 else None
    for name in ('base_fee', 'per_km', 'min_fee', 'rounding'):
        value = f(name, 0) or 0
        if value < 0:
            raise ValueError('Las tarifas no pueden ser negativas.')
        setattr(z, name, Decimal(str(value)))
    z.included_km = max(0.0, f('included_km', 0) or 0)
    max_fee = f('max_fee')
    z.max_fee = Decimal(str(max_fee)) if max_fee and max_fee > 0 else None
    if z.max_fee is not None and z.max_fee < z.min_fee:
        raise ValueError('El máximo no puede ser menor que el mínimo.')
    days = ''.join(d for d in '0123456' if form.get(f'day{d}'))
    z.days = days or '0123456'
    start, end = (form.get('start_time') or '').strip()[:5], (form.get('end_time') or '').strip()[:5]
    z.start_time, z.end_time = (start, end) if start and end else (None, None)


@router.post('/logistica/zonas')
def zone_save(request: Request, form=Depends(form_data), db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse): return u
    zid = form_int(form.get('id'))
    z = db.get(LogisticsZone, zid) if zid else LogisticsZone()
    if zid and (not z or z.deleted):
        return go('/admin/logistica/zonas')
    before = logistics.zone_data(z) if zid else None
    try:
        _apply_zone(z, form)
    except ValueError as exc:
        db.rollback()
        flash(request, 'error', str(exc))
        return go('/admin/logistica/zonas' + (f'?edit={zid}' if zid else ''))
    if not zid:
        db.add(z)
    db.flush()
    logistics.record_version(db, z, u)
    audit.log(db, 'zone.update' if zid else 'zone.create', 'logistics_zone', z.id, user=u, old=before, new=logistics.zone_data(z),
              amount_old=Decimal(before['per_km']) if before else None, amount_new=z.per_km, ip=client_ip(request))
    db.commit()
    logistics.invalidate()
    flash(request, 'ok', f'Zona "{z.name}" guardada. Rige para los pedidos nuevos; los anteriores conservan su tarifa.')
    return go(f'/admin/logistica/zonas?edit={z.id}')


@router.post('/logistica/zonas/{zone_id}/estado')
def zone_toggle(zone_id: int, request: Request, action: str = Form(...), db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse): return u
    z = db.get(LogisticsZone, zone_id)
    if not z or z.deleted:
        return go('/admin/logistica/zonas')
    before = logistics.zone_data(z)
    if action == 'eliminar':
        z.deleted, z.active = True, False  # baja logica: los pedidos viejos la referencian
    else:
        z.active = not z.active
    logistics.record_version(db, z, u)
    audit.log(db, f'zone.{action}', 'logistics_zone', z.id, user=u, old=before, new=logistics.zone_data(z), ip=client_ip(request))
    db.commit()
    logistics.invalidate()
    flash(request, 'ok', 'Zona eliminada.' if action == 'eliminar' else ('Zona activada.' if z.active else 'Zona desactivada.'))
    return go('/admin/logistica/zonas')


@router.get('/logistica/configuracion', response_class=HTMLResponse)
def logistics_config(request: Request, db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse): return u
    return settings_form(request, db, u, platform_settings.LOGISTICS_SECTIONS, '/admin/logistica/configuracion', 'Logística · configuración',
                         'Tarifas de envío por zona en <a href="/admin/logistica/zonas">Zonas</a>. "Cuánto gana el repartidor" se elige en '
                         '<a href="/admin/settings#sec-couriers">Configuración → Repartidores</a> (elegí "Fórmula de la flota" para usar lo de acá).')


@router.post('/logistica/configuracion')
def logistics_config_save(request: Request, form=Depends(form_data), db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse): return u
    settings_store(request, db, u, form, platform_settings.LOGISTICS_SECTIONS)
    return go('/admin/logistica/configuracion?ok=1')


@router.get('/logistica/rentabilidad', response_class=HTMLResponse)
def profitability(request: Request, days: int = 30, db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse): return u
    days = days if days in (7, 30, 90) else 30
    rows = db.scalars(select(Order).options(joinedload(Order.store), joinedload(Order.courier)).where(
        Order.delivery_mode == 'trappi', Order.status == OrderStatus.ENTREGADO, Order.created_at >= local_day_start_utc(days - 1))
        .order_by(Order.created_at.desc()).limit(500)).all()
    lines, zones = [], {}
    for o in rows:
        b = plans.breakdown(o)
        minutes = None
        picked, delivered = o.status_time(OrderStatus.EN_CAMINO), o.status_time(OrderStatus.ENTREGADO)
        if picked and delivered:
            minutes = round((delivered - picked).total_seconds() / 60)
        lines.append({'o': o, 'b': b, 'minutes': minutes})
        z = zones.setdefault(o.zone_name or 'Sin zona', {'orders': 0, 'charged': Decimal('0'), 'courier': Decimal('0'), 'operating': Decimal('0'), 'margin': Decimal('0'), 'km': 0.0})
        z['orders'] += 1
        z['charged'] += b['fee_customer'] + b['fee_merchant']
        z['courier'] += b['courier_pay'] or Decimal('0')
        z['operating'] += b['operating_cost']
        z['margin'] += b['logistics_margin']
        z['km'] += o.route_km or 0
    return templates.TemplateResponse(request, 'admin/logistics_profit.html', {'user': u, 'lines': lines, 'zones': zones, 'days': days})


# ==================== comisiones ====================

@router.get('/configuracion/comisiones', response_class=HTMLResponse)
def commissions_page(request: Request, db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse): return u
    stores = db.scalars(select(Store).order_by(Store.name)).all()
    return settings_form(request, db, u, platform_settings.COMMISSION_SECTIONS, '/admin/configuracion/comisiones', 'Comisiones',
                         'Comisión = % sobre los productos (sin el envío) + monto fijo, con mínimo y máximo. El % de Trappi Delivery está en '
                         '<a href="/admin/settings#sec-commercial">Configuración comercial</a>. Cada pedido guarda la regla con que se hizo.',
                         stores=stores, terms={s.id: plans.commission_terms(db, s) for s in stores}, commission_overrides=True)


@router.post('/configuracion/comisiones')
def commissions_save(request: Request, form=Depends(form_data), db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse): return u
    settings_store(request, db, u, form, platform_settings.COMMISSION_SECTIONS)
    return go('/admin/configuracion/comisiones?ok=1')


@router.post('/configuracion/comisiones/{store_id}')
def store_commission_save(store_id: int, request: Request, rate: str = Form(''), fixed: str = Form(''), minimum: str = Form(''), maximum: str = Form(''),
                          reason: str = Form(''), db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse): return u
    s = db.get(Store, store_id)
    if not s:
        return go('/admin/configuracion/comisiones')
    before = plans.commission_terms(db, s)
    r = dec(rate)
    if r is not None and not (0 <= r <= 100):
        return go('/admin/configuracion/comisiones?error=1')
    if r is not None:
        s.commission_rate = r
    s.commission_fixed, s.commission_min, s.commission_max = dec(fixed), dec(minimum), dec(maximum)
    after = plans.commission_terms(db, s)
    audit.log(db, 'commission.update', 'store', s.id, user=u, old=before, new=after, amount_old=Decimal(before['rate']), amount_new=Decimal(after['rate']),
              reason=reason, ip=client_ip(request))
    db.commit()
    return go('/admin/configuracion/comisiones?ok=1#comercios')


# ==================== finanzas ====================

@router.get('/finanzas', response_class=HTMLResponse)
def finance_home(request: Request, db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse): return u
    stores = db.scalars(select(Store).order_by(Store.name)).all()
    couriers = db.scalars(select(Courier).where(Courier.store_id.is_(None)).order_by(Courier.name)).all()
    balances = {s.id: finance.merchant_balance(db, s.id) for s in stores}
    boxes = {c.id: finance.courier_box(db, c) for c in couriers}
    online = db.execute(select(Payment.status, func.count(Payment.id), func.coalesce(func.sum(Payment.amount), 0), func.coalesce(func.sum(Payment.marketplace_fee), 0))
                        .group_by(Payment.status)).all()
    totals = {'merchant_owed': sum((b['pending'] for b in balances.values() if b['pending'] > 0), Decimal('0')),
              'merchant_owes': -sum((b['pending'] for b in balances.values() if b['pending'] < 0), Decimal('0')),
              'cash_pending': sum((b['pending'] for b in boxes.values()), Decimal('0')),
              'earnings_pending': sum((b['earnings_pending'] for b in boxes.values()), Decimal('0'))}
    return templates.TemplateResponse(request, 'admin/finance_home.html', {'user': u, 'stores': stores, 'couriers': couriers, 'balances': balances,
                                                                           'boxes': boxes, 'online': online, 'totals': totals, 'flash': pop_flash(request)})


@router.get('/finanzas/rendiciones', response_class=HTMLResponse)
def remittances_page(request: Request, courier: int = 0, db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse): return u
    couriers = db.scalars(select(Courier).where(Courier.store_id.is_(None)).order_by(Courier.name)).all()
    selected = next((c for c in couriers if c.id == courier), None)
    pending = db.scalars(select(LedgerEntry).options(joinedload(LedgerEntry.order)).where(LedgerEntry.account == 'courier_cash', LedgerEntry.courier_id == selected.id,
                                                                                          LedgerEntry.settled.is_(False)).order_by(LedgerEntry.id)).all() if selected else []
    rows = db.scalars(select(CashRemittance).options(joinedload(CashRemittance.courier), joinedload(CashRemittance.user)).order_by(CashRemittance.id.desc()).limit(100)).all()
    return templates.TemplateResponse(request, 'admin/finance_remittances.html', {'user': u, 'couriers': couriers, 'selected': selected, 'pending': pending,
                                                                                 'rows': rows, 'box': finance.courier_box(db, selected) if selected else None,
                                                                                 'flash': pop_flash(request)})


@router.post('/finanzas/rendiciones')
def remittance_create(request: Request, form=Depends(form_data), db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse): return u
    c = db.get(Courier, form_int(form.get('courier_id')) or 0)
    if not c:
        return go('/admin/finanzas/rendiciones')
    order_ids = [int(x) for x in form.getlist('order_ids') if str(x).isdigit()] if hasattr(form, 'getlist') else []
    received = dec(form.get('received'))
    if received is None:
        flash(request, 'error', 'Poné el importe recibido.')
        return go(f'/admin/finanzas/rendiciones?courier={c.id}')
    try:
        rem = finance.create_remittance(db, c, received, order_ids=order_ids or None, receipt=form.get('receipt') or '', notes=form.get('notes') or '',
                                        user=u, ip=client_ip(request))
    except finance.FinanceError as exc:
        db.rollback()
        flash(request, 'error', str(exc))
        return go(f'/admin/finanzas/rendiciones?courier={c.id}')
    db.commit()
    diff = rem.difference
    flash(request, 'ok', f'Rendición #{rem.id} registrada.' + ('' if diff == 0 else (f' Faltan ${-diff:,.0f}: siguen pendientes.' if diff < 0 else f' Sobran ${diff:,.0f}: quedan a favor del repartidor.')).replace(',', '.'))
    return go(f'/admin/finanzas/rendiciones?courier={c.id}')


@router.get('/finanzas/liquidaciones', response_class=HTMLResponse)
def settlements_page(request: Request, db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse): return u
    merchant = db.scalars(select(MerchantSettlement).options(joinedload(MerchantSettlement.store)).order_by(MerchantSettlement.id.desc()).limit(100)).all()
    courier = db.scalars(select(CourierSettlement).options(joinedload(CourierSettlement.courier)).order_by(CourierSettlement.id.desc()).limit(100)).all()
    couriers = db.scalars(select(Courier).where(Courier.store_id.is_(None)).order_by(Courier.name)).all()
    return templates.TemplateResponse(request, 'admin/finance_settlements.html', {
        'user': u, 'merchant': merchant, 'courier': courier, 'couriers': couriers, 'boxes': {c.id: finance.courier_box(db, c) for c in couriers},
        'statuses': finance.SETTLEMENT_STATUSES, 'flash': pop_flash(request)})


@router.post('/finanzas/liquidaciones/comercios')
def merchant_settlements_generate(request: Request, store_id: str = Form(''), db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse): return u
    sid = form_int(store_id)
    if sid:
        st = finance.create_merchant_settlement(db, sid, user=u, ip=client_ip(request))
        made = [st] if st else []
    else:
        made = finance.generate_merchant_settlements(db, user=u, ip=client_ip(request))
    db.commit()
    flash(request, 'ok', f'{len(made)} liquidación(es) generada(s).' if made else 'No había saldos pendientes para liquidar.')
    return go('/admin/finanzas/liquidaciones')


@router.post('/finanzas/liquidaciones/repartidores')
def courier_settlement_create(request: Request, courier_id: str = Form(...), bonuses: str = Form(''), adjustments: str = Form(''), notes: str = Form(''),
                              db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse): return u
    c = db.get(Courier, form_int(courier_id) or 0)
    if not c:
        return go('/admin/finanzas/liquidaciones')
    try:
        st = finance.create_courier_settlement(db, c, bonuses=dec(bonuses, 0), adjustments=dec(adjustments, 0), notes=notes, user=u, ip=client_ip(request))
    except finance.FinanceError as exc:
        db.rollback()
        flash(request, 'error', str(exc))
        return go('/admin/finanzas/liquidaciones')
    db.commit()
    flash(request, 'ok', f'Liquidación #{st.id} de {c.name} creada por ${st.total:,.0f}.'.replace(',', '.') + ('' if st.account_masked else ' Ojo: no tiene datos de cobro cargados.'))
    return go('/admin/finanzas/liquidaciones')


@router.post('/finanzas/liquidaciones/{kind}/{settlement_id}')
def settlement_status(kind: str, settlement_id: int, request: Request, status: str = Form(...), receipt: str = Form(''), notes: str = Form(''),
                      db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse): return u
    model = MerchantSettlement if kind == 'comercio' else CourierSettlement
    st = db.get(model, settlement_id)
    if not st:
        return go('/admin/finanzas/liquidaciones')
    try:
        finance.set_settlement_status(db, st, status, receipt=receipt, notes=notes, user=u, ip=client_ip(request))
    except finance.FinanceError as exc:
        db.rollback()
        flash(request, 'error', str(exc))
        return go('/admin/finanzas/liquidaciones')
    db.commit()
    flash(request, 'ok', f'Liquidación #{st.id}: {finance.SETTLEMENT_STATUSES[status].lower()}.')
    return go('/admin/finanzas/liquidaciones')


@router.post('/finanzas/ajustes')
def adjustment_create(request: Request, account: str = Form(...), target_id: str = Form(...), amount: str = Form(...), reason: str = Form(''),
                      back: str = Form('/admin/finanzas'), db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse): return u
    tid = form_int(target_id) or 0
    try:
        finance.adjust(db, account, dec(amount, 0), reason, store_id=tid if account == 'merchant' else None,
                       courier_id=tid if account != 'merchant' else None, user=u, ip=client_ip(request))
    except finance.FinanceError as exc:
        db.rollback()
        flash(request, 'error', str(exc))
        return go(back if back.startswith('/admin') else '/admin/finanzas')
    db.commit()
    flash(request, 'ok', 'Ajuste registrado.')
    return go(back if back.startswith('/admin') else '/admin/finanzas')


@router.get('/finanzas/pagos', response_class=HTMLResponse)
def payments_page(request: Request, db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse): return u
    rows = db.scalars(select(Payment).options(joinedload(Payment.order).joinedload(Order.store)).order_by(Payment.id.desc()).limit(200)).all()
    return templates.TemplateResponse(request, 'admin/finance_payments.html', {'user': u, 'rows': rows, 'flash': pop_flash(request),
                                                                              'mp_configured': mercadopago.configured(), 'sandbox': settings.mercadopago_sandbox})


@router.post('/finanzas/pagos/{payment_id}/devolver')
def payment_refund(payment_id: int, request: Request, amount: str = Form(''), reason: str = Form(''), db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse): return u
    p = db.get(Payment, payment_id)
    if not p:
        return go('/admin/finanzas/pagos')
    if not reason.strip():
        flash(request, 'error', 'Toda devolución necesita un motivo.')
        return go('/admin/finanzas/pagos')
    value = dec(amount)
    try:
        result = mercadopago.refund(db, p, value, user=u, reason=reason, ip=client_ip(request))
        db.commit()
    except mercadopago.MPError as exc:
        db.rollback()
        flash(request, 'error', str(exc))
        return go('/admin/finanzas/pagos')
    flash(request, 'ok', f'Devolución enviada a Mercado Pago ({result}).')
    return go('/admin/finanzas/pagos')


@router.post('/finanzas/pagos/{payment_id}/sincronizar')
def payment_sync(payment_id: int, request: Request, db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse): return u
    p = db.get(Payment, payment_id)
    if p:
        try:
            result = mercadopago.sync_payment(db, p.provider_payment_id) if p.provider_payment_id else mercadopago.reconcile(db, p.order)
            db.commit()
            flash(request, 'ok', f'Estado consultado a Mercado Pago: {result or "sin pagos todavía"}.')
        except mercadopago.MPError as exc:
            db.rollback()
            flash(request, 'error', str(exc))
    return go('/admin/finanzas/pagos')


@router.get('/finanzas/auditoria', response_class=HTMLResponse)
def audit_page(request: Request, entity: str = '', db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse): return u
    q = select(AuditLog).options(joinedload(AuditLog.user)).order_by(AuditLog.id.desc()).limit(300)
    if entity:
        q = q.where(AuditLog.entity == entity)
    entities = db.scalars(select(AuditLog.entity).distinct()).all()
    return templates.TemplateResponse(request, 'admin/finance_audit.html', {'user': u, 'rows': db.scalars(q).all(), 'entity': entity, 'entities': sorted(entities)})


# ==================== repartidores: datos de cobro y efectivo ====================

@router.get('/repartidores/{courier_id}/pago', response_class=HTMLResponse)
def courier_payout_page(courier_id: int, request: Request, db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse): return u
    c = db.get(Courier, courier_id)
    if not c:
        return go('/admin/repartidores')
    versions = db.scalars(select(CourierPayoutAccount).where(CourierPayoutAccount.courier_id == c.id).order_by(CourierPayoutAccount.id.desc())).all()
    trips = db.scalars(select(Order).options(joinedload(Order.store)).where(Order.courier_id == c.id, Order.status == OrderStatus.ENTREGADO)
                       .order_by(Order.id.desc()).limit(30)).all()
    return templates.TemplateResponse(request, 'admin/courier_payout.html', {
        'user': u, 'c': c, 'current': finance.payout_account(db, c.id), 'versions': versions, 'box': finance.courier_box(db, c),
        'movements': finance.movements(db, 'courier_earnings', courier_id=c.id, limit=50) + finance.movements(db, 'courier_cash', courier_id=c.id, limit=50),
        'trips': trips, 'default_limit': platform_settings.get_all(db)['courier_cash_limit'], 'flash': pop_flash(request)})


@router.post('/repartidores/{courier_id}/pago')
def courier_payout_save(courier_id: int, request: Request, holder: str = Form(''), provider: str = Form(''), cbu: str = Form(''), cvu: str = Form(''),
                        alias: str = Form(''), account_type: str = Form(''), verification: str = Form('pendiente'), reason: str = Form(''),
                        db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse): return u
    c = db.get(Courier, courier_id)
    if not c:
        return go('/admin/repartidores')
    try:
        finance.save_payout_account(db, c, holder=holder, provider=provider, cbu=cbu, cvu=cvu, alias=alias, account_type=account_type,
                                    verification=verification, user=u, ip=client_ip(request), reason=reason)
    except finance.FinanceError as exc:
        db.rollback()
        flash(request, 'error', str(exc))
        return go(f'/admin/repartidores/{c.id}/pago')
    db.commit()
    flash(request, 'ok', 'Datos de cobro guardados (la versión anterior queda en el historial).')
    return go(f'/admin/repartidores/{c.id}/pago')


@router.post('/repartidores/{courier_id}/efectivo')
def courier_cash_rules(courier_id: int, request: Request, cash_limit: str = Form(''), cash_orders_enabled: str = Form(''), online_orders_enabled: str = Form(''),
                       db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse): return u
    c = db.get(Courier, courier_id)
    if not c:
        return go('/admin/repartidores')
    before = {'limit': str(c.cash_limit) if c.cash_limit is not None else None, 'cash': c.cash_orders_enabled, 'online': c.online_orders_enabled}
    limit = dec(cash_limit)
    c.cash_limit = limit if limit is not None and limit >= 0 else None
    c.cash_orders_enabled, c.online_orders_enabled = bool(cash_orders_enabled), bool(online_orders_enabled)
    audit.log(db, 'courier.cash_rules', 'courier', c.id, user=u, old=before,
              new={'limit': str(c.cash_limit) if c.cash_limit is not None else None, 'cash': c.cash_orders_enabled, 'online': c.online_orders_enabled},
              amount_old=Decimal(before['limit']) if before['limit'] else None, amount_new=c.cash_limit, ip=client_ip(request))
    db.commit()
    flash(request, 'ok', 'Reglas de efectivo guardadas.')
    return go(f'/admin/repartidores/{c.id}/pago')


# ==================== comercio: logistica y envio (desde la ficha) ====================

@router.post('/comercios/{store_id}/logistica')
def store_logistics_save(store_id: int, request: Request, fleet_enabled: str = Form(''), delivery_fee_payer: str = Form(''), fee_share_mode: str = Form(''),
                         fee_share_value: str = Form(''), db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse): return u
    s = db.get(Store, store_id)
    if not s:
        return go('/admin/comercios')
    before = {'fleet': s.fleet_enabled, 'payer': s.delivery_fee_payer, 'mode': s.fee_share_mode, 'value': str(s.fee_share_value) if s.fee_share_value is not None else None}
    s.fleet_enabled = bool(fleet_enabled) or s.plan == plans.DELIVERY  # en Trappi Delivery la flota viene con el plan
    s.delivery_fee_payer = delivery_fee_payer if delivery_fee_payer in logistics.PAYERS else None
    s.fee_share_mode = fee_share_mode if fee_share_mode in ('percent', 'amount') else None
    s.fee_share_value = dec(fee_share_value)
    if s.logistics in ('mixta', 'trappi') and not s.fleet_enabled:
        s.logistics = 'propia'  # sin permiso de flota entrega con sus cadetes
    audit.log(db, 'store.logistics', 'store', s.id, user=u, old=before,
              new={'fleet': s.fleet_enabled, 'payer': s.delivery_fee_payer, 'mode': s.fee_share_mode, 'value': str(s.fee_share_value) if s.fee_share_value is not None else None},
              ip=client_ip(request))
    db.commit()
    request.session['commercial_flash'] = ['ok', 'Logística y envío guardados.']
    return go(f'/admin/comercios/{s.id}#logistica')


# ==================== comercio: pagos y liquidaciones ====================

def _store_for(request: Request, db: Session, u) -> Store | None:
    if u.role == Role.SUPERADMIN:
        sid = form_int(request.query_params.get('store'))
        return db.get(Store, sid) if sid else None
    return db.get(Store, u.store_id) if u.store_id else None


@router.get('/pagos', response_class=HTMLResponse)
def store_payments(request: Request, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    s = _store_for(request, db, u)
    if not s:
        return go('/admin/finanzas' if u.role == Role.SUPERADMIN else '/admin')
    acct = mercadopago.account_for(db, s.id)
    settlements = db.scalars(select(MerchantSettlement).where(MerchantSettlement.store_id == s.id).order_by(MerchantSettlement.id.desc()).limit(30)).all()
    return templates.TemplateResponse(request, 'admin/store_payments.html', {
        'user': u, 's': s, 'acct': acct, 'mp_configured': mercadopago.configured(), 'sandbox': settings.mercadopago_sandbox,
        'balance': finance.merchant_balance(db, s.id), 'moves': finance.movements(db, 'merchant', store_id=s.id, limit=100), 'settlements': settlements,
        'statuses': finance.SETTLEMENT_STATUSES, 'flash': pop_flash(request), 'terms': plans.terms(s), 'commission': plans.commission_terms(db, s),
        'choices': plans.delivery_choices(s), 'plans': plans})


def _site_base(request: Request) -> str:
    from .public import public_base
    return public_base(request)


@router.get('/pagos/diagnostico', response_class=HTMLResponse)
def mp_diagnostics(request: Request, db: Session = Depends(get_db)):
    """Que pieza de Mercado Pago falta o esta mal (sin mostrar secretos)."""
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse): return u
    accounts = db.scalars(select(MercadoPagoAccount).order_by(MercadoPagoAccount.id.desc())).all()
    store_names = dict(db.execute(select(Store.id, Store.name).where(Store.id.in_([a.store_id for a in accounts] or [0]))).all())
    events = db.scalars(select(PaymentEvent).order_by(PaymentEvent.id.desc()).limit(15)).all()
    base = _site_base(request)
    return templates.TemplateResponse(request, 'admin/mp_diagnostics.html', {
        'user': u, 'checks': mercadopago.diagnose(db, base), 'accounts': accounts, 'store_names': store_names, 'events': events, 'base': base,
        'configured': mercadopago.configured(), 'sandbox': settings.mercadopago_sandbox, 'flash': pop_flash(request),
        'test': request.session.pop('mp_test', None), 'webhooks': list(payments_api.recent)})


@router.post('/pagos/diagnostico/probar')
def mp_diagnostics_test(request: Request, db: Session = Depends(get_db)):
    u = superadmin(request, db)
    if isinstance(u, RedirectResponse): return u
    ok, message = mercadopago.test_credentials()
    request.session['mp_test'] = ['ok' if ok else 'error', message]
    return go('/admin/pagos/diagnostico')


@router.get('/pagos/mercadopago/conectar')
def mp_connect(request: Request, store: int = 0, db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    sid = store if u.role == Role.SUPERADMIN else u.store_id
    if not sid or not mercadopago.configured():
        flash(request, 'error', 'Mercado Pago todavía no está configurado en el servidor.')
        return go('/admin/pagos' + (f'?store={sid}' if u.role == Role.SUPERADMIN and sid else ''))
    return RedirectResponse(mercadopago.authorization_url(sid, u.id), 303)


@router.get('/pagos/mercadopago/callback')
def mp_callback(request: Request, code: str = '', state: str = '', error: str = '', db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    data = mercadopago.read_state(state) if state else None
    back = '/admin/pagos'
    if not data or data.get('u') != u.id or (u.role != Role.SUPERADMIN and data.get('s') != u.store_id):
        flash(request, 'error', 'La conexión con Mercado Pago venció o no es válida. Probá de nuevo.')
        return go(back)
    s = db.get(Store, data['s'])
    back = '/admin/pagos' + (f'?store={s.id}' if u.role == Role.SUPERADMIN else '')
    if error or not code:
        flash(request, 'error', 'No se autorizó la conexión con Mercado Pago.')
        return go(back)
    try:
        mercadopago.connect(db, s, code, user=u, ip=client_ip(request))
        db.commit()
    except mercadopago.MPError as exc:
        db.rollback()
        logger.warning('No se pudo conectar Mercado Pago del comercio %s: %s', s.id, exc)
        flash(request, 'error', f'{exc}. Si el error dice "invalid_grant" o "redirect_uri", revisá que la Redirect URL sea igual en Render y en Mercado Pago.')
        return go(back)
    except Exception:  # noqa: BLE001 - mostrar algo util en vez de un error 500
        db.rollback()
        logger.exception('Error inesperado al conectar Mercado Pago del comercio %s', s.id)
        flash(request, 'error', 'Error inesperado al conectar Mercado Pago. Mirá el diagnóstico en Finanzas → Mercado Pago o los logs de Render.')
        return go(back)
    flash(request, 'ok', 'Mercado Pago conectado. Ya podés cobrar online.')
    return go(back)


@router.post('/pagos/mercadopago/desconectar')
def mp_disconnect(request: Request, store: str = Form(''), db: Session = Depends(get_db)):
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    sid = form_int(store) if u.role == Role.SUPERADMIN else u.store_id
    acct = mercadopago.account_for(db, sid or 0)
    if acct:
        mercadopago.disconnect(db, acct, user=u, ip=client_ip(request))
        db.commit()
        flash(request, 'ok', 'Mercado Pago desconectado: los pedidos nuevos ya no ofrecen pago online.')
    return go('/admin/pagos' + (f'?store={sid}' if u.role == Role.SUPERADMIN and sid else ''))


@router.post('/pagos/entrega')
def store_delivery_method(request: Request, method: str = Form(...), store: str = Form(''), db: Session = Depends(get_db)):
    """El comercio elige si usa la flota de respaldo, solo si su plan lo permite. Trappi Delivery: siempre la flota."""
    u = guard(request, db)
    if isinstance(u, RedirectResponse): return u
    sid = form_int(store) if u.role == Role.SUPERADMIN else u.store_id
    s = db.get(Store, sid or 0)
    if not s:
        return go('/admin')
    back = '/admin/pagos' + (f'?store={s.id}' if u.role == Role.SUPERADMIN else '')
    choices = plans.delivery_choices(s)
    if not choices:
        flash(request, 'error', 'Quién entrega lo define tu plan. Para cambiarlo, pedí el cambio de plan.' if s.plan == plans.DELIVERY
              else 'La flota de Trappi no está habilitada para tu comercio. Escribinos para sumarla.')
        return go(back)
    if method not in choices:
        flash(request, 'error', 'Elegí una opción válida.')
        return go(back)
    if method != s.logistics:
        before = s.logistics
        s.logistics = method
        audit.log(db, 'store.delivery_method', 'store', s.id, user=u, old=before, new=method, ip=client_ip(request))
        db.commit()
    flash(request, 'ok', 'Listo: ' + plans.LOGISTICS[method].lower() + '.')
    return go(back)
