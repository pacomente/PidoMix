from datetime import datetime, timedelta, timezone

from ..models import StoreStatus

try:
    from zoneinfo import ZoneInfo
    LOCAL_TZ = ZoneInfo("America/Argentina/Buenos_Aires")
except Exception:  # sin base tzdata en el sistema
    LOCAL_TZ = timezone(timedelta(hours=-3))


def local_now() -> datetime:
    return datetime.now(LOCAL_TZ)


def local_day_start_utc(days_back: int = 0) -> datetime:
    """Medianoche local (Argentina) de hace N dias, como datetime UTC naive (como se guarda created_at)."""
    start = local_now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_back)
    return start.astimezone(timezone.utc).replace(tzinfo=None)


def to_local(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ)


def is_open(store) -> bool:
    if store.status != StoreStatus.ACTIVA:
        return False
    now = local_now()
    current = now.strftime("%H:%M")
    todays = [h for h in store.hours if h.weekday == now.weekday()]
    if not todays:
        return True
    for h in todays:
        if h.closed:
            continue
        if h.open_time <= h.close_time:
            if h.open_time <= current <= h.close_time:
                return True
        elif current >= h.open_time or current <= h.close_time:  # horario que cruza medianoche
            return True
    return False


_DAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def open_text(store) -> str:
    """Texto para el cliente cuando el local esta cerrado: 'Abre hoy a las 18:00'."""
    if store.status == StoreStatus.CERRADA:
        return "Cerrado temporalmente"
    now = local_now()
    current = now.strftime("%H:%M")
    for offset in range(8):
        weekday = (now.weekday() + offset) % 7
        slots = sorted((h.open_time for h in store.hours if h.weekday == weekday and not h.closed))
        if offset == 0:
            slots = [s for s in slots if s > current]
        if slots:
            when = "hoy" if offset == 0 else ("mañana" if offset == 1 else f"el {_DAYS[weekday]}")
            return f"Abre {when} a las {slots[0]}"
    return "Cerrado por ahora"
