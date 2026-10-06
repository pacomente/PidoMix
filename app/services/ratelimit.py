"""Limites de intentos por IP o por cuenta.

- RateLimiter: en memoria (por proceso). Para las rafagas generales de la web y la API, que se
  consultan en cada pedido y no vale la pena escribir en la base.
- PersistentRateLimiter: en la base. Para los ingresos (panel, cadetes, verificacion en dos pasos,
  codigos de entrega): no se reinicia al desplegar y vale para todas las instancias.

Render publica el servicio detras de Cloudflare: la IP que ve uvicorn es la del proxy, compartida
por todos los clientes. La IP real llega en CF-Connecting-IP, que Cloudflare siempre reescribe
(un cliente no puede falsificarla pasando por Cloudflare).
"""
import logging
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta

from starlette.requests import Request


def client_ip(request: Request) -> str:
    cf = (request.headers.get('cf-connecting-ip') or '').strip()
    if cf:
        return cf
    return (request.client.host if request.client else '') or 'desconocida'


class RateLimiter:
    SWEEP_EVERY = 500  # cada tantos registros se borran las IPs que ya no tienen intentos recientes

    def __init__(self, limit: int = 5, window_seconds: int = 300):
        self.limit, self.window = limit, window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)
        self._writes = 0

    def _purge(self, key: str, now: float) -> deque:
        q = self._hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def blocked(self, key: str) -> bool:
        q = self._purge(key, time.monotonic())
        if not q:
            self._hits.pop(key, None)  # no acumular claves vacias en memoria
        return len(q) >= self.limit

    def hit(self, key: str) -> None:
        now = time.monotonic()
        self._purge(key, now).append(now)
        self._writes += 1
        if self._writes % self.SWEEP_EVERY == 0:
            for k in [k for k, q in self._hits.items() if not q or now - q[-1] > self.window]:
                self._hits.pop(k, None)

    def check(self, key: str) -> bool:
        """Registra un intento y devuelve True si todavia esta dentro del limite."""
        if self.blocked(key):
            return False
        self.hit(key)
        return True

    def retry_after(self, key: str) -> int:
        q = self._hits.get(key)
        return max(1, int(self.window - (time.monotonic() - q[0])) + 1) if q else 1

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)

    def clear(self) -> None:
        self._hits.clear()


class PersistentRateLimiter:
    """Mismo uso que RateLimiter, pero los intentos quedan en la tabla auth_attempts.

    Cada llamada usa su propia sesion y confirma enseguida: un intento fallido cuenta aunque el
    pedido termine con error. Si la base no responde, no bloquea a nadie (falla abierto) y lo avisa
    en el log: el limite en memoria de la web y la API sigue frenando las rafagas.
    """
    SWEEP_EVERY = 200
    KEEP = timedelta(days=2)

    def __init__(self, name: str, limit: int = 5, window_seconds: int = 300):
        self.name, self.limit, self.window = name, limit, window_seconds
        self._writes = 0

    def _key(self, key: str) -> str:
        return f'{self.name}:{key}'[:200]

    def _since(self) -> datetime:
        return datetime.utcnow() - timedelta(seconds=self.window)

    def _run(self, fn, default):
        from ..db import SessionLocal
        try:
            with SessionLocal() as db:
                return fn(db)
        except Exception:  # noqa: BLE001 - un problema de la base no tiene que dejar a todos afuera
            logging.getLogger('pidomix').exception('Limite de intentos %s: no se pudo usar la base', self.name)
            return default

    def blocked(self, key: str) -> bool:
        from sqlalchemy import func, select
        from ..models import AuthAttempt
        k = self._key(key)
        return self._run(lambda db: (db.scalar(select(func.count(AuthAttempt.id)).where(AuthAttempt.key == k, AuthAttempt.created_at > self._since())) or 0) >= self.limit, False)

    def hit(self, key: str) -> None:
        from sqlalchemy import delete
        from ..models import AuthAttempt
        self._writes += 1
        sweep = self._writes % self.SWEEP_EVERY == 0

        def run(db):
            db.add(AuthAttempt(key=self._key(key)))
            if sweep:
                db.execute(delete(AuthAttempt).where(AuthAttempt.created_at < datetime.utcnow() - self.KEEP))
            db.commit()
        self._run(run, None)

    def check(self, key: str) -> bool:
        if self.blocked(key):
            return False
        self.hit(key)
        return True

    def retry_after(self, key: str) -> int:
        from sqlalchemy import func, select
        from ..models import AuthAttempt
        k = self._key(key)
        first = self._run(lambda db: db.scalar(select(func.min(AuthAttempt.created_at)).where(AuthAttempt.key == k, AuthAttempt.created_at > self._since())), None)
        return max(1, int(self.window - (datetime.utcnow() - first).total_seconds()) + 1) if first else 1

    def reset(self, key: str) -> None:
        from sqlalchemy import delete, select
        from ..models import AuthAttempt
        k = self._key(key)

        def run(db):
            if db.scalar(select(AuthAttempt.id).where(AuthAttempt.key == k).limit(1)):  # casi siempre no hay nada: no escribe
                db.execute(delete(AuthAttempt).where(AuthAttempt.key == k))
                db.commit()
        self._run(run, None)

    def clear(self) -> None:
        """Borra todos los intentos de este limite (lo usan los tests)."""
        from sqlalchemy import delete
        from ..models import AuthAttempt

        def run(db):
            db.execute(delete(AuthAttempt).where(AuthAttempt.key.like(f'{self.name}:%')))
            db.commit()
        self._run(run, None)


# Pedidos nuevos por IP (web y app comparten el mismo cupo). Los celulares con datos moviles
# suelen salir por una IP compartida de la compania, por eso los topes son holgados.
order_limiter = PersistentRateLimiter('order', limit=20, window_seconds=600)
# Rafagas generales por IP: frena scrapers y bots sin molestar a clientes reales
api_limiter = RateLimiter(limit=300, window_seconds=60)
web_limiter = RateLimiter(limit=300, window_seconds=60)
