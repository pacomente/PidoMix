"""Limites de pedidos por IP, en memoria (por proceso).

Render publica el servicio detras de Cloudflare: la IP que ve uvicorn es la del proxy, compartida
por todos los clientes. La IP real llega en CF-Connecting-IP, que Cloudflare siempre reescribe
(un cliente no puede falsificarla pasando por Cloudflare).
"""
import time
from collections import defaultdict, deque

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


# Pedidos nuevos por IP (web y app comparten el mismo cupo). Los celulares con datos moviles
# suelen salir por una IP compartida de la compania, por eso los topes son holgados.
order_limiter = RateLimiter(limit=20, window_seconds=600)
# Rafagas generales por IP: frena scrapers y bots sin molestar a clientes reales
api_limiter = RateLimiter(limit=300, window_seconds=60)
web_limiter = RateLimiter(limit=300, window_seconds=60)
