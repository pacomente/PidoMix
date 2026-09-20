# PidoMix

Marketplace local multi-tienda construido sobre **Python + FastAPI + PostgreSQL + Jinja2**, con imágenes en **Cloudinary** y cierre de pedidos mediante **WhatsApp**.

## MVP actual
- Home con banners, categorías, tiendas y productos destacados.
- Marketplace `/tiendas` con búsqueda y filtros reales.
- Página `/tienda/{slug}` con catálogo por categorías.
- Búsqueda global `/buscar` de tiendas, productos y categorías.
- Carrito por sesión, limitado a una sola tienda.
- Checkout con delivery/retiro, pedido mínimo y cálculo de total.
- Registro del pedido en PostgreSQL + enlace de WhatsApp.
- Panel `/admin` con login y permisos `SUPERADMIN` / `STORE_ADMIN`.
- CRUD inicial de tiendas, categorías, productos, banners y estados de pedidos.
- Upload de imágenes a Cloudinary.
- Migración Alembic inicial.
- Docker Compose para PostgreSQL.
- Datos demo con `python -m app.seed`.

## Requisitos
- Python 3.11+
- Docker / Docker Compose
- PostgreSQL (o el servicio incluido en Compose)
- Cuenta Cloudinary para imágenes reales

## Instalación
```bash
cp .env.example .env
docker compose up -d db
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
python -m app.seed
uvicorn app.main:app --reload
```

Abrir `http://127.0.0.1:8000`.
Panel: `http://127.0.0.1:8000/admin/login`.

## Variables
- `DATABASE_URL`
- `SECRET_KEY`
- `CLOUDINARY_CLOUD_NAME`
- `CLOUDINARY_API_KEY`
- `CLOUDINARY_API_SECRET`
- `WHATSAPP_DEFAULT_NUMBER`
- `ADMIN_EMAIL`
- `ADMIN_PASSWORD`

Nunca subir `.env` al repositorio.

## Arquitectura
`app/models` contiene entidades SQLAlchemy; `app/routers` contiene frontend HTTP y API; `app/services` contiene autenticación, carrito, Cloudinary y WhatsApp; `migrations` contiene Alembic.

## Próximas ampliaciones
Pagos, repartidores, zonas de cobertura, geolocalización, promociones, reviews, notificaciones, app móvil, comisiones y multi-ciudad quedan preparados como evolución posterior sin formar parte del MVP actual.
