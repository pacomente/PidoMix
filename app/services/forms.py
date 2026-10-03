"""Campos numericos de los formularios del panel.

Un input vacio llega como "" y FastAPI lo rechaza como numero (error 422 con JSON crudo).
Estos helpers lo toman como "sin valor" y aceptan coma decimal ("12,5").
"""


def form_float(value: str | None, default: float | None = None) -> float | None:
    text = (value or '').strip().replace('.', '').replace(',', '.') if ',' in (value or '') else (value or '').strip()
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def form_int(value: str | None, default: int | None = None) -> int | None:
    number = form_float(value)
    return int(number) if number is not None else default
