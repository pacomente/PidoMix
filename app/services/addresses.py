"""Direcciones guardadas del cliente (Casa, Trabajo...): las mismas en la web y en la app, porque van con la cuenta."""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ClientAddress

MAX = 10
ICONS = ('home', 'work', 'heart', 'pin')


class AddressError(ValueError):
    pass


def for_account(db: Session, account_id: int) -> list[ClientAddress]:
    rows = db.scalars(select(ClientAddress).where(ClientAddress.account_id == account_id)).all()
    # la ultima que uso primero; las nunca usadas en el orden en que las cargo
    return sorted(rows, key=lambda a: (a.last_used_at or datetime.min, -a.id), reverse=True)


def get(db: Session, account_id: int, address_id: int) -> ClientAddress | None:
    a = db.get(ClientAddress, address_id)
    return a if a and a.account_id == account_id else None


def _coord(value, low, high):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if low <= v <= high else None


def save(db: Session, account_id: int, data: dict, row: ClientAddress | None = None) -> ClientAddress:
    """Crea o actualiza (si viene row). Valida todo en el backend. No hace commit."""
    label = ' '.join(str(data.get('label') or '').split())[:40]
    address = ' '.join(str(data.get('address') or '').split())[:255]
    if not label:
        raise AddressError('Ponele un nombre, por ejemplo Casa o Trabajo.')
    if len(address) < 4:
        raise AddressError('Escribí la dirección: calle y número.')
    if row is None:
        if len(for_account(db, account_id)) >= MAX:
            raise AddressError(f'Podés guardar hasta {MAX} direcciones. Borrá alguna para sumar otra.')
        row = ClientAddress(account_id=account_id)
        db.add(row)
    lat, lng = _coord(data.get('lat'), -90, 90), _coord(data.get('lng'), -180, 180)
    row.label, row.address = label, address
    row.reference = ' '.join(str(data.get('reference') or '').split())[:255] or None
    row.lat, row.lng = (lat, lng) if lat is not None and lng is not None else (None, None)
    icon = str(data.get('icon') or '')
    row.icon = icon if icon in ICONS else ('work' if label.lower().startswith('trabajo') else 'home' if label.lower().startswith('casa') else 'pin')
    db.flush()
    return row


def touch(db: Session, account_id: int, address: str) -> None:
    """Al hacer un pedido a una direccion guardada, queda primera en la lista. No hace commit."""
    text = ' '.join((address or '').split()).lower()
    for a in for_account(db, account_id):
        if a.address.lower() == text:
            a.last_used_at = datetime.utcnow()
            return


def as_json(a: ClientAddress) -> dict:
    return {'id': a.id, 'label': a.label, 'address': a.address, 'reference': a.reference, 'lat': a.lat, 'lng': a.lng, 'icon': a.icon}
