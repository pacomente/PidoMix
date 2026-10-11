"""Asistente de voz del repartidor: el cadete aprieta el botón, habla, y la app le contesta en voz alta.

Permisos acotados: el asistente solo puede hacer estas cosas, y todas las ejecuta el backend validando
que el viaje sea suyo (como si tocara el botón):
  estado      cuánto falta, a dónde va, qué cobra
  ganancias   cuánto ganó hoy
  ir_zona     llevarlo a la zona con pedidos esperando (la app traza la ruta)
  avisar      mandarle un mensaje al cliente o al local por el chat del pedido
  llegue      marcar "Llegué" (valida el GPS)
  abrir_chat  abrir el chat
  silencio / voz   apagar o prender las indicaciones habladas
Primero se reconoce la frase con reglas (rápido y sin depender de la IA); si no se entiende y hay un
modelo configurado, se le pide al modelo SOLO que diga cuál de esas acciones es (no puede inventar otras).
"""
import json
import logging
import re
import unicodedata

from ..services import delivery_safety, demand, dispatch, payments, routing
from ..services.formatting import money
from ..services.geo import distance_km
from ..models import OrderStatus

log = logging.getLogger('pidomix.ai.courier')
MAX_TEXT = 300
INTENTS = ('estado', 'ganancias', 'ir_zona', 'avisar', 'llegue', 'abrir_chat', 'silencio', 'voz', 'ayuda')
HELP = 'Podés decirme: cuánto falta, cuánto gané hoy, llevame a la zona con pedidos, avisale al cliente que llego en cinco minutos, o llegué.'
NUMBERS = {'un': 1, 'uno': 1, 'una': 1, 'dos': 2, 'tres': 3, 'cuatro': 4, 'cinco': 5, 'seis': 6, 'siete': 7, 'ocho': 8, 'nueve': 9, 'diez': 10,
           'quince': 15, 'veinte': 20, 'media hora': 30}


def norm(text: str) -> str:
    t = unicodedata.normalize('NFD', (text or '').lower())
    return re.sub(r'\s+', ' ', ''.join(c for c in t if unicodedata.category(c) != 'Mn')).strip()


def minutes_in(t: str) -> int | None:
    m = re.search(r'(\d{1,2})\s*(?:min|minuto)', t)
    if m:
        return int(m.group(1))
    for word, n in NUMBERS.items():
        if re.search(rf'\b{word}\b(?:\s*min|\s*minuto)', t) or (word == 'media hora' and word in t):
            return n
    return None


def classify(text: str) -> dict:
    """Reglas para las frases más comunes. Devuelve {'intent': ..., 'to': ..., 'minutes': ..., 'text': ...} o intent None."""
    t = norm(text)
    if not t:
        return {'intent': None}
    if re.search(r'\b(silencio|callate|calla|mute|no hables|sin voz)\b', t):
        return {'intent': 'silencio'}
    if re.search(r'\b(habla|hablame|con voz|activa la voz|prende la voz)\b', t):
        return {'intent': 'voz'}
    if re.search(r'\b(ayuda|que podes hacer|que sabes hacer)\b', t):
        return {'intent': 'ayuda'}
    if re.search(r'\b(avisa|avisale|decile|mandale|escribile|manda un mensaje|deci)\b', t):
        to = 'local' if re.search(r'\b(local|comercio|negocio|restaurante|cocina)\b', t) else 'cliente'
        mins = minutes_in(t)
        free = re.split(r'\b(?:que|diciendo)\b', text, maxsplit=1, flags=re.I)  # del texto original: con tildes
        return {'intent': 'avisar', 'to': to, 'minutes': mins, 'text': free[1].strip(' ,.') if len(free) > 1 else ''}
    if re.search(r'\b(llegue|ya llegue|estoy en la puerta|estoy en la casa|estoy abajo)\b', t):
        return {'intent': 'llegue'}
    if re.search(r'\b(gane|ganancia|ganancias|cuanto llevo|cuanta plata)\b', t):
        return {'intent': 'ganancias'}
    if re.search(r'\b(zona|pedidos esperando|donde hay pedidos|demanda|donde conviene|llevame donde)\b', t):
        return {'intent': 'ir_zona'}
    if re.search(r'\b(chat|mensajes)\b', t):
        return {'intent': 'abrir_chat', 'to': 'local' if 'local' in t else 'cliente'}
    if re.search(r'\b(cuanto falta|cuanto me falta|cuanto tardo|a donde voy|adonde voy|direccion|donde queda|cuanto cobro|que cobro|tengo que cobrar|estado|en que va)\b', t):
        return {'intent': 'estado'}
    return {'intent': None}


def classify_ai(text: str) -> dict:
    """Si las reglas no lo entendieron: el modelo solo elige una de las acciones permitidas (sin herramientas)."""
    from . import providers
    p = providers.get_provider()
    if p is None:
        return {'intent': None}
    prompt = ('Sos el clasificador del asistente de voz de un repartidor. Respondé SOLO un JSON con las claves intent, to, minutes, text. '
              f'intent es una de: {", ".join(INTENTS)}. to es "cliente" o "local" (solo para avisar o abrir_chat). minutes es un número o null. '
              'text es el mensaje a mandar (solo para avisar), corto y en español rioplatense. Si no corresponde ninguna, intent "ayuda".')
    try:
        reply = p.chat([{'role': 'system', 'content': prompt}, {'role': 'user', 'content': text[:MAX_TEXT]}], [])
        data = json.loads(re.search(r'\{.*\}', reply.text or '', re.S).group(0))
    except Exception as exc:  # modelo apagado, lento o respuesta rara: se pide que lo repita
        log.info('Clasificacion IA no disponible: %s', exc)
        return {'intent': None}
    intent = data.get('intent') if data.get('intent') in INTENTS else None
    return {'intent': intent, 'to': 'local' if data.get('to') == 'local' else 'cliente',
            'minutes': data.get('minutes') if isinstance(data.get('minutes'), int) else None, 'text': str(data.get('text') or '')[:200]}


