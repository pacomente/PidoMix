import bcrypt
from fastapi import Request
from sqlalchemy.orm import Session
from ..models import User

# bcrypt solo usa los primeros 72 bytes; se recorta explicito (igual que hacia passlib).
def _secret(p: str) -> bytes: return p.encode("utf-8")[:72]
def hash_password(p): return bcrypt.hashpw(_secret(p), bcrypt.gensalt()).decode("ascii")
def verify_password(p, h):
    try:
        return bcrypt.checkpw(_secret(p), (h or "").encode("ascii"))
    except ValueError:  # hash vacio o con formato invalido
        return False
def current_user(request: Request, db: Session):
    uid = request.session.get("user_id")
    return db.get(User, uid) if uid else None
