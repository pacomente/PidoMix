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
    'fleet': ('Flota Trappi y cobertura', 'Cuándo opera la flota, qué pasa fuera de cobertura y quién paga el envío. Las zonas y tarifas por km se administran en Logística → Zonas.'),
    'operating': ('Costo operativo de la flota', 'Estimación interna de lo que cuesta cada entrega (no se le cobra al cliente). Sirve para la rentabilidad.'),
    'payouts': ('Pago a repartidores (fórmula de la flota)', 'Se usa cuando "Cuánto gana el repartidor" está en "Fórmula de la flota". Pago = base + km × valor + por entrega + bonos + adicionales.'),
    'cash': ('Efectivo y retiro', 'Límite de efectivo que un repartidor puede tener sin rendir, cómo se le paga al local en los pedidos en efectivo y el código de retiro.'),
    'commissions': ('Comisiones por plan', 'Comisión = % sobre los productos + fijo, con mínimo y máximo opcionales (0 = sin límite). Cada comercio puede tener la suya en su ficha.'),
    'payments': ('Pagos online (Mercado Pago)', 'Las credenciales van en variables de entorno de Render (nunca acá). Cada comercio conecta su cuenta desde "Pagos y liquidaciones".'),
    'clients': ('Clientes y datos legales', 'Cuentas de clientes (entran con Google) y los datos del titular de Trappi que se muestran en los Términos y la Política de Privacidad.'),
    'commercial': ('Configuración comercial', 'Planes de Trappi y cómo te contactan los comercios que se quieren sumar. Los comercios se dan de alta solo desde el panel, después de hablar por WhatsApp.'),
}

