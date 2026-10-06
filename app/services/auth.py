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
    """El usuario de la sesion. Si cambio la contrasena (o se cerraron sus sesiones) despues de entrar, ya no vale."""
    uid = request.session.get("user_id")
    u = db.get(User, uid) if uid else None
    if u is None or request.session.get("sv") != u.session_version:
        return None
    return u


def start_session(request: Request, user: User) -> None:
    """Sesion nueva (otro id de cookie) para el usuario que termino de ingresar."""
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["sv"] = user.session_version


def end_other_sessions(request: Request, user: User) -> None:
    """Cierra las sesiones de los otros dispositivos; esta sigue abierta. No hace commit."""
    user.session_version = (user.session_version or 1) + 1
    request.session["sv"] = user.session_version
