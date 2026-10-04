"""Configuración de la plataforma que el superadmin cambia desde el panel (/admin/settings).

Cada opción tiene un valor por defecto: si nadie la tocó, la plataforma funciona como siempre.
Se guardan en la tabla settings (clave/valor) y se leen con una caché corta para no consultar
la base en cada request.
"""
import re
import threading
import time
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Setting
from .forms import parse_number

GITHUB_APK = 'https://github.com/pacomente/PidoMix/releases/download/app-android/'

MAP_STYLES = {
    'liberty': ('OpenFreeMap · Liberty (colores, recomendado)', 'https://tiles.openfreemap.org/styles/liberty'),
    'bright': ('OpenFreeMap · Bright (más contraste)', 'https://tiles.openfreemap.org/styles/bright'),
    'positron': ('OpenFreeMap · Positron (gris claro, minimalista)', 'https://tiles.openfreemap.org/styles/positron'),
    'custom': ('Otro proveedor (URL de un estilo MapLibre)', ''),
}


@dataclass
class Option:
    key: str
    kind: str  # bool, int, float, str, text, choice, url, version
    default: object
    label: str
    help: str = ''
    section: str = ''
    min: float | None = None
    max: float | None = None
    choices: dict = field(default_factory=dict)


SECTIONS = {
    'apps': ('Apps y mantenimiento', 'Apagá cualquier parte de Trappi mientras la actualizás. Los usuarios ven el mensaje que escribas; el panel y comandas siguen funcionando.'),
    'couriers': ('Repartidores', 'Cómo se ofrecen los viajes y cuánto gana cada repartidor.'),
    'maps': ('Mapas y direcciones', 'Proveedores de mapas de la app de repartidores y de la web, y el buscador de direcciones.'),
    'commercial': ('Configuración comercial', 'Planes de Trappi y cómo te contactan los comercios que se quieren sumar. Los comercios se dan de alta solo desde el panel, después de hablar por WhatsApp.'),
}

MAINTENANCE = 'Estamos actualizando Trappi. Volvé en unos minutos 🙌'