# que secciones muestra cada pagina de configuracion
GENERAL_SECTIONS = ('apps', 'clients', 'couriers', 'maps', 'commercial', 'payments')
LOGISTICS_SECTIONS = ('fleet', 'operating', 'payouts', 'cash')
COMMISSION_SECTIONS = ('commissions',)

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
    # --- clientes y datos legales ---
    Option('customer_login_required', 'bool', True, 'Pedir cuenta para hacer pedidos',
           'Prendido, para pedir (web y app) hay que entrar con Google. Solo se aplica si GOOGLE_CLIENT_ID y GOOGLE_CLIENT_SECRET están cargadas en Render.', 'clients'),
    Option('legal_name', 'str', '', 'Titular (razón social o nombre y apellido)', 'Quién es responsable de Trappi y de la base de datos de clientes.', 'clients'),
    Option('legal_cuit', 'str', '', 'CUIT del titular', section='clients'),
    Option('legal_address', 'str', '', 'Domicilio legal', 'Calle, número, ciudad y provincia.', 'clients'),
    Option('legal_email', 'str', '', 'Email para consultas legales y de datos personales', 'Ahí te piden acceso, corrección o baja de sus datos.', 'clients'),
    Option('legal_jurisdiction', 'str', '', 'Ciudad de los tribunales (si no es la del domicilio legal)', 'Ej: Bahía Blanca, provincia de Buenos Aires.', 'clients'),
    # --- repartidores ---
    Option('dispatch_auto', 'bool', True, 'Ofrecer los viajes automáticamente', 'Apagado, ningún viaje se ofrece solo: cada local los asigna desde comandas.', 'couriers'),
    Option('dispatch_offer_seconds', 'int', 35, 'Segundos para aceptar una oferta', section='couriers', min=10, max=120),
    Option('dispatch_radius_km', 'float', 8.0, 'Radio máximo desde el local (km)', 'Repartidores más lejos no reciben la oferta.', 'couriers', min=0.5, max=50),
    Option('dispatch_reoffer_minutes', 'int', 3, 'Volver a ofrecer a quien no respondió después de (minutos)', section='couriers', min=0, max=120),
    Option('dispatch_location_minutes', 'int', 5, 'Ubicación válida durante (minutos)', 'Si la app del repartidor no reporta su ubicación en este tiempo, deja de recibir ofertas.', 'couriers', min=1, max=60),
    Option('courier_pulse_seconds', 'int', 4, 'Cada cuántos segundos la app manda la ubicación', 'Menos segundos = ofertas más rápidas, pero más batería y datos.', 'couriers', min=3, max=30),
    Option('delivery_pin_required', 'bool', True, 'Pedir el PIN de entrega', 'El cliente recibe un PIN de 4 números con su pedido y el repartidor lo tiene que cargar para marcarlo entregado.', 'couriers'),
    Option('courier_pay_mode', 'choice', 'shipping', 'Cuánto gana el repartidor por viaje', section='couriers',
           choices={'shipping': 'El costo de envío completo', 'percent': 'Un porcentaje del costo de envío', 'fixed': 'Un monto fijo por viaje',
                    'formula': 'Fórmula de la flota (base + km + entrega + bonos; ver Logística → Configuración)'}),
    Option('courier_pay_value', 'float', 100.0, 'Porcentaje o monto', 'Con "porcentaje": ej. 80 (= 80 % del envío). Con "monto fijo": ej. 1500.', 'couriers', min=0, max=1_000_000),
    # --- mapas ---
    Option('driver_map_style', 'choice', 'liberty', 'Mapa de la app de repartidores', section='maps', choices={k: v[0] for k, v in MAP_STYLES.items()}),
    Option('driver_map_style_url', 'url', '', 'URL del estilo (si elegiste "Otro proveedor")', 'Ej: un estilo de MapTiler o Stadia con tu clave: https://api.maptiler.com/maps/streets-v2/style.json?key=…', 'maps'),
    Option('web_tiles_url', 'url', 'https://tile.openstreetmap.org/{z}/{x}/{y}.png', 'Mosaicos del mapa de la web', 'Plantilla {z}/{x}/{y} (Leaflet). Con mucho tráfico conviene un proveedor con plan propio.', 'maps'),
    Option('web_tiles_attribution', 'str', '&copy; OpenStreetMap', 'Atribución del mapa de la web', section='maps'),
    Option('geocoder_url', 'url', 'https://nominatim.openstreetmap.org/', 'Buscador de direcciones (Nominatim)', 'URL base de un servidor compatible con Nominatim (/search y /reverse).', 'maps'),
    # --- contacto ---
    # --- flota y cobertura ---
    Option('fleet_active', 'bool', True, 'Flota Trappi activa', 'Apagada, ningún comercio puede elegir "Entrega Trappi" (los que la usan pasan a la regla de fuera de cobertura).', 'fleet'),
    Option('fleet_start_time', 'str', '', 'La flota trabaja desde (HH:MM)', 'Vacío = todo el día. Además, cada zona tiene sus días y horarios.', 'fleet'),
    Option('fleet_end_time', 'str', '', 'La flota trabaja hasta (HH:MM)', section='fleet'),
    Option('out_of_coverage_policy', 'choice', 'pickup', 'Si la dirección está fuera de cobertura de la flota', section='fleet',
           choices={'pickup': 'Ofrecer solo retiro en el local', 'merchant': 'Permitir que entregue el propio comercio (con su envío)', 'reject': 'No permitir el pedido con envío'}),
    Option('delivery_fee_payer', 'choice', 'CUSTOMER', 'Quién paga el envío de la flota (por defecto)', 'Cada comercio puede tener otra regla en su ficha.', 'fleet',
           choices={'CUSTOMER': 'El cliente', 'MERCHANT': 'El comercio (envío gratis para el cliente)', 'TRAPPI': 'Trappi (envío bonificado)', 'SHARED': 'Compartido cliente / comercio'}),
    Option('fee_share_mode', 'choice', 'percent', 'Compartido: cómo se divide', section='fleet', choices={'percent': 'El cliente paga un % del envío', 'amount': 'El cliente paga un monto fijo (el resto, el comercio)'}),
    Option('fee_share_value', 'float', 50.0, 'Compartido: % o monto que paga el cliente', section='fleet', min=0, max=1_000_000),
    Option('routing_fallback', 'choice', 'estimate', 'Si el servicio de rutas no responde', section='fleet',
           choices={'estimate': 'Estimar la distancia (línea recta × factor) y marcarla como estimada', 'reject': 'No ofrecer la flota hasta que vuelva'}),
    Option('routing_detour_factor', 'float', 1.35, 'Factor para estimar la ruta desde la línea recta', 'Solo si el servicio de rutas falla. Ej: 1,35 = la ruta es 35 % más larga que la línea recta.', 'fleet', min=1, max=3),
    Option('fleet_extra_minutes', 'int', 10, 'Minutos extra en la demora estimada de la flota', 'Demora = preparación del local + viaje por ruta + estos minutos.', 'fleet', min=0, max=120),
    # --- costo operativo ---
    Option('operating_cost_per_km', 'float', 0.0, 'Costo operativo estimado por km ($)', 'Sobre el recorrido operativo (cadete → local → cliente).', 'operating', min=0, max=1_000_000),
    Option('operating_cost_min', 'float', 0.0, 'Costo operativo mínimo por viaje ($)', section='operating', min=0, max=1_000_000),
    # --- pago a repartidores ---
    Option('payout_base', 'float', 0.0, 'Pago base por viaje ($)', section='payouts', min=0, max=1_000_000),
    Option('payout_per_km', 'float', 0.0, 'Pago por km ($)', 'Sobre los km facturados local → cliente.', 'payouts', min=0, max=1_000_000),
    Option('payout_per_delivery', 'float', 0.0, 'Pago por entrega ($)', section='payouts', min=0, max=1_000_000),
    Option('payout_night_start', 'str', '', 'Tarifa nocturna desde (HH:MM)', 'Vacío = sin tarifa nocturna.', 'payouts'),
    Option('payout_night_end', 'str', '', 'Tarifa nocturna hasta (HH:MM)', section='payouts'),
    Option('payout_night_bonus', 'float', 0.0, 'Bono nocturno por viaje ($)', section='payouts', min=0, max=1_000_000),
    Option('payout_high_demand', 'bool', False, 'Alta demanda (activar a mano)', 'Prendido, cada viaje suma el bono de alta demanda.', 'payouts'),
    Option('payout_high_demand_bonus', 'float', 0.0, 'Bono de alta demanda por viaje ($)', section='payouts', min=0, max=1_000_000),
    Option('payout_long_km', 'float', 0.0, 'Adicional por viaje largo: desde (km)', '0 = sin adicional.', 'payouts', min=0, max=100),
    Option('payout_long_amount', 'float', 0.0, 'Adicional por viaje largo ($)', section='payouts', min=0, max=1_000_000),
    # --- efectivo ---
    Option('courier_cash_limit', 'float', 50000.0, 'Límite de efectivo por repartidor ($)', 'Efectivo cobrado sin rendir. Al llegar, deja de recibir pedidos en efectivo. Cada repartidor puede tener el suyo.', 'cash', min=0, max=100_000_000),
    Option('cash_block_allows_online', 'bool', True, 'Al llegar al límite puede seguir con pedidos pagados online', section='cash'),
    Option('fleet_cash_pay_store', 'bool', True, 'El cadete de la flota le paga al local al retirar (pedidos en efectivo)',
           'Como en las apps de delivery: el cadete de Trappi le paga al local en efectivo al retirar y después le cobra al cliente los productos más el envío.', 'cash'),
    Option('fleet_cash_store_amount', 'choice', 'products', 'Cuánto le paga el cadete al local', section='cash',
           choices={'products': 'El valor de los productos (la comisión queda en la liquidación del comercio)', 'net': 'Los productos menos la comisión de Trappi'}),
    Option('failed_delivery_pay_courier', 'bool', True, 'Si no se pudo entregar, el cadete cobra el viaje igual',
           'Cuando se cancela un pedido que el cadete de Trappi ya había retirado (por ejemplo, el cliente no atiende), se le paga el viaje.', 'cash'),
    Option('pickup_code_enabled', 'bool', True, 'Código de retiro', 'El cadete le muestra al local un código de 4 números que también sale en la comanda y en el ticket: el local entrega el pedido solo a quien tenga ese código.', 'cash'),
    # --- comisiones por plan ---
    Option('plan_comercio_commission', 'float', 0.0, 'Trappi Comercio: comisión (%)', section='commissions', min=0, max=100),
    Option('commission_comercio_fixed', 'float', 0.0, 'Trappi Comercio: comisión fija por venta ($)', section='commissions', min=0, max=1_000_000),
    Option('commission_comercio_min', 'float', 0.0, 'Trappi Comercio: comisión mínima ($)', section='commissions', min=0, max=1_000_000),
    Option('commission_comercio_max', 'float', 0.0, 'Trappi Comercio: comisión máxima ($, 0 = sin tope)', section='commissions', min=0, max=100_000_000),
    Option('commission_delivery_fixed', 'float', 0.0, 'Trappi Delivery: comisión fija por venta ($)', 'El % está en Configuración comercial.', 'commissions', min=0, max=1_000_000),
    Option('commission_delivery_min', 'float', 0.0, 'Trappi Delivery: comisión mínima ($)', section='commissions', min=0, max=1_000_000),
    Option('commission_delivery_max', 'float', 0.0, 'Trappi Delivery: comisión máxima ($, 0 = sin tope)', section='commissions', min=0, max=100_000_000),
    # --- pagos online ---
    Option('mp_enabled', 'bool', True, 'Ofrecer pago con Mercado Pago', 'Solo aparece en los comercios que conectaron su cuenta y si las credenciales están cargadas en el servidor.', 'payments'),
    Option('online_payment_minutes', 'int', 30, 'Minutos para pagar antes de que se cancele el pedido', section='payments', min=5, max=1440),
    # --- comercial (planes, alta de comercios) ---
    Option('platform_whatsapp', 'str', '', 'WhatsApp de contacto comercial', 'Abre el botón "Sumá tu comercio" de la web y "Solicitar cambio de plan" del panel de cada local (sin espacios ni +, ej: 5492911234567). También es el contacto de soporte de las apps.', 'commercial'),
    Option('commercial_message', 'str', 'Hola, quiero sumar mi comercio a Trappi. Me gustaría conocer los planes y cómo comenzar.', 'Mensaje predefinido de WhatsApp', 'El texto que ya aparece escrito al abrir WhatsApp desde la web.', 'commercial'),
    Option('new_stores_open', 'bool', True, 'Recibir nuevos comercios', 'Apagado, la web muestra que por ahora no estamos sumando comercios y el botón de WhatsApp no aparece.', 'commercial'),
    Option('plan_comercio_price', 'float', 10000.0, 'Abono mensual del plan Trappi Comercio ($)', '0 % de comisión y cadetes propios. Es el valor que se propone al dar de alta; cada comercio puede tener el suyo.', 'commercial', min=0, max=100_000_000),
    Option('plan_delivery_commission', 'float', 15.0, 'Comisión del plan Trappi Delivery (%)', 'Sin abono y con la flota de Trappi. Se cobra sobre los productos (sin el envío). Es la comisión que se propone al dar de alta; cada comercio puede tener la suya.', 'commercial', min=0, max=100),
]
BY_KEY = {o.key: o for o in OPTIONS}
# lo que cada ciudad puede tener distinto (vacio: el valor general). Se guarda como "city.<id>.<clave>".
CITY_KEYS = tuple(o.key for o in OPTIONS if o.section in LOGISTICS_SECTIONS) + (
    'courier_pay_mode', 'courier_pay_value', 'dispatch_radius_km', 'plan_delivery_commission', 'plan_comercio_price')
