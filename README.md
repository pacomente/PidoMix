# PidoMix

Marketplace local multi-tienda construido con **Python + FastAPI + PostgreSQL + Jinja2**, con imágenes en **Cloudinary** y cierre de pedidos mediante **WhatsApp**.

## MVP actual
- Home comercial con banners, categorías, tiendas y productos destacados.
- Marketplace `/tiendas` con búsqueda y filtros reales.
- Página `/tienda/{slug}` con catálogo por categorías.
- Búsqueda global `/buscar`.
- Carrito por sesión, limitado a una sola tienda, con cantidades, vaciado y totales.
- Checkout con delivery/retiro, pedido mínimo y cálculo de total.
- Registro del pedido en PostgreSQL + enlace de WhatsApp.
- Panel `/admin` con login y autorización backend.
- Gestión de tiendas, categorías de tiendas, categorías de productos, productos, banners, clientes, usuarios y estados de pedidos.
- Imágenes validadas y almacenadas en Cloudinary.
- Alembic para migraciones.
- Health check `/health`.
- Configuración `render.yaml` para Render.

## Producción / Render
El servicio web ejecuta:
```bash
alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

El proyecto acepta URLs PostgreSQL de Render (`postgres://` / `postgresql://`) y las normaliza internamente para usar **Psycopg 3**. La dependencia requerida es:
```text
psycopg[binary]>=3.2.0,<4.0.0
```

## Desarrollo local
```bash
cp .env.example .env
docker compose up -d db
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
python -m app.seed
uvicorn app.main:app --reload
```

Abrir `http://127.0.0.1:8000`. Panel: `http://127.0.0.1:8000/admin/login`.

## Variables de entorno
- `DATABASE_URL`
- `SECRET_KEY`
- `ENVIRONMENT`
- `ALLOWED_ORIGINS`
- `CLOUDINARY_CLOUD_NAME`
- `CLOUDINARY_API_KEY`
- `CLOUDINARY_API_SECRET`
- `WHATSAPP_DEFAULT_NUMBER`
- `ADMIN_EMAIL`
- `ADMIN_PASSWORD`

Nunca subir `.env` al repositorio ni secretos a `render.yaml`.

## Cloudinary
Las imágenes persistentes del marketplace se almacenan en Cloudinary; PostgreSQL guarda URL segura y `public_id`. En producción no se depende del filesystem local de Render.

## Migraciones
```bash
alembic upgrade head
```
No se ejecutan operaciones destructivas automáticamente.

## Seed demo
Ejecutar después de aplicar migraciones:
```bash
python -m app.seed
```

## Próxima evolución
Pagos, repartidores avanzados, zonas de cobertura, geolocalización, promociones, reviews, notificaciones, app móvil, comisiones y multi-ciudad quedan fuera del MVP actual.
