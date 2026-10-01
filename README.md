# Trappi

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

## Versiones de producción

PidoMix fija **Python 3.12** mediante `.python-version` para evitar depender del runtime por defecto de Render. Las dependencias críticas están controladas en `requirements.txt`: SQLAlchemy 2.0.44, Alembic 1.17.2 y Psycopg 3.

## Producción / Render

**Importante para el servicio existente:** `render.yaml` solo puede corregir el servicio si Render está usando ese Blueprint/configuración. En el Dashboard, el servicio debe tener exactamente el mismo Build, Pre-Deploy y Start Command de este archivo. Si el repositorio está dentro de una carpeta `PidoMix_project`, el Root Directory de Render debe apuntar a esa carpeta.

No debe existir `python -m app.seed` como Start Command ni como tarea independiente. El seed debe ejecutarse únicamente después de Alembic.

Render separa el despliegue en build, pre-deploy y start. El `preDeployCommand` aplica Alembic, verifica que la base de producción esté realmente en el `head` esperado y que las tablas principales (incluido `users`) existan, y solo entonces ejecuta el seed idempotente:
```bash
python -m alembic upgrade head && python -m app.verify_database && python -m app.seed
```

El `startCommand` queda reservado para FastAPI:
```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Así una migración fallida detiene el deploy antes de ejecutar el seed o arrancar la nueva versión. Render documenta `preDeployCommand` específicamente para migraciones y tareas previas al arranque. En planes donde esta función no esté disponible, configurá el mismo comando desde la configuración de deploy de Render; no agregues el seed antes de Alembic.

`migrations/env.py` resuelve la raíz del proyecto de forma portable antes de importar `app`, por lo que Alembic no depende del directorio de trabajo del proceso. En Render también se declara `PYTHONPATH=.` como configuración explícita del entorno.

El proyecto acepta URLs PostgreSQL de Render (`postgres://` / `postgresql://`) y las normaliza internamente para usar **Psycopg 3**. La dependencia requerida es:
```text
psycopg[binary]>=3.2.0,<4.0.0
```

## Desarrollo local

Usar Python 3.12 para mantener el mismo runtime que producción.
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

## Modo comandas (PC o tablet del local)
`/admin/comandas` es una pantalla para dejar abierta en el local: los pedidos nuevos aparecen solos con una alarma que suena hasta que se aceptan, una notificación del sistema (aunque la ventana esté minimizada) y la opción de imprimir el ticket de 80 mm al aceptarlo.

Se instala como app desde Chrome o Edge (botón «Instalar app»): queda el ícono **Trappi Comandas** en el escritorio y abre en su propia ventana. Para imprimir sin el diálogo de impresión, agregar `--kiosk-printing` al acceso directo de la app y dejar la impresora térmica como predeterminada. La guía completa está en la misma pantalla, en «⚙ Ajustes → Cómo instalar e imprimir».

## Zonas de entrega y ubicación
Cada local marca su ubicación en el mapa y define anillos de entrega desde **Mi local → 📍 Zona** (`/admin/stores/{id}/zona`): por ejemplo «hasta 2 km: $900, hasta 4 km: $1.600». Más allá del último anillo el local no entrega (el cliente puede retirar). Los locales sin zona siguen con su envío fijo y sin límite.

El cliente elige su ubicación desde el botón 📍 del encabezado (GPS, búsqueda de dirección o tocando el mapa). Se guarda en su sesión y con eso ve la distancia a cada comercio, cuáles le llegan, el envío exacto y puede ordenar por «Más cerca». En el checkout se valida que esté dentro de la zona, y el pedido guarda las coordenadas: el panel y la pantalla de comandas abren la ubicación exacta en el mapa.

Los mapas usan Leaflet (incluido en `app/static/vendor/leaflet`) con mosaicos de OpenStreetMap, y la búsqueda de direcciones usa Nominatim desde el navegador del usuario: no hace falta ninguna clave de API. Con mucho tráfico conviene pasar a un proveedor de mosaicos y geocodificación con plan propio (MapTiler, Mapbox, etc.). `MAP_DEFAULT_CENTER` (por defecto Bahía Blanca, `-38.7183,-62.2663`) define dónde se abre el mapa.

## App móvil (Android / iOS)
En `mobile/` está la app nativa para clientes, hecha con Expo + React Native. Consume la API JSON `/api/v1` (catálogo, cotización del carrito, pedidos, seguimiento y opiniones), que comparte la lógica de carrito y checkout con la web (`app/services/cart.py` y `app/services/checkout.py`). Los pedidos de la app entran a comandas igual que los de la web. Cómo correrla y publicarla en las tiendas: [mobile/README.md](mobile/README.md).

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
- `MAP_DEFAULT_CENTER` (opcional, `lat,lng`)

Nunca subir `.env` al repositorio ni secretos a `render.yaml`.

## Cloudinary
Las imágenes persistentes del marketplace se almacenan en Cloudinary; PostgreSQL guarda URL segura y `public_id`. En producción no se depende del filesystem local de Render.

## Migraciones
```bash
alembic upgrade head
```
No se ejecutan operaciones destructivas automáticamente.

La migración `0005_performance_indexes` agrega índices sobre las foreign keys y `orders.created_at` (PostgreSQL no indexa las FKs automáticamente). Es idempotente: solo crea los índices que falten.

## Tests
```bash
pip install -r requirements.txt pytest httpx
python -m pytest -q
```
Corren sobre SQLite (no necesitan PostgreSQL): recorren las páginas públicas, el carrito, el checkout, el panel admin y la cadena completa de migraciones de Alembic.

## Rendimiento
- Respuestas comprimidas con GZip y archivos de `/static` cacheados un año (se versionan con `?v=` en cada deploy).
- Las colecciones (horarios, productos, modificadores) se cargan con `selectinload` para no multiplicar filas, y los listados se limitan en la base de datos.
- Los endpoints del carrito son síncronos (corren en el threadpool), así una consulta lenta no bloquea al resto de los requests.

## Seed demo
Ejecutar después de aplicar migraciones:
```bash
python -m app.seed
```

## Próxima evolución
Pagos, repartidores avanzados, zonas de cobertura, geolocalización, promociones, reviews, notificaciones, app móvil, comisiones y multi-ciudad quedan fuera del MVP actual.