CITY_PREFIX = 'city.'

_cache: dict = {'at': 0.0, 'values': None, 'cities': {}}
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


def _load(db: Session) -> None:
    rows = dict(db.execute(select(Setting.key, Setting.value).where(Setting.key.in_(list(BY_KEY)))).all())
    values = {o.key: _parse(o, rows.get(o.key)) for o in OPTIONS}
    by_city: dict[int, dict] = {}
    for key, raw in db.execute(select(Setting.key, Setting.value).where(Setting.key.like(CITY_PREFIX + '%'))).all():
        try:
            _, cid, name = key.split('.', 2)
            if name in CITY_KEYS:
                by_city.setdefault(int(cid), {})[name] = _parse(BY_KEY[name], raw)
        except ValueError:
            continue
    with _lock:
        _cache.update(at=time.monotonic(), values=values, cities=by_city)


def get_all(db: Session) -> dict:
    """La configuracion general (sin lo propio de cada ciudad)."""
    with _lock:
        if _cache['values'] is not None and time.monotonic() - _cache['at'] < CACHE_SECONDS:
            return _cache['values']
    _load(db)
    return _cache['values']


def city_overrides(db: Session, city_id: int | None) -> dict:
    """Lo que la ciudad tiene distinto de la configuracion general."""
    get_all(db)
    return dict(_cache.get('cities', {}).get(city_id, {})) if city_id else {}


