"""Estilo del repartidor en el mapa: elige un personaje y un color en la app.

Se ve en su mapa y en el seguimiento del cliente. Algunos personajes se desbloquean con entregas hechas
(lo cuenta el servidor: la app no puede elegir uno bloqueado).
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Courier, Order, OrderStatus

# (clave, emoji, nombre, entregas para desbloquearlo)
AVATARS = [
    ('gato', '🐱', 'Gato', 0), ('perro', '🐶', 'Perro', 0), ('zorro', '🦊', 'Zorro', 0), ('rana', '🐸', 'Rana', 0),
    ('panda', '🐼', 'Panda', 0), ('moto', '🛵', 'Moto', 0), ('bici', '🚲', 'Bici', 0), ('rayo', '⚡', 'Rayo', 0),
    ('cohete', '🚀', 'Cohete', 25), ('alien', '👽', 'Alien', 50), ('tigre', '🐯', 'Tigre', 50),
    ('unicornio', '🦄', 'Unicornio', 100), ('dragon', '🐉', 'Dragón', 250), ('corona', '👑', 'Corona', 500),
]
COLORS = [
    ('violeta', '#8B5CF6'), ('rosa', '#FF6FB5'), ('menta', '#2EE59D'), ('amarillo', '#FFD43B'),
    ('celeste', '#38BDF8'), ('naranja', '#FF8A00'), ('rojo', '#F43F5E'),
]
_AV = {k: (e, n, need) for k, e, n, need in AVATARS}
_COL = dict(COLORS)
DEFAULT_COLOR = 'violeta'


def delivered(db: Session, c: Courier) -> int:
    return db.scalar(select(func.count(Order.id)).where(Order.courier_id == c.id, Order.status == OrderStatus.ENTREGADO)) or 0


def public(c: Courier | None) -> dict:
    """Lo que ve el cliente en el seguimiento (y la app en su mapa): emoji y color, o None si no eligió."""
    if c is None or c.avatar not in _AV:
        return {'avatar': None, 'color': None}
    return {'avatar': _AV[c.avatar][0], 'color': _COL.get(c.avatar_color or DEFAULT_COLOR, _COL[DEFAULT_COLOR])}


def catalog(db: Session, c: Courier) -> dict:
    done = delivered(db, c)
    return {
        'avatar': c.avatar if c.avatar in _AV else None,
        'color': c.avatar_color if c.avatar_color in _COL else DEFAULT_COLOR,
        'delivered': done,
        'avatars': [{'key': k, 'emoji': e, 'label': n, 'unlock': need, 'locked': done < need} for k, e, n, need in AVATARS],
        'colors': [{'key': k, 'hex': h} for k, h in COLORS],
    }


def choose(db: Session, c: Courier, avatar: str | None, color: str | None) -> str | None:
    """Guarda el estilo. Devuelve un error para mostrar, o None si salió bien. avatar vacío: vuelve al punto de siempre."""
    if avatar and avatar not in _AV:
        return 'Ese personaje no existe.'
    if color and color not in _COL:
        return 'Ese color no existe.'
    if avatar:
        need = _AV[avatar][2]
        if need and delivered(db, c) < need:
            return f'Lo desbloqueás con {need} entregas.'
    c.avatar = avatar or None
    c.avatar_color = color or DEFAULT_COLOR
    return None
