"""Resumen semanal por mail al dueño del local (los lunes a la mañana, gratis con el mismo envio de emails).

Ventas y pedidos de la semana pasada (lunes a domingo) contra la anterior, lo más vendido, las reseñas,
lo que entró por WhatsApp y la tarjeta de sellos. Se manda una vez por semana por local (se "reserva" con un
UPDATE condicional, como los otros avisos) a los dueños activos del local. Se apaga desde Comandas → Avisos
o con el link del mail.
"""
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Order, OrderItem, OrderStatus, Review, Role, Store, User
from . import email
from .formatting import money
from .store_hours import to_local

log = logging.getLogger(__name__)
SEND_HOUR = 9  # lunes desde las 9 (hora de Argentina)
_unsub = URLSafeSerializer(settings.secret_key, salt='trappi-weekly-off')
DAYS = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']


def unsubscribe_token(store_id: int) -> str:
    return _unsub.dumps(store_id)


def store_from_token(token: str) -> int | None:
    try:
        v = _unsub.loads(token)
    except BadSignature:
        return None
    return v if isinstance(v, int) else None


def _range(monday_local: datetime) -> tuple[datetime, datetime]:
    start = monday_local.astimezone(timezone.utc).replace(tzinfo=None)
    return start, start + timedelta(days=7)


def build(db: Session, store: Store, monday_local: datetime) -> dict:
    """Numeros de la semana que empieza en monday_local (00:00, hora local) y de la anterior."""
    def totals(a, b):
        rows = db.execute(select(Order.status, func.count(Order.id), func.coalesce(func.sum(Order.total), 0)).where(
            Order.store_id == store.id, Order.created_at >= a, Order.created_at < b).group_by(Order.status)).all()
        by = {s: (n, t) for s, n, t in rows}
        done = by.get(OrderStatus.ENTREGADO, (0, 0))
        return {'orders': sum(n for n, _ in by.values()), 'delivered': done[0], 'sales': done[1], 'cancelled': by.get(OrderStatus.CANCELADO, (0, 0))[0]}
    a, b = _range(monday_local)
    out = totals(a, b)
    prev = totals(a - timedelta(days=7), a)
    out['prev_sales'] = prev['sales']
    out['vs'] = round((float(out['sales']) - float(prev['sales'])) / float(prev['sales']) * 100) if prev['sales'] else None
    out['avg_ticket'] = (out['sales'] / out['delivered']) if out['delivered'] else 0
    out['top'] = [(name, int(q)) for name, q in db.execute(
        select(OrderItem.product_name, func.sum(OrderItem.quantity)).join(Order, Order.id == OrderItem.order_id).where(
            Order.store_id == store.id, Order.status == OrderStatus.ENTREGADO, Order.created_at >= a, Order.created_at < b)
        .group_by(OrderItem.product_name).order_by(func.sum(OrderItem.quantity).desc()).limit(3)).all()]
    by_day = Counter(to_local(t).weekday() for t in db.scalars(select(Order.created_at).where(
        Order.store_id == store.id, Order.status == OrderStatus.ENTREGADO, Order.created_at >= a, Order.created_at < b)))
    out['best_day'] = DAYS[by_day.most_common(1)[0][0]] if by_day else None
    rv = db.execute(select(func.count(Review.id), func.avg(Review.rating)).where(
        Review.store_id == store.id, Review.hidden.is_(False), Review.created_at >= a, Review.created_at < b)).one()
    out['reviews'], out['rating'] = rv[0] or 0, round(float(rv[1]), 1) if rv[1] else None
    out['bad_reviews'] = db.scalar(select(func.count(Review.id)).where(Review.store_id == store.id, Review.hidden.is_(False), Review.rating <= 2,
                                                                      Review.reply.is_(None), Review.created_at >= a, Review.created_at < b)) or 0
    out['whatsapp'] = None
    if store.wa_enabled:
        from . import wa_agent
        w = wa_agent.day_counts(db, store.id, a, b)
        out['whatsapp'] = w if w['chats'] else None
    return out


def text(store: Store, r: dict, monday_local: datetime, base: str) -> str:
    end = monday_local + timedelta(days=6)
    lines = [f'Hola, este es el resumen de {store.name} en Trappi de la semana del {monday_local:%d/%m} al {end:%d/%m}.', '']
    vs = '' if r['vs'] is None else f' ({"▲" if r["vs"] >= 0 else "▼"} {abs(r["vs"])}% contra la semana anterior)'
    lines += [f'• Ventas: {money(r["sales"])}{vs}', f'• Pedidos entregados: {r["delivered"]} de {r["orders"]}' + (f' ({r["cancelled"]} cancelados)' if r['cancelled'] else ''),
              f'• Ticket promedio: {money(r["avg_ticket"])}']
    if r['best_day']:
        lines.append(f'• El día con más pedidos: {r["best_day"]}')
    if r['top']:
        lines += ['', 'Lo más vendido:'] + [f'  {i + 1}. {n} ({q})' for i, (n, q) in enumerate(r['top'])]
    if r['reviews']:
        lines += ['', f'Reseñas: {r["reviews"]} nuevas, promedio {str(r["rating"]).replace(".", ",")} ★' +
                  (f'. Tenés {r["bad_reviews"]} con 1 o 2 estrellas sin responder: {base}/admin/reviews?filter=negativas' if r['bad_reviews'] else '.')]
    if r['whatsapp']:
        w = r['whatsapp']
        lines += ['', f'WhatsApp con agente: {w["chats"]} charlas y {w["orders"]} pedidos ({money(w["sales"])}).']
    lines += ['', f'Ver todo en tu panel: {base}/admin', '',
              f'Para no recibir más este resumen: {base}/resumen-semanal/baja?t={unsubscribe_token(store.id)}']
    return '\n'.join(lines)


def run(db: Session, now_local: datetime, base: str | None = None) -> int:
    """Manda los resumenes que falten de la semana pasada. Devuelve cuantos mails salieron."""
    if now_local.weekday() != 0 or now_local.hour < SEND_HOUR or not email.configured():
        return 0
    base = (base or settings.public_base_url or 'https://trappi.com.ar').rstrip('/')
    today = now_local.date()
    last_monday = (now_local - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
    ids = db.scalars(select(Store.id).where(Store.weekly_report.is_(True), or_(Store.weekly_sent_on.is_(None), Store.weekly_sent_on < today))).all()
    sent = 0
    for sid in ids:
        res = db.execute(update(Store).where(Store.id == sid, or_(Store.weekly_sent_on.is_(None), Store.weekly_sent_on < today)).values(weekly_sent_on=today))
        db.commit()
        if res.rowcount != 1:
            continue
        store = db.get(Store, sid)
        r = build(db, store, last_monday)
        if not r['orders']:
            continue  # semana sin pedidos: no se manda nada
        owners = db.scalars(select(User.email).where(User.store_id == sid, User.role == Role.STORE_ADMIN, User.active.is_(True))).all()
        body = text(store, r, last_monday, base)
        subject = f'Tu semana en Trappi: {money(r["sales"])} en ventas' + (f' ({"+" if r["vs"] >= 0 else ""}{r["vs"]}%)' if r['vs'] is not None else '')
        for to in owners:
            try:
                email.send(to, subject, body)
                sent += 1
            except Exception:
                log.exception('resumen semanal a %s', sid)
    return sent
