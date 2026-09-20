# PidoMix

Marketplace local de delivery construido con Python, FastAPI y PostgreSQL. Las imágenes se preparan para Cloudinary y los pedidos se finalizan mediante WhatsApp.

## Incluye
- Marketplace multi-tienda.
- Home, búsqueda, categorías, filtros y banners.
- Página individual de tienda y catálogo.
- Carrito de una sola tienda.
- Delivery o retiro.
- Checkout y generación de enlace WhatsApp.
- Registro de pedidos.
- Panel `/admin` con autenticación.
- CRUD de tiendas, categorías, productos y banners.
- Roles `SUPERADMIN` y `STORE_ADMIN` preparados.
- Cloudinary mediante variables de entorno.
- PostgreSQL + Alembic.
- Docker Compose para PostgreSQL.

## Ejecutar
1. Copiar `.env.example` a `.env` y completar secretos.
2. `docker compose up -d db`
3. Crear entorno virtual: `python -m venv .venv`
4. Activar entorno y ejecutar `pip install -r requirements.txt`.
5. `alembic upgrade head`
6. `python -m app.seed`
7. `uvicorn app.main:app --reload`

Abrir `http://127.0.0.1:8000` y `/admin/login`.

Usuario inicial: los valores `ADMIN_EMAIL` y `ADMIN_PASSWORD` del `.env`.

## Cloudinary
Configurar `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY` y `CLOUDINARY_API_SECRET`. El servicio deja preparado el upload y guarda `public_id` + URL segura.

## Producción
Cambiar `SECRET_KEY`, credenciales de PostgreSQL y credenciales de Cloudinary. No subir `.env` al repositorio.
