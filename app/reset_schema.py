"""Vacia por completo el schema 'public' de la base configurada en DATABASE_URL.

USO MANUAL UNICAMENTE. No se llama desde render.yaml ni desde ningun flujo
automatico. Sirve para recuperarse de un estado de Alembic inconsistente
(por ejemplo: alembic_version apunta a una revision que ya no existe en el
codigo, o el schema tiene tablas/tipos de una migracion anterior que ya no
coincide con los archivos actuales de migrations/versions).

Borra TODAS las tablas, tipos y datos del schema public. No pide confirmacion
extra: quien lo corre ya confirmo explicitamente que puede perder los datos.

Ejecutar apuntando a la base que se quiere limpiar, nunca a produccion sin
confirmar antes que no hay datos que conservar:

    DATABASE_URL="<external-database-url-de-render>" python -m app.reset_schema
"""
from sqlalchemy import create_engine, text

from .config import settings
from .db import normalize_database_url


def reset_schema() -> None:
    url = normalize_database_url(settings.database_url)
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    print("[RESET] schema 'public' vaciado por completo.")


if __name__ == "__main__":
    reset_schema()
