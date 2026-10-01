"""Formatos compartidos por el panel y la tienda publica."""
from decimal import Decimal
import unicodedata
import zlib


def money(value) -> str:
    """Formato argentino: $166.500 (o $1.234,50 cuando hay centavos)."""
    amount = Decimal(str(value or 0))
    text = f'{abs(amount):,.0f}' if amount == amount.to_integral_value() else f'{abs(amount):,.2f}'
    text = text.replace(',', 'X').replace('.', ',').replace('X', '.')
    return ('-$' if amount < 0 else '$') + text


# Palabra clave (sin tildes, en minuscula) -> emoji. Se usa cuando el local o el producto no tiene foto.
_EMOJI = [
    ('hamburg', '🍔'), ('burger', '🍔'), ('pizz', '🍕'), ('empanad', '🥟'), ('papas', '🍟'), ('aros', '🧅'),
    ('helad', '🍦'), ('paleta', '🍦'), ('postre', '🍰'), ('torta', '🍰'), ('medialuna', '🥐'), ('panader', '🥐'), ('pan ', '🥖'),
    ('cafe', '☕'), ('flat white', '☕'), ('te ', '🍵'), ('cerveza', '🍺'), ('vino', '🍷'),
    ('bebida', '🥤'), ('gaseosa', '🥤'), ('coca', '🥤'), ('agua', '💧'), ('jugo', '🧃'), ('leche', '🥛'), ('yerba', '🧉'),
    ('sushi', '🍣'), ('combo', '🍱'), ('carne', '🥩'), ('parrilla', '🥩'), ('pollo', '🍗'), ('veggie', '🥗'), ('ensalada', '🥗'),
    ('farmac', '💊'), ('ibuprofeno', '💊'), ('protector', '🧴'), ('perfum', '🧴'),
    ('almacen', '🛒'), ('mercado', '🛒'), ('super', '🛒'), ('kiosco', '🍬'), ('verduler', '🥕'), ('fruta', '🍎'),
    ('librer', '📚'), ('flor', '💐'), ('mascota', '🐾'), ('heladeria', '🍦'), ('cafeteria', '☕'), ('restaurante', '🍽️'),
]
# Fondos suaves para portadas sin foto (siempre el mismo para el mismo nombre)
_HUES = (262, 328, 18, 158, 204, 42, 290)


def _plain(text: str) -> str:
    text = unicodedata.normalize('NFKD', text or '').encode('ascii', 'ignore').decode().lower()
    return f' {text} '


def visual(*names, default='🏪') -> dict:
    """{'emoji': ..., 'hue': ...} para dibujar un placeholder lindo a partir de nombres (rubro, producto, local)."""
    for name in names:
        plain = _plain(name)
        for key, emoji in _EMOJI:
            if ' ' + key in plain:  # solo al comienzo de una palabra ("te" no matchea "restaurante")
                break
        else:
            continue
        break
    else:
        emoji = default
    seed = next((n for n in names if n), '') or 'trappi'
    return {'emoji': emoji, 'hue': _HUES[zlib.crc32(seed.encode()) % len(_HUES)]}