def spoken_km(km: float) -> str:
    return f'{int(round(km * 1000, -1))} metros' if km < 1 else f'{str(round(km, 1)).replace(".", ",")} kilómetros'


def handle(db, courier, text: str, lat: float | None, lng: float | None) -> dict:
    """Una frase del repartidor -> {'reply': lo que dice la app en voz alta, 'action': lo que hace la app (o None)}."""
    text = (text or '').strip()[:MAX_TEXT]
    c = classify(text)
    if c['intent'] is None:
        c = classify_ai(text)
    intent = c.get('intent')
    trip = dispatch.current_trip(db, courier)
    me = (lat, lng) if lat is not None and lng is not None else (courier.lat, courier.lng)

    if intent in (None, 'ayuda'):
        return {'reply': ('No te entendí. ' if intent is None else '') + HELP, 'action': None}
    if intent == 'silencio':
        return {'reply': 'Listo, no te hablo más. Decime "hablá" para volver a escucharme.', 'action': {'type': 'mute'}}
    if intent == 'voz':
        return {'reply': 'Listo, te voy diciendo las indicaciones.', 'action': {'type': 'unmute'}}
    if intent == 'ganancias':
        from ..routers.courier_api import earnings_json  # import tardio: el router importa este modulo
        e = earnings_json(db, courier)
        return {'reply': f"Hoy llevás {money(e['today'])} en {e['trips_today']} {'viaje' if e['trips_today'] == 1 else 'viajes'}.", 'action': None}
    if intent == 'ir_zona':
        if trip:
            return {'reply': 'Primero terminá el viaje que tenés en curso.', 'action': None}
        s = demand.for_courier(db, courier, busy=False)['suggestion']
        if not s:
            return {'reply': 'Ahora no hay una zona con pedidos esperando. Quedate conectado y te aviso.', 'action': None}
        return {'reply': f"Vamos. {s['text']}.", 'action': {'type': 'navigate_suggestion'}}

    if trip is None:
        return {'reply': 'No tenés un viaje en curso.', 'action': None}
    picked = trip.status == OrderStatus.EN_CAMINO
    who = trip.customer.first_name if trip.customer and trip.customer.first_name else 'el cliente'

    if intent == 'abrir_chat':
        return {'reply': 'Abro el chat.', 'action': {'type': 'open_chat', 'thread': c.get('to') or ('cliente' if picked else 'local')}}
    if intent == 'llegue':
        if not picked:
            return {'reply': 'Todavía no retiraste el pedido. Cuando llegues al local, pedile el pedido.', 'action': None}
        try:
            delivery_safety.arrival(db, courier, trip, lat, lng)
        except delivery_safety.SafetyError as exc:
            return {'reply': str(exc), 'action': None}
        db.commit()
        from ..services import push
        push.notify_order(db, trip, 'Tu repartidor llegó 🛵', f'{courier.name.split()[0]} te está esperando en la puerta con tu pedido #{trip.id}.', 'llego')
        return {'reply': f'Listo, le avisé a {who} que llegaste. Si en {delivery_safety.cfg_for(db, trip)["noshow_wait_minutes"]} minutos no sale, podés cancelar con una foto.',
                'action': {'type': 'refresh'}}
    if intent == 'avisar':
        thread = c.get('to') or 'cliente'
        mins = c.get('minutes')
        if mins:
            body = f'Llego en {mins} minutos.' if thread == 'cliente' else f'Llego al local en {mins} minutos.'
        else:
            body = (c.get('text') or '').strip().rstrip('.')
            body = (body[:1].upper() + body[1:] + '.') if body else ('Ya estoy llegando.' if thread == 'cliente' else 'Voy para el local.')
        try:
            delivery_safety.post(db, trip, thread, 'courier', body)
        except delivery_safety.SafetyError as exc:
            return {'reply': str(exc), 'action': None}
        db.commit()
        from ..services import push
        if thread == 'cliente':
            push.notify_order(db, trip, f'Mensaje de {courier.name.split()[0]} (tu repartidor)', body, 'chat')
        return {'reply': f'Listo, le mandé a {who if thread == "cliente" else "el local"}: {body}', 'action': None}

    # estado: a dónde va, cuánto falta y qué cobra
    dest = (trip.lat, trip.lng) if picked else (trip.store.lat, trip.store.lng)
    place = (trip.address or 'la dirección del cliente') if picked else trip.store.name
    parts = [f'Vas a {place}.']
    if me[0] is not None and dest[0] is not None:
        d = routing.service.directions(me, dest)
        if d:
            parts.append(f"Faltan {spoken_km(d['km'])}, unos {max(1, round(d['minutes']))} minutos.")
        else:
            parts.append(f'Estás a {spoken_km(distance_km(me[0], me[1], dest[0], dest[1]))} en línea recta.')
    collect = payments.to_collect(trip)
    if picked:
        parts.append(f'Cobrás {money(collect)} en efectivo.' if collect else 'Ya está pagado: no cobres nada.')
    else:
        from ..routers.courier_api import store_payment
        pay = store_payment(db, trip, courier)
        if pay:
            parts.append(f'Al retirar le pagás {money(pay)} al local.')
    return {'reply': ' '.join(parts), 'action': None}
