"""Distancias y zonas de entrega.

Cada local puede marcar su ubicacion y definir anillos de cobertura ("hasta 2 km: $1.000").
Si no lo hizo, todo sigue como antes: envio fijo y sin control de zona.
"""
from dataclasses import dataclass
from decimal import Decimal
from math import asin, cos, radians, sin, sqrt

EARTH_KM = 6371.0088
MAX_ZONE_KM = 50


def distance_km(lat1, lng1, lat2, lng2) -> float:
    """Distancia en linea recta (haversine). El recorrido real suele ser ~20-30% mayor."""
    dlat, dlng = radians(lat2 - lat1), radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 2 * EARTH_KM * asin(sqrt(a))


def parse_location(data) -> dict | None:
    """{'lat','lng','label'} valido o None. Acepta lo que guardamos en la sesion o lo que manda el navegador."""
    try:
        lat, lng = float(data.get("lat")), float(data.get("lng"))
    except (TypeError, ValueError, AttributeError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180) or (lat == 0 and lng == 0):
        return None
    label = str(data.get("label") or "").strip()[:120] or "Mi ubicación"
    return {"lat": round(lat, 6), "lng": round(lng, 6), "label": label}


@dataclass
class Coverage:
    zoned: bool                     # el local configuro ubicacion + zonas
    distance: float | None = None   # km en linea recta (si hay ubicacion del cliente y del local)
    covered: bool | None = None     # None = no sabemos (falta la ubicacion del cliente)
    cost: Decimal | None = None     # costo de envio para esa distancia (o el fijo)
    max_km: float | None = None
    from_cost: Decimal | None = None  # el envio mas barato, para mostrar "desde $X"

    @property
    def delivers(self) -> bool:
        """Se puede pedir delivery (o al menos no sabemos que no)."""
        return self.covered is not False


def coverage(store, loc: dict | None) -> Coverage:
    if not store.delivery_enabled:
        return Coverage(zoned=False, covered=False)
    zones = list(store.zones or []) if store.lat is not None and store.lng is not None else []
    dist = distance_km(store.lat, store.lng, loc["lat"], loc["lng"]) if loc and store.lat is not None and store.lng is not None else None
    if not zones:
        return Coverage(zoned=False, distance=dist, covered=True, cost=Decimal(store.delivery_cost or 0))
    max_km = float(zones[-1].max_km)
    cheapest = min(Decimal(z.cost) for z in zones)
    if dist is None:
        return Coverage(zoned=True, covered=None, max_km=max_km, from_cost=cheapest)
    zone = next((z for z in zones if dist <= float(z.max_km)), None)
    return Coverage(zoned=True, distance=dist, covered=zone is not None, cost=Decimal(zone.cost) if zone else None, max_km=max_km, from_cost=cheapest)


def format_km(km: float | None) -> str:
    if km is None:
        return ""
    return f"{round(km * 1000 / 50) * 50:.0f} m" if km < 1 else f"{km:.1f} km".replace(".", ",")
