"""Herramientas que el modelo puede pedir. Es lo UNICO que la IA puede hacer en Trappi.

    Cliente -> Trappi AI (modelo) -> herramienta (esta capa) -> servicios de Trappi -> base de datos

- El modelo nunca toca la base: elige una herramienta y argumentos; el backend valida todo
  (usuario, permisos, que el comercio y el producto existan y esten disponibles, precio actual,
  cantidades, que el pedido sea del usuario) y devuelve solo datos reales.
- Cada herramienta declara para quien es (audience): hoy 'cliente'; mas adelante 'comercio',
  'repartidor' y 'admin' se agregan con su propio contexto y permisos, sin cambiar el asistente.
- Lo que una herramienta devuelve vuelve al modelo como datos (JSON). Tambien puede sumar
  tarjetas (comercios y productos reales) que la app muestra debajo de la respuesta.
"""
import json
from dataclasses import dataclass, field
from typing import Callable

from sqlalchemy.orm import Session


class ToolError(Exception):
    """Algo que el modelo tiene que saber (y contarle al usuario): producto agotado, local cerrado..."""


@dataclass
class ToolContext:
    db: Session
    audience: str = 'cliente'
    account: object | None = None  # ClientAccount del usuario autenticado (o None)
    loc: dict | None = None  # ubicacion que compartio el cliente (la usa solo el backend)
    city_id: int | None = None
    cart: list[dict] = field(default_factory=list)  # lineas {product_id, quantity, modifiers}
    cart_changed: bool = False
    cards: list[dict] = field(default_factory=list)  # tarjetas para la app/web
    store_user: object | None = None  # (segunda etapa) usuario del panel de un comercio

    def add_card(self, card: dict) -> None:
        key = (card.get('type'), card.get('id'))
        if key not in {(c.get('type'), c.get('id')) for c in self.cards} and len(self.cards) < 12:
            self.cards.append(card)


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    fn: Callable[..., object]
    audience: str = 'cliente'
    needs_account: bool = False

    def schema(self) -> dict:
        return {'name': self.name, 'description': self.description, 'parameters': self.parameters}


REGISTRY: dict[str, Tool] = {}


def tool(name: str, description: str, properties: dict | None = None, required: list[str] | None = None, *,
         audience: str = 'cliente', needs_account: bool = False):
    def register(fn):
        REGISTRY[name] = Tool(name, description, {'type': 'object', 'properties': properties or {}, 'required': required or []},
                              fn, audience, needs_account)
        return fn
    return register


def available(audience: str) -> list[Tool]:
    return [t for t in REGISTRY.values() if t.audience == audience]


MAX_RESULT_CHARS = 6000


def run(ctx: ToolContext, name: str, arguments: dict) -> str:
    """Ejecuta una herramienta pedida por el modelo y devuelve el resultado como JSON (siempre, aun con error)."""
    t = REGISTRY.get(name)
    if t is None or t.audience != ctx.audience:
        result = {'error': f'La herramienta "{name}" no existe.'}
    elif t.needs_account and ctx.account is None:
        result = {'error': 'El usuario no inició sesión. Pedile que entre con su cuenta (pestaña Cuenta) para ver sus pedidos.'}
    else:
        try:
            result = t.fn(ctx, **_clean_args(t, arguments))
        except ToolError as exc:
            result = {'error': str(exc)}
        except (TypeError, ValueError):
            result = {'error': 'Argumentos inválidos para esta herramienta.'}
    text = json.dumps(result, ensure_ascii=False, default=str)
    return text if len(text) <= MAX_RESULT_CHARS else text[:MAX_RESULT_CHARS] + '…(recortado)'


def _clean_args(t: Tool, arguments: dict) -> dict:
    """Solo los argumentos declarados (el modelo puede inventar otros)."""
    allowed = set(t.parameters['properties'])
    return {k: v for k, v in (arguments or {}).items() if k in allowed and v is not None}
