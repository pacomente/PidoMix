"""Distancia real por calle entre dos puntos (para cobrar el envio de la flota por km).

RoutingService elige el proveedor con ROUTING_PROVIDER:
  osrm  servidor OSRM (ROUTING_URL; el publico router.project-osrm.org es de prueba, conviene uno propio)
  none  sin proveedor: siempre se estima
Todo gratis: si el principal no responde se prueban los respaldos en orden (ROUTING_FALLBACK_URLS, por
defecto el OSRM de OpenStreetMap, y OpenRouteService si hay ORS_API_KEY). Un proveedor que falla se saltea
un rato, asi no se espera su timeout en cada pedido.
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
COOLDOWN_SECONDS = 120  # un proveedor que fallo no se vuelve a probar hasta dentro de 2 minutos
# los servidores publicos piden que la app se identifique (politica de uso de OpenStreetMap)
USER_AGENT = 'Trappi/1.0 (+https://trappi.com.ar)'


@dataclass(frozen=True)
class Route:
    km: float
    minutes: float | None
    source: str  # osrm | ors | estimate


class RoutingError(Exception):
    pass


class OSRMProvider:
    name = 'osrm'

    def __init__(self, base_url: str, timeout: float, api_key: str = '', transport: httpx.BaseTransport | None = None):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.api_key = api_key
        self.transport = transport
        self.label = self.base_url.split('://')[-1].split('/')[0]  # para los logs (sin la clave)

    def route(self, a: tuple[float, float], b: tuple[float, float]) -> Route:
        # OSRM recibe lng,lat
        url = f'{self.base_url}/route/v1/driving/{a[1]:.6f},{a[0]:.6f};{b[1]:.6f},{b[0]:.6f}'
        params = {'overview': 'false', 'alternatives': 'false'}
        headers = {'User-Agent': USER_AGENT, **({'Authorization': f'Bearer {self.api_key}'} if self.api_key else {})}
        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                resp = client.get(url, params=params, headers=headers)
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RoutingError(f'OSRM ({self.label}) no respondió: {exc}') from exc
        if resp.status_code != 200 or data.get('code') != 'Ok' or not data.get('routes'):
            raise RoutingError(f"OSRM ({self.label}) sin ruta ({resp.status_code} {data.get('code')})")
        r = data['routes'][0]
        return Route(km=round(float(r['distance']) / 1000, 3), minutes=round(float(r['duration']) / 60, 1), source='osrm')

    def directions(self, a: tuple[float, float], b: tuple[float, float]) -> dict:
        """Recorrido completo por calle con las maniobras (para guiar al repartidor)."""
        url = f'{self.base_url}/route/v1/driving/{a[1]:.6f},{a[0]:.6f};{b[1]:.6f},{b[0]:.6f}'
        params = {'overview': 'full', 'geometries': 'geojson', 'steps': 'true', 'alternatives': 'false'}
        headers = {'User-Agent': USER_AGENT, **({'Authorization': f'Bearer {self.api_key}'} if self.api_key else {})}
        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                resp = client.get(url, params=params, headers=headers)
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RoutingError(f'OSRM ({self.label}) no respondió: {exc}') from exc
        if resp.status_code != 200 or data.get('code') != 'Ok' or not data.get('routes'):
            raise RoutingError(f"OSRM ({self.label}) sin ruta ({resp.status_code} {data.get('code')})")
        return parse_directions(data['routes'][0])


# OpenRouteService: tipos de maniobra -> los de OSRM (asi las indicaciones salen con el mismo texto)
ORS_STEP = {0: ('turn', 'left'), 1: ('turn', 'right'), 2: ('turn', 'sharp left'), 3: ('turn', 'sharp right'), 4: ('turn', 'slight left'),
            5: ('turn', 'slight right'), 6: ('continue', 'straight'), 7: ('roundabout', None), 8: ('exit roundabout', None), 9: ('turn', 'uturn'),
            10: ('arrive', None), 11: ('depart', None), 12: ('turn', 'slight left'), 13: ('turn', 'slight right')}


class ORSProvider:
    """OpenRouteService (plan gratis con clave). La clave va solo en el header, nunca en la URL ni en los logs."""
    name = 'ors'
    label = 'openrouteservice'
    URL = 'https://api.openrouteservice.org/v2/directions/driving-car/geojson'

    def __init__(self, api_key: str, timeout: float, transport: httpx.BaseTransport | None = None):
        self.api_key = api_key
        self.timeout = timeout
        self.transport = transport

    def _get(self, a, b, steps: bool) -> dict:
        body = {'coordinates': [[a[1], a[0]], [b[1], b[0]]], 'instructions': steps, 'language': 'es', 'units': 'm'}
        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                resp = client.post(self.URL, json=body, headers={'Authorization': self.api_key, 'User-Agent': USER_AGENT})
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RoutingError(f'OpenRouteService no respondió: {exc}') from exc
        feats = data.get('features') if isinstance(data, dict) else None
        if resp.status_code != 200 or not feats:
            raise RoutingError(f'OpenRouteService sin ruta ({resp.status_code})')
        return feats[0]

    def route(self, a, b) -> Route:
        s = self._get(a, b, False)['properties']['summary']
        return Route(km=round(float(s.get('distance', 0)) / 1000, 3), minutes=round(float(s.get('duration', 0)) / 60, 1), source='ors')

    def directions(self, a, b) -> dict:
        f = self._get(a, b, True)
        coords = (f.get('geometry') or {}).get('coordinates') or []
        steps = []
        for seg in f['properties'].get('segments') or []:
            for st in seg.get('steps') or []:
                kind, mod = ORS_STEP.get(st.get('type'), ('turn', 'straight'))
                wp = (st.get('way_points') or [0])[0]
                loc = coords[wp] if 0 <= wp < len(coords) else [None, None]
                name = st.get('name') if st.get('name') not in (None, '-') else ''
                steps.append({'maneuver': {'type': kind, 'modifier': mod or 'straight', 'location': loc, 'exit': st.get('exit_number')},
                              'name': name, 'distance': st.get('distance') or 0})
        s = f['properties']['summary']
        out = parse_directions({'distance': s.get('distance', 0), 'duration': s.get('duration', 0), 'geometry': {'coordinates': coords},
                                'legs': [{'steps': steps}]})
        out['source'] = 'ors'
        return out


class ChainProvider:
    """Prueba los proveedores en orden y se queda con el primero que responde. El que falla se saltea
    COOLDOWN_SECONDS (salvo que fallen todos: ahi se vuelven a probar todos)."""
    name = 'chain'

    def __init__(self, providers: list, clock=time.monotonic):
        self.providers = providers
        self.clock = clock
        self._down: dict[int, float] = {}
        self._lock = threading.Lock()

    def _order(self) -> list:
        now = self.clock()
        with self._lock:
            up = [p for i, p in enumerate(self.providers) if self._down.get(i, 0) <= now]
        return up or list(self.providers)

    def _call(self, method: str, a, b):
        errors = []
        for p in self._order():
            i = self.providers.index(p)
            try:
                out = getattr(p, method)(a, b)
            except RoutingError as exc:
                errors.append(str(exc))
                with self._lock:
                    self._down[i] = self.clock() + COOLDOWN_SECONDS
                continue
            with self._lock:
                self._down.pop(i, None)
            if errors:
                logger.info('Ruta por el respaldo %s (%s)', getattr(p, 'label', p.name), '; '.join(errors))
            return out
        raise RoutingError(' / '.join(errors) or 'sin proveedores de rutas')

    def route(self, a, b) -> Route:
        return self._call('route', a, b)

    def directions(self, a, b) -> dict:
        return self._call('directions', a, b)


# ---------- indicaciones paso a paso (app de repartidores) ----------

MODIFIER = {'right': 'doblá a la derecha', 'left': 'doblá a la izquierda', 'slight right': 'tomá levemente a la derecha',
            'slight left': 'tomá levemente a la izquierda', 'sharp right': 'doblá cerrado a la derecha', 'sharp left': 'doblá cerrado a la izquierda',
            'straight': 'seguí derecho', 'uturn': 'pegá la vuelta en U'}


def instruction(step: dict) -> str:
    """Texto en castellano de una maniobra de OSRM ("Doblá a la derecha por Av. Alem")."""
    m = step.get('maneuver') or {}
    kind, mod, name = m.get('type', ''), m.get('modifier', 'straight'), (step.get('name') or '').strip()
    by = f' por {name}' if name else ''
    if kind == 'depart':
        return f'Salí{by}' if name else 'Arrancá'
    if kind == 'arrive':
        return 'Llegaste'
    if kind in ('roundabout', 'rotary', 'roundabout turn'):
        n = m.get('exit')
        return (f'En la rotonda, tomá la {n}ª salida' if n else 'Entrá a la rotonda') + (f' hacia {name}' if name else '')
    if kind in ('exit roundabout', 'exit rotary'):
        return f'Salí de la rotonda{by}'
    if kind in ('new name', 'continue') and mod in ('straight', None):
        return f'Seguí derecho{by}'
    if kind == 'merge':
        return f'Incorporate{by}'
    text = MODIFIER.get(mod, 'seguí')
    return text[0].upper() + text[1:] + by


def parse_directions(route: dict) -> dict:
    steps = []
    for leg in route.get('legs') or []:
        for st in leg.get('steps') or []:
            loc = (st.get('maneuver') or {}).get('location') or [None, None]
            steps.append({'text': instruction(st), 'distance_m': round(float(st.get('distance') or 0)), 'lng': loc[0], 'lat': loc[1],
                          'type': (st.get('maneuver') or {}).get('type'), 'modifier': (st.get('maneuver') or {}).get('modifier')})
    geometry = (route.get('geometry') or {}).get('coordinates') or []
    return {'km': round(float(route['distance']) / 1000, 2), 'minutes': round(float(route['duration']) / 60, 1),
            'geometry': [[round(x, 6), round(y, 6)] for x, y in geometry], 'steps': steps, 'source': 'osrm'}


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


    def directions(self, a: tuple[float, float], b: tuple[float, float]) -> dict | None:
        """Recorrido e indicaciones; None si no hay proveedor que responda (la app dibuja la línea recta)."""
        if self.provider is None or not hasattr(self.provider, 'directions'):
            return None
        key = ('dir',) + self._key(a, b)
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(key)
            if hit and now - hit[0] < DIRECTIONS_CACHE_SECONDS:
                return hit[1]
        try:
            out = self.provider.directions(a, b)
        except RoutingError as exc:
            logger.warning('Indicaciones no disponibles: %s', exc)
            return None
        with self._lock:
            if len(self._cache) >= CACHE_MAX:
                self._cache.clear()
            self._cache[key] = (now, out)
        return out


DIRECTIONS_CACHE_SECONDS = 600


def _default_provider():
    if settings.routing_provider.lower() != 'osrm':
        return None
    t = settings.routing_timeout_seconds
    chain = [OSRMProvider(settings.routing_url, t, settings.routing_api_key)] if settings.routing_url else []
    for url in (u.strip() for u in settings.routing_fallback_urls.split(',')):
        if url.startswith('https://') and url.rstrip('/') != settings.routing_url.rstrip('/'):
            chain.append(OSRMProvider(url, t))
    if settings.ors_api_key:
        chain.append(ORSProvider(settings.ors_api_key, t))
    if not chain:
        return None
    return chain[0] if len(chain) == 1 else ChainProvider(chain)


service = RoutingService(_default_provider())


def set_provider(provider) -> None:
    """Para tests o para cambiar de proveedor en caliente."""
    service.provider = provider
    service.clear()