OPTIONS = [
    # --- apps ---
    Option('web_enabled', 'bool', True, 'Tienda web activa', 'Apagada, la web muestra el mensaje de mantenimiento (el panel /admin sigue andando).', 'apps'),
    Option('web_message', 'str', MAINTENANCE, 'Mensaje de la web apagada', section='apps'),
    Option('orders_enabled', 'bool', True, 'Recibir pedidos', 'Apagado, nadie puede hacer pedidos (ni por la web ni por la app), pero se puede navegar.', 'apps'),
    Option('orders_message', 'str', 'Por un momento no estamos tomando pedidos. Volvé a intentar en unos minutos.', 'Mensaje de pedidos pausados', section='apps'),
    Option('app_clientes_enabled', 'bool', True, 'App de clientes activa', 'Apagada, la app muestra el mensaje de mantenimiento.', 'apps'),
    Option('app_clientes_message', 'str', MAINTENANCE, 'Mensaje de la app de clientes apagada', section='apps'),
    Option('app_clientes_min_version', 'version', '1.0.0', 'Versión mínima de la app de clientes', 'Las versiones anteriores tienen que actualizar para seguir usándola (ej: 1.2.0).', 'apps'),
    Option('app_clientes_download_url', 'url', GITHUB_APK + 'trappi.apk', 'Link de descarga de la app de clientes', 'Play Store o el APK.', 'apps'),
    Option('app_repartidor_enabled', 'bool', True, 'App de repartidores activa', 'Apagada, los repartidores quedan desconectados y no reciben viajes (los locales asignan a mano).', 'apps'),
    Option('app_repartidor_message', 'str', 'Estamos actualizando la app de repartidores. Volvé en unos minutos.', 'Mensaje de la app de repartidores apagada', section='apps'),
    Option('app_repartidor_min_version', 'version', '1.0.0', 'Versión mínima de la app de repartidores', section='apps'),
    Option('app_repartidor_download_url', 'url', GITHUB_APK + 'trappi-repartidor.apk', 'Link de descarga de la app de repartidores', section='apps'),
    # --- repartidores ---
    Option('dispatch_auto', 'bool', True, 'Ofrecer los viajes automáticamente', 'Apagado, ningún viaje se ofrece solo: cada local los asigna desde comandas.', 'couriers'),
    Option('dispatch_offer_seconds', 'int', 35, 'Segundos para aceptar una oferta', section='couriers', min=10, max=120),
    Option('dispatch_radius_km', 'float', 8.0, 'Radio máximo desde el local (km)', 'Repartidores más lejos no reciben la oferta.', 'couriers', min=0.5, max=50),
    Option('dispatch_reoffer_minutes', 'int', 3, 'Volver a ofrecer a quien no respondió después de (minutos)', section='couriers', min=0, max=120),
    Option('dispatch_location_minutes', 'int', 5, 'Ubicación válida durante (minutos)', 'Si la app del repartidor no reporta su ubicación en este tiempo, deja de recibir ofertas.', 'couriers', min=1, max=60),
    Option('courier_pulse_seconds', 'int', 4, 'Cada cuántos segundos la app manda la ubicación', 'Menos segundos = ofertas más rápidas, pero más batería y datos.', 'couriers', min=3, max=30),
    Option('delivery_pin_required', 'bool', True, 'Pedir el PIN de entrega', 'El cliente recibe un PIN de 4 números con su pedido y el repartidor lo tiene que cargar para marcarlo entregado.', 'couriers'),
    Option('courier_pay_mode', 'choice', 'shipping', 'Cuánto gana el repartidor por viaje', section='couriers',
           choices={'shipping': 'El costo de envío completo', 'percent': 'Un porcentaje del costo de envío', 'fixed': 'Un monto fijo por viaje'}),
    Option('courier_pay_value', 'float', 100.0, 'Porcentaje o monto', 'Con "porcentaje": ej. 80 (= 80 % del envío). Con "monto fijo": ej. 1500.', 'couriers', min=0, max=1_000_000),
    # --- mapas ---
    Option('driver_map_style', 'choice', 'liberty', 'Mapa de la app de repartidores', section='maps', choices={k: v[0] for k, v in MAP_STYLES.items()}),
    Option('driver_map_style_url', 'url', '', 'URL del estilo (si elegiste "Otro proveedor")', 'Ej: un estilo de MapTiler o Stadia con tu clave: https://api.maptiler.com/maps/streets-v2/style.json?key=…', 'maps'),
    Option('web_tiles_url', 'url', 'https://tile.openstreetmap.org/{z}/{x}/{y}.png', 'Mosaicos del mapa de la web', 'Plantilla {z}/{x}/{y} (Leaflet). Con mucho tráfico conviene un proveedor con plan propio.', 'maps'),
    Option('web_tiles_attribution', 'str', '&copy; OpenStreetMap', 'Atribución del mapa de la web', section='maps'),
    Option('geocoder_url', 'url', 'https://nominatim.openstreetmap.org/', 'Buscador de direcciones (Nominatim)', 'URL base de un servidor compatible con Nominatim (/search y /reverse).', 'maps'),
    # --- contacto ---
    # --- comercial (planes, alta de comercios) ---
    Option('platform_whatsapp', 'str', '', 'WhatsApp de contacto comercial', 'Abre el botón "Sumá tu comercio" de la web y "Solicitar cambio de plan" del panel de cada local (sin espacios ni +, ej: 5492911234567). También es el contacto de soporte de las apps.', 'commercial'),
    Option('commercial_message', 'str', 'Hola, quiero sumar mi comercio a Trappi. Me gustaría conocer los planes y cómo comenzar.', 'Mensaje predefinido de WhatsApp', 'El texto que ya aparece escrito al abrir WhatsApp desde la web.', 'commercial'),
    Option('new_stores_open', 'bool', True, 'Recibir nuevos comercios', 'Apagado, la web muestra que por ahora no estamos sumando comercios y el botón de WhatsApp no aparece.', 'commercial'),
    Option('plan_comercio_price', 'float', 10000.0, 'Abono mensual del plan Trappi Comercio ($)', '0 % de comisión y cadetes propios. Es el valor que se propone al dar de alta; cada comercio puede tener el suyo.', 'commercial', min=0, max=100_000_000),
    Option('plan_delivery_commission', 'float', 15.0, 'Comisión del plan Trappi Delivery (%)', 'Sin abono y con la flota de Trappi. Se cobra sobre los productos (sin el envío). Es la comisión que se propone al dar de alta; cada comercio puede tener la suya.', 'commercial', min=0, max=100),
]
BY_KEY = {o.key: o for o in OPTIONS}

