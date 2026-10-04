"""Campos numericos de los formularios del panel.

Un input vacio llega como "" y FastAPI lo rechaza como numero (error 422 con JSON crudo).
Estos helpers lo toman como "sin valor" y entienden los importes como se escriben en Argentina:
"18.800" es dieciocho mil ochocientos, "1.500,50" lleva centavos y "12,5" es doce con cincuenta.
"""
import re

from fastapi.exceptions import RequestValidationError

_THOUSANDS = re.compile(r'^\d{1,3}(\.\d{3})+$')


def parse_number(value: str | None) -> float | None:
    text = re.sub(r'[\s$]', '', value or '')
    if not text:
        return None
    if ',' in text:  # la coma es el decimal y los puntos separan miles
        text = text.replace('.', '').replace(',', '.')
    elif _THOUSANDS.match(text):  # "18.800" o "1.250.000": puntos de miles, sin decimales
        text = text.replace('.', '')
    try:
        return float(text)
    except ValueError:
        return None


def form_float(value: str | None, default: float | None = None) -> float | None:
    number = parse_number(value)
    return default if number is None else number


def form_int(value: str | None, default: int | None = None) -> int | None:
    number = parse_number(value)
    return default if number is None else int(number)


def required_float(value: str | None, field: str) -> float:
    """Para campos obligatorios: si no se entiende, el usuario ve "Revisá: <campo>"."""
    number = parse_number(value)
    if number is None:
        raise RequestValidationError([{'type': 'float_parsing', 'loc': ('body', field), 'msg': 'Número inválido', 'input': value}])
    return number
