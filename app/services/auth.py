from passlib.context import CryptContext
from fastapi import Request
from sqlalchemy.orm import Session
from ..models import User
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(p): return pwd.hash(p)
def verify_password(p,h): return pwd.verify(p,h)
def current_user(request: Request, db: Session):
    uid=request.session.get("user_id")
    return db.get(User, uid) if uid else None