def for_city(db: Session, city_id: int | None) -> dict:
    """Configuracion que rige en una ciudad: la general con lo propio de la ciudad encima."""
    base = get_all(db)
    own = city_overrides(db, city_id)
    return {**base, **own} if own else base


def save_city(db: Session, city_id: int, form: dict) -> dict:
    """Guarda lo propio de una ciudad. Por cada clave: inherit_<clave> marcado = usa la general (se borra).
    Devuelve {clave: (antes, despues)} para la auditoria. Hace commit."""
    before = for_city(db, city_id)
    rows = {s.key: s for s in db.scalars(select(Setting).where(Setting.key.like(f'{CITY_PREFIX}{city_id}.%')))}
    for key in CITY_KEYS:
        opt, name = BY_KEY[key], f'{CITY_PREFIX}{city_id}.{key}'
        if form.get(f'inherit_{key}') in ('1', 'on', 'true'):
            if name in rows:
                db.delete(rows[name])
            continue
        if opt.kind == 'bool':
            value = '1' if form.get(key) in ('1', 'on', 'true') else '0'
        elif key in form and str(form[key]).strip() != '':
            value = str(_parse(opt, str(form[key]).strip()))
        else:
            continue
        if name in rows:
            rows[name].value = value
        else:
            db.add(Setting(key=name, value=value))
    db.commit()
    invalidate()
    after = for_city(db, city_id)
    return {k: (before[k], after[k]) for k in CITY_KEYS if before[k] != after[k]}


def get(db: Session, key: str):
    return get_all(db)[key]


def invalidate() -> None:
    with _lock:
        _cache.update(at=0.0, values=None)


def save(db: Session, form: dict, sections: set[str] | None = None) -> dict:
    """Guarda lo que vino del formulario (los checkbox apagados no vienen: se guardan como apagados). Hace commit.
    Con sections, solo toca las opciones de esas secciones (paginas que muestran una parte).
    Devuelve {clave: (antes, despues)} de lo que cambio, para la auditoria."""
    rows = {s.key: s for s in db.scalars(select(Setting).where(Setting.key.in_(list(BY_KEY))))}
    before = get_all(db)
    changed = {}
    for opt in OPTIONS:
        if sections is not None and opt.section not in sections:
            continue
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
        new_value = _parse(opt, value if value != '' else None)
        if new_value != before[opt.key]:
            changed[opt.key] = (before[opt.key], new_value)
    db.commit()
    invalidate()
    return changed


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
