"""Cargar el menú de un local desde una planilla (CSV que se exporta desde Excel o Google Sheets).

Columnas (se aceptan varios nombres, en cualquier orden; la primera fila son los títulos):
  nombre / producto       obligatorio
  precio                  obligatorio ("$1.500", "1500,50", "1500.5")
  sección / categoría     opcional: se crea si no existe
  descripción             opcional
  precio anterior         opcional (para mostrar la oferta tachada)

Primero se muestra una vista previa con lo que se va a hacer en cada fila. Al confirmar se vuelve a leer y
validar todo en el servidor. Si ya hay un producto con el mismo nombre en el local se actualiza (precio,
descripción y sección), no se duplica. Nunca borra productos.
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Product, Store, StoreSection

MAX_ROWS = 1000
MAX_BYTES = 2 * 1024 * 1024
HEADERS = {
    'name': ('nombre', 'producto', 'productos', 'articulo', 'item', 'name', 'plato'),
    'price': ('precio', 'precio de venta', 'importe', 'valor', 'price', 'pvp'),
    'section': ('seccion', 'categoria', 'rubro', 'grupo', 'section', 'category'),
    'description': ('descripcion', 'detalle', 'ingredientes', 'description'),
    'previous_price': ('precio anterior', 'antes', 'precio tachado', 'precio lista', 'previous price'),
}


class ImportError_(Exception):
    pass


@dataclass
class Row:
    line: int
    name: str
    price: Decimal | None
    section: str = ''
    description: str = ''
    previous_price: Decimal | None = None
    errors: list[str] = field(default_factory=list)
    action: str = ''  # crear | actualizar

    @property
    def ok(self) -> bool:
        return not self.errors


def _plain(text: str) -> str:
    text = unicodedata.normalize('NFD', (text or '').strip().lower())
    return ' '.join(''.join(ch for ch in text if unicodedata.category(ch) != 'Mn').replace('_', ' ').split())


def parse_money(raw: str) -> Decimal | None:
    """'$ 1.500,50' -> 1500.50 · '1500.5' -> 1500.5 · '1,500.50' -> 1500.50. None si no es un número."""
    s = re.sub(r'[^\d.,-]', '', raw or '')
    if not s or s in '-.,':
        return None
    if ',' in s and '.' in s:  # el último separador es el de los decimales
        s = s.replace('.', '').replace(',', '.') if s.rfind(',') > s.rfind('.') else s.replace(',', '')
    elif ',' in s:
        head, _, tail = s.rpartition(',')
        s = (head.replace(',', '') + '.' + tail) if len(tail) in (1, 2) else s.replace(',', '')
    elif s.count('.') == 1 and len(s.rpartition('.')[2]) == 3:
        s = s.replace('.', '')  # 1.500 = mil quinientos
    elif s.count('.') > 1:
        s = s.replace('.', '')
    try:
        v = Decimal(s)
    except InvalidOperation:
        return None
    return v.quantize(Decimal('0.01')) if v >= 0 else None


def _decode(data: bytes) -> str:
    for enc in ('utf-8-sig', 'cp1252', 'latin-1'):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ImportError_('No pudimos leer el archivo. Guardalo como CSV (UTF-8) y probá de nuevo.')


def _columns(header: list[str]) -> dict[str, int]:
    cols = {}
    plain = [_plain(h) for h in header]
    for exact in (True, False):  # primero los títulos exactos ("precio"), después los que empiezan igual ("precio final")
        for key, names in HEADERS.items():
            if key in cols:
                continue
            for i, h in enumerate(plain):
                if i not in cols.values() and (h in names if exact else any(h.startswith(n) for n in names)):
                    cols[key] = i
                    break
    return cols


def parse(data: bytes) -> list[Row]:
    if not data:
        raise ImportError_('El archivo está vacío.')
    if len(data) > MAX_BYTES:
        raise ImportError_('El archivo es muy grande (máximo 2 MB).')
    if data[:4] == b'PK\x03\x04':
        raise ImportError_('Ese archivo es un Excel (.xlsx). En Excel: Archivo → Guardar como → CSV, y subí ese.')
    text = _decode(data)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=';,\t')
    except csv.Error:
        class dialect(csv.excel):  # noqa: N801
            delimiter = ';' if text.count(';') > text.count(',') else ','
    rows = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise ImportError_('La planilla tiene que tener una fila de títulos y al menos un producto.')
    cols = _columns(rows[0])
    if 'name' not in cols or 'price' not in cols:
        raise ImportError_('No encontramos las columnas "nombre" y "precio" en la primera fila. Bajá la planilla modelo para ver el formato.')
    if len(rows) - 1 > MAX_ROWS:
        raise ImportError_(f'Son muchos productos de una vez (máximo {MAX_ROWS}). Partí la planilla en dos.')
    get = lambda r, k: (r[cols[k]].strip() if k in cols and cols[k] < len(r) else '')  # noqa: E731
    out, seen = [], set()
    for n, r in enumerate(rows[1:], start=2):
        name = ' '.join(get(r, 'name').split())[:160]
        price_raw = get(r, 'price')
        row = Row(line=n, name=name, price=parse_money(price_raw), section=' '.join(get(r, 'section').split())[:120],
                  description=' '.join(get(r, 'description').split())[:1000], previous_price=parse_money(get(r, 'previous_price')))
        if not name:
            row.errors.append('Falta el nombre')
        if row.price is None:
            row.errors.append(f'Precio inválido ("{price_raw[:20]}")' if price_raw else 'Falta el precio')
        elif row.price > Decimal('100000000'):
            row.errors.append('Precio demasiado alto')
        if row.previous_price is not None and row.price is not None and row.previous_price <= row.price:
            row.previous_price = None  # el precio anterior solo sirve si era más caro
        key = _plain(name)
        if name and key in seen:
            row.errors.append('Está repetido en la planilla')
        seen.add(key)
        out.append(row)
    return out


def plan(db: Session, store: Store, rows: list[Row]) -> list[Row]:
    """Marca qué se hace con cada fila: crear o actualizar (mismo nombre en el local)."""
    existing = {_plain(p.name) for p in db.scalars(select(Product).where(Product.store_id == store.id, Product.deleted.is_(False)))}
    for r in rows:
        if r.ok:
            r.action = 'actualizar' if _plain(r.name) in existing else 'crear'
    return rows


def apply(db: Session, store: Store, rows: list[Row]) -> dict:
    """Crea o actualiza los productos válidos. No hace commit. Devuelve cuántos de cada uno."""
    products = {_plain(p.name): p for p in db.scalars(select(Product).where(Product.store_id == store.id, Product.deleted.is_(False)))}
    sections = {_plain(s.name): s for s in db.scalars(select(StoreSection).where(StoreSection.store_id == store.id))}
    next_order = (db.scalar(select(func.max(StoreSection.display_order)).where(StoreSection.store_id == store.id)) or 0) + 1
    order = (db.scalar(select(func.max(Product.display_order)).where(Product.store_id == store.id)) or 0) + 1
    created = updated = skipped = 0
    for r in rows:
        if not r.ok:
            skipped += 1
            continue
        section = None
        if r.section:
            section = sections.get(_plain(r.section))
            if section is None:
                section = StoreSection(store_id=store.id, name=r.section, display_order=next_order)
                next_order += 1
                db.add(section)
                db.flush()
                sections[_plain(r.section)] = section
        p = products.get(_plain(r.name))
        if p is None:
            p = Product(store_id=store.id, name=r.name, price=r.price, description=r.description, previous_price=r.previous_price,
                        section_id=section.id if section else None, display_order=order)
            order += 1
            db.add(p)
            products[_plain(r.name)] = p
            created += 1
        else:
            p.price = r.price
            if r.description:
                p.description = r.description
            if section is not None:
                p.section_id = section.id
            p.previous_price = r.previous_price
            updated += 1
    db.flush()
    return {'created': created, 'updated': updated, 'skipped': skipped}


TEMPLATE_CSV = ('nombre;precio;sección;descripción;precio anterior\r\n'
                'Hamburguesa clásica;6500;Hamburguesas;Medallón 180 g, lechuga, tomate y cheddar;\r\n'
                'Papas fritas;3200;Acompañamientos;Porción grande;3800\r\n'
                'Coca-Cola 500 ml;1800;Bebidas;;\r\n')
