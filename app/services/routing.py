"""Distancia real por calle entre dos puntos (para cobrar el envio de la flota por km).

RoutingService elige el proveedor con ROUTING_PROVIDER:
  osrm  servidor OSRM (ROUTING_URL; el publico router.project-osrm.org es de prueba, conviene uno propio)
  none  sin proveedor: siempre se estima
Si el proveedor no responde, segun la configuracion se estima (linea recta x factor, marcado como
"estimate") o se avisa que no hay ruta. Las respuestas se guardan en una cache en memoria.
La clave del proveedor, si hace falta, solo vive en el backend.
"""
import logging
import threading
import time
from dataclasses import dataclass

import httpx

from ..config import settings
from .geo import distance_km

logger = logging.getLogger('trappi.routing')

CACHE_SECONDS = 6 * 3600
CACHE_MAX = 5000


@dataclass(frozen=True)
class Route:
    km: float
    minutes: float | None
    source: str  # osrm | estimate


class RoutingError(Exception):
    pass


class OSRMProvider:
    name = 'osrm'

    def __init__(self, base_url: str, timeout: float, api_key: str = '', transport: httpx.BaseTransport | None = None):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.api_key = api_key
        self.transport = transport

    def route(self, a: tuple[float, float], b: tuple[float, float]) -> Route:
        # OSRM recibe lng,lat
        url = f'{self.base_url}/route/v1/driving/{a[1]:.6f},{a[0]:.6f};{b[1]:.6f},{b[0]:.6f}'
        params = {'overview': 'false', 'alternatives': 'false'}
        headers = {'Authorization': f'Bearer {self.api_key}'} if self.api_key else {}
        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                resp = client.get(url, params=params, headers=headers)
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RoutingError(f'OSRM no respondió: {exc}') from exc
        if resp.status_code != 200 or data.get('code') != 'Ok' or not data.get('routes'):
            raise RoutingError(f"OSRM sin ruta ({resp.status_code} {data.get('code')})")
        r = data['routes'][0]
        return Route(km=round(float(r['distance']) / 1000, 3), minutes=round(float(r['duration']) / 60, 1), source='osrm')


class RoutingService:
    def __init__(self, provider=None):
        self.provider = provider
        self._cache: dict = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(a, b):
        # ~11 m de precision: la misma cuadra usa la misma ruta
        return (round(a[0], 4), round(a[1], 4), round(b[0], 4), round(b[1], 4))

    def clear(self):
        with self._lock:
            self._cache.clear()

    def route(self, a: tuple[float, float], b: tuple[float, float], *, fallback: str = 'estimate', detour: float = 1.35) -> Route | None:
        """Ruta por calle de a -> b. None si no hay proveedor que responda y fallback == 'reject'."""
        key = self._key(a, b)
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(key)
            if hit and now - hit[0] < CACHE_SECONDS:
                return hit[1]
        route = None
        if self.provider is not None:
            try:
                route = self.provider.route(a, b)
            except RoutingError as exc:
                logger.warning('Ruta no disponible: %s', exc)
        if route is None:
            if fallback == 'reject':
                return None
            straight = distance_km(a[0], a[1], b[0], b[1])
            route = Route(km=round(straight * detour, 3), minutes=None, source='estimate')
            return route  # lo estimado no se guarda: se vuelve a intentar con el proveedor la proxima vez
        with self._lock:
            if len(self._cache) >= CACHE_MAX:
                self._cache.clear()
            self._cache[key] = (now, route)
        return route


def _default_provider():
    if settings.routing_provider.lower() == 'osrm' and settings.routing_url:
        return OSRMProvider(settings.routing_url, settings.routing_timeout_seconds, settings.routing_api_key)
    return None


service = RoutingService(_default_provider())


def set_provider(provider) -> None:
    """Para tests o para cambiar de proveedor en caliente."""
    service.provider = provider
    service.clear()
