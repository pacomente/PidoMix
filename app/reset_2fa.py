"""Salida de emergencia: quitar la verificacion en dos pasos de una cuenta del panel.

Para cuando el superadmin perdio el celular y los codigos de recuperacion. Se corre desde la
consola del servidor (Render -> el servicio -> Shell):

    python -m app.reset_2fa admin@tu-dominio.com

Cierra sus sesiones; al volver a entrar le pide configurarla de nuevo. Queda en la auditoria.
"""
import sys

from sqlalchemy import select

from .db import SessionLocal
from .models import User
from .services import audit, totp


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print('Uso: python -m app.reset_2fa <email>')
        return 2
    email = argv[1].strip().lower()
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == email))
        if not u:
            print(f'No existe un usuario con el email {email}.')
            return 1
        totp.disable(u)
        u.session_version = (u.session_version or 1) + 1
        audit.log(db, 'user.2fa.reset', 'user', u.id, new={'email': u.email, 'via': 'consola'})
        db.commit()
    print(f'Listo: {email} ya no tiene verificación en dos pasos. Al entrar la vuelve a configurar.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
