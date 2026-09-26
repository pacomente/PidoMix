# PidoMix — configuración de deploy en Render

## Causa que este proyecto evita

El código actual no ejecuta `app.seed` al importar `app`, `app.main`, los routers ni los modelos. El seed solo se ejecuta con `python -m app.seed`.

Si los logs de Render muestran `python -m app.seed` antes de `alembic upgrade head`, el servicio de Render está usando una configuración distinta de la que está versionada en `render.yaml` (por ejemplo, un Start Command/pre-deploy antiguo en el Dashboard o un Root Directory distinto).

## Configuración exacta

**Root Directory**

Debe ser la carpeta que contiene directamente `app/`, `migrations/`, `alembic.ini`, `requirements.txt` y `render.yaml`.

**Build Command**

```bash
python --version && pip install -r requirements.txt
```

**Pre-Deploy Command**

```bash
python -m alembic upgrade head && python -m app.verify_database && python -m app.seed
```

**Start Command**

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

No debe haber otro `python -m app.seed` configurado en el servicio.

## Qué verifica el pre-deploy

1. Alembic ejecuta todas las migraciones hasta `head`.
2. `app.verify_database` comprueba que la revisión de `alembic_version` coincide con el `head` del código.
3. Comprueba que existen las tablas principales, incluyendo `users`.
4. En PostgreSQL registra únicamente `database` y `schema`, sin contraseña ni URL completa.
5. Solo después se ejecuta el seed idempotente.
6. Si cualquiera de esos pasos falla, el `&&` impide continuar al siguiente paso.

## Variables obligatorias

- `DATABASE_URL` — debe ser la conexión PostgreSQL de producción de PidoMix.
- `SECRET_KEY`
- `ENVIRONMENT=production`
- `ADMIN_EMAIL`
- `ADMIN_PASSWORD`
- `WHATSAPP_DEFAULT_NUMBER`
- `CLOUDINARY_CLOUD_NAME`
- `CLOUDINARY_API_KEY`
- `CLOUDINARY_API_SECRET`

En producción, PidoMix rechaza `DATABASE_URL` vacía o apuntando a `localhost`, `127.0.0.1` o `0.0.0.0`, y rechaza la `SECRET_KEY` de desarrollo.

## Python

El proyecto contiene `.python-version` con `3.12`. Render admite esa forma de fijar la versión y usa el último patch disponible de Python 3.12.

## Psycopg

Se mantiene exactamente:

```text
psycopg[binary]>=3.2.0,<4.0.0
```

## Diagnóstico del error `relation "users" does not exist`

En una base nueva, la secuencia correcta es:

```text
Build
  -> PostgreSQL de producción
  -> alembic upgrade head
  -> verify_database
  -> app.seed
  -> uvicorn
  -> /health
```

Si aparece nuevamente `python -m app.seed` antes de Alembic en los logs, el problema está en la configuración efectiva del servicio de Render, no en el orden definido por este repositorio.