_cache: dict = {'at': 0.0, 'values': None}
_lock = threading.Lock()
CACHE_SECONDS = 5


def _parse(opt: Option, raw):
    """Valor guardado (texto) -> tipo de la opcion. Ante cualquier cosa rara, el valor por defecto."""
    if raw is None or (raw == '' and opt.kind in ('str', 'url') and opt.default):
        return opt.default
    try:
        if opt.kind == 'bool':
            return str(raw).lower() in ('1', 'true', 'on', 'si', 'sí')
        if opt.kind in ('int', 'float'):
            num = parse_number(str(raw))  # formato argentino: "1.000" es mil, "3,5" es tres y medio
            if num is None:
                return opt.default
            if opt.min is not None: num = max(opt.min, num)
            if opt.max is not None: num = min(opt.max, num)
            return int(num) if opt.kind == 'int' else num
        if opt.kind == 'choice':
            return raw if raw in opt.choices else opt.default
        if opt.kind == 'version':
            return raw if re.fullmatch(r'\d+(\.\d+){0,2}', str(raw)) else opt.default
        return str(raw)
    except (TypeError, ValueError):
        return opt.default


def get_all(db: Session) -> dict:
    with _lock:
        if _cache['values'] is not None and time.monotonic() - _cache['at'] < CACHE_SECONDS:
            return _cache['values']
    rows = dict(db.execute(select(Setting.key, Setting.value).where(Setting.key.in_(list(BY_KEY)))).all())
    values = {o.key: _parse(o, rows.get(o.key)) for o in OPTIONS}
    with _lock:
        _cache.update(at=time.monotonic(), values=values)
    return values


def get(db: Session, key: str):
    return get_all(db)[key]


def invalidate() -> None:
    with _lock:
        _cache.update(at=0.0, values=None)


def save(db: Session, form: dict) -> None:
    """Guarda lo que vino del formulario (los checkbox apagados no vienen: se guardan como apagados). Hace commit."""
    rows = {s.key: s for s in db.scalars(select(Setting).where(Setting.key.in_(list(BY_KEY))))}
    for opt in OPTIONS:
        if opt.kind == 'bool':
            value = '1' if form.get(opt.key) in ('1', 'on', 'true') else '0'
        elif opt.key in form:
            value = str(form[opt.key]).strip()
            parsed = _parse(opt, value if value != '' else None)
            value = '' if value == '' and opt.kind in ('str', 'url') else str(parsed)
        else:
            continue
        if opt.key in rows:
            rows[opt.key].value = value
        else:
            db.add(Setting(key=opt.key, value=value))
    db.commit()
    invalidate()


def map_style_url(values: dict) -> str:
    if values['driver_map_style'] == 'custom' and values['driver_map_style_url'].startswith('https://'):
        return values['driver_map_style_url']
    return MAP_STYLES.get(values['driver_map_style'], MAP_STYLES['liberty'])[1] or MAP_STYLES['liberty'][1]


def app_status(values: dict, app: str) -> dict:
    """Bloque que consultan las apps al abrir: si están activas, la versión mínima y de dónde bajar la nueva."""
    return {'enabled': values[f'app_{app}_enabled'], 'message': values[f'app_{app}_message'] or MAINTENANCE,
            'min_version': values[f'app_{app}_min_version'], 'download_url': values[f'app_{app}_download_url']}


def courier_pay(values: dict, shipping) -> "Decimal":
    """Lo que gana el repartidor por un viaje, según la regla configurada."""
    from decimal import ROUND_HALF_UP, Decimal
    ship = Decimal(str(shipping or 0))
    mode, value = values['courier_pay_mode'], Decimal(str(values['courier_pay_value']))
    if mode == 'fixed':
        pay = value
    elif mode == 'percent':
        pay = ship * value / 100
    else:
        pay = ship
    return max(Decimal('0'), pay).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def current() -> dict:
    """Para plantillas y middlewares que no tienen una sesion a mano (usa la cache)."""
    from ..db import SessionLocal
    with _lock:
        if _cache['values'] is not None and time.monotonic() - _cache['at'] < CACHE_SECONDS:
            return _cache['values']
    with SessionLocal() as db:
        return get_all(db)
