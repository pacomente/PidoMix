"""Auditoria de operaciones sensibles (tarifas, comisiones, cuentas de cobro, liquidaciones, rendiciones,
reembolsos, cobertura). Solo agrega registros: nunca se editan ni se borran."""
import json
from decimal import Decimal

from sqlalchemy.orm import Session

from ..models import AuditLog


def _dump(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value[:20000]
    return json.dumps(value, default=str, ensure_ascii=False)[:20000]


def log(db: Session, action: str, entity: str, entity_id=None, *, user=None, old=None, new=None, amount_old=None, amount_new=None,
        reason: str | None = None, ip: str | None = None) -> AuditLog:
    """Agrega una linea de auditoria. No hace commit (va en la misma transaccion que el cambio)."""
    row = AuditLog(user_id=getattr(user, 'id', None), action=action[:60], entity=entity[:40], entity_id=str(entity_id) if entity_id is not None else None,
                   old_value=_dump(old), new_value=_dump(new),
                   amount_old=Decimal(str(amount_old)) if amount_old is not None else None,
                   amount_new=Decimal(str(amount_new)) if amount_new is not None else None,
                   reason=(reason or '').strip()[:255] or None, ip=(ip or '')[:64] or None)
    db.add(row)
    return row
