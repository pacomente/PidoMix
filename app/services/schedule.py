"""Pedidos programados: el cliente elige para cuando lo quiere (hoy, mañana o pasado, cada 15 minutos).

Los horarios salen del horario del local y de su demora; se puede programar aunque el local este cerrado ahora
(por ejemplo a la mañana para el almuerzo). El backend vuelve a validar el horario elegido al crear el pedido.
"""
from datetime import datetime, timedelta, timezone

from ..models import StoreStatus
from .store_hours import local_now, open_at

STEP = 15  # minutos entre un horario y el siguiente
DAYS = 3  # hoy, mañana y pasado
MIN_AHEAD = 30  # lo programado tiene que ser por lo menos para dentro de media hora
_WEEKDAYS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']


def _ceil(dt: datetime) -> datetime:
    dt = dt.replace(second=0, microsecond=0)
    extra = (-dt.minute) % STEP
    return dt + timedelta(minutes=extra)


def allowed(store) -> bool:
    """Si el local admite pedidos programados ahora (no si esta cerrado a mano, suspendido, etc.)."""
    return store.status == StoreStatus.ACTIVA


_cache: dict = {}
CACHE_MAX = 2000


def options(store, now: datetime | None = None) -> list[dict]:
    """[{'date': '2026-10-22', 'label': 'Hoy', 'slots': ['20:15', ...]}, ...] en hora local.
    Se guarda un minuto por local (las listas de comercios lo piden para cada local cerrado)."""
    if not allowed(store):
        return []
    if now is None:
        now = local_now()
        hours = tuple(sorted((h.weekday, h.open_time, h.close_time, h.closed) for h in store.hours))
        key = (store.id, now.strftime('%Y-%m-%d %H:%M'), store.prep_minutes, hours)
        hit = _cache.get(store.id)
        if hit and hit[0] == key:
            return hit[1]
        out = _compute(store, now)
        if len(_cache) > CACHE_MAX:
            _cache.clear()
        _cache[store.id] = (key, out)
        return out
    return _compute(store, now)


def _compute(store, now: datetime) -> list[dict]:
    first = _ceil(now + timedelta(minutes=max(MIN_AHEAD, store.prep_minutes)))
    out = []
    for offset in range(DAYS):
        day = (now + timedelta(days=offset)).date()
        t = now.replace(year=day.year, month=day.month, day=day.day, hour=0, minute=0, second=0, microsecond=0)
        slots = []
        while t.date() == day:
            # que este abierto a esa hora y que haya estado abierto el rato de preparacion antes
            if t >= first and open_at(store, t) and open_at(store, t - timedelta(minutes=min(store.prep_minutes, 45))):
                slots.append(t.strftime('%H:%M'))
            t += timedelta(minutes=STEP)
        if slots:
            label = 'Hoy' if offset == 0 else 'Mañana' if offset == 1 else f'{_WEEKDAYS[day.weekday()]} {day.day}'
            out.append({'date': day.isoformat(), 'label': label, 'slots': slots})
    return out


def parse(store, value: str, now: datetime | None = None) -> datetime | None:
    """'2026-10-22T20:15' -> datetime UTC naive (como se guarda). None si no es un horario valido para ese local."""
    try:
        day, hhmm = (value or '').strip().split('T')
    except ValueError:
        return None
    for d in options(store, now):
        if d['date'] == day and hhmm in d['slots']:
            local = (now or local_now()).tzinfo
            dt = datetime.fromisoformat(f'{day}T{hhmm}').replace(tzinfo=local)
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return None


def label(dt_utc: datetime | None, now: datetime | None = None) -> str:
    """'hoy 20:15' / 'mañana 12:30' / 'el viernes 24 a las 13:00' (para mensajes)."""
    if not dt_utc:
        return ''
    now = now or local_now()
    local = dt_utc.replace(tzinfo=timezone.utc).astimezone(now.tzinfo)
    days = (local.date() - now.date()).days
    when = 'hoy' if days == 0 else 'mañana' if days == 1 else f'el {_WEEKDAYS[local.weekday()].lower()} {local.day}'
    return f'{when} a las {local.strftime("%H:%M")}'


def next_day_opening(store, now: datetime | None = None) -> datetime:
    """Cuando abre el local el proximo dia (UTC naive). Sin horario cargado: mañana a las 6."""
    now = now or local_now()
    for offset in range(1, 8):
        day = now + timedelta(days=offset)
        opens = sorted(h.open_time for h in store.hours if h.weekday == day.weekday() and not h.closed)
        if opens or not store.hours:
            hh, mm = (opens[0] if opens else '06:00').split(':')
            at = day.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
            return at.astimezone(timezone.utc).replace(tzinfo=None)
    at = (now + timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)
    return at.astimezone(timezone.utc).replace(tzinfo=None)


def hint(store) -> str | None:
    """Para las listas de comercios cuando esta cerrado: 'Programalo para hoy 12:30' (None si no se puede)."""
    days = options(store)
    if not days:
        return None
    d = days[0]
    when = d['label'].lower() if d['label'] in ('Hoy', 'Mañana') else d['label']
    return f'Programalo para {when} {d["slots"][0]}'
