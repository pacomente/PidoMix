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

## Repartidores (app y asignación de viajes)
En `driver/` está **Trappi Repartidor**, la app nativa para repartidores con estilo Uber Driver: mapa, botón GO, ofertas con cuenta regresiva, retiro, entrega y ganancias. La flota es mixta: cada local puede tener repartidores propios (que reciben primero sus pedidos) y además está la flota de Trappi.

- **Asignación:** al confirmarse un delivery se le ofrece a un repartidor por vez (`app/services/dispatch.py`). Si nadie acepta, se asigna a mano desde comandas.
- **Ganancia:** cada repartidor gana el costo de envío.
- **Alta:** los repartidores se dan de alta en **/admin/repartidores**.
- **Detalles:** [driver/README.md](driver/README.md).

## Configuración de la plataforma (superadmin)
Desde **/admin/settings** (`app/services/platform.py`; los valores se guardan en la tabla `settings` y se aplican en unos segundos):
- **Apps y mantenimiento:**
  - Apagar por separado la tienda web, la app de clientes y la app de repartidores, cada una con su mensaje. El panel y comandas siguen andando.
  - Pausar los pedidos en toda la plataforma.
  - Versión mínima de cada app, que obliga a actualizar, y el link de descarga.
- **Repartidores:** ofertas automáticas sí o no, segundos para aceptar, radio en km, cuándo volver a ofrecer, cuánto dura la ubicación, cada cuánto manda el GPS y la regla de ganancia (envío completo, porcentaje o monto fijo). La ganancia queda fijada al asignar el viaje.
- **Mapas:** estilo del mapa de la app de repartidores (OpenFreeMap u otro proveedor MapLibre), mosaicos del mapa de la web y buscador de direcciones (Nominatim).

Las apps consultan `/api/v1/config` y `/api/courier/v1/config` al abrir, al volver y cada 2 minutos. Con una app apagada, el resto de su API responde `503 {"maintenance": true}`.

## Modelo comercial y alta de comercios
Los comercios **no se registran solos**. El botón "Sumá tu comercio" de la web abre WhatsApp con el número y el mensaje de **Configuración → Configuración comercial**. Después de acordar las condiciones, el superadmin los da de alta en **/admin/comercios/nuevo** con su plan y su usuario; la contraseña se genera sola si no se carga, y se muestra una sola vez con un botón para mandarla por WhatsApp. El comercio queda *pendiente* hasta que se activa desde su ficha, con al menos un producto.

- **Trappi Comercio:** abono mensual (por defecto $10.000), 0 % de comisión y cadetes propios. La flota de Trappi solo entra si se elige la logística "propios y flota".
- **Trappi Delivery:** sin abono, comisión por venta configurable (sobre los productos, sin el envío) y la flota de Trappi.

Cada comercio tiene sus condiciones acordadas: plan, abono, comisión, logística y estado (pendiente, activo, suspendido o desactivado). Hay historial de cambios de plan y registro manual de abonos (período, importe, pendiente o pagado), sin cobro automático.

Cada pedido guarda las condiciones vigentes al crearse: plan, % de comisión y logística. Con eso se calculan:
- la comisión;
- el pago al cadete;
- el neto del comercio;
- el ingreso de Trappi.

Si reparte la flota, Trappi cobra el envío y le paga al cadete. Si reparte un cadete propio, el envío es del comercio. Cambiar después el plan no toca los pedidos ya hechos. Los comercios anteriores a los planes quedan "sin plan": sin comisión y con la logística de siempre, hasta que se les asigne uno.

Cada local ve sus condiciones en **/admin/mi-plan**, con un botón "Solicitar cambio de plan" que abre WhatsApp. No las puede cambiar.

**Reiniciar un comercio** (solo superadmin, en la ficha → *Zona peligrosa*): borra sus pedidos, estadísticas, comisiones, movimientos de saldo, liquidaciones, pagos registrados y reseñas, y opcionalmente los abonos. Antes muestra qué se borra y avisa si tiene saldo con Trappi, liquidaciones sin pagar, efectivo de cadetes sin rendir o pagos aprobados en Mercado Pago (allá no cambia nada). Con pedidos en curso no deja. Hay que escribir el nombre del comercio para confirmar y queda en la auditoría. Productos, plan, horarios, cupones y usuarios siguen igual; la plata de los cadetes tampoco se toca.

**Eliminar productos:** el local puede eliminar sus productos desde **Productos**. Si nunca se vendió se borra del todo; si ya se vendió queda oculto para que los pedidos viejos lo sigan mostrando.

## Logística: flota, zonas y envío por km
El superadmin maneja todo en **/admin/logistica**:
- **Zonas** (`/admin/logistica/zonas`): mapa con zonas de radio o polígono, prioridad (si se superponen gana la de mayor prioridad y, a igual prioridad, la más chica), días y horario, tope de km y tarifa. Cada cambio guarda una versión (historial de tarifas) y queda en la auditoría.
- **Tarifa**: `base + max(0, km por ruta − km incluidos) × precio por km`, con mínimo, máximo y redondeo hacia arriba. La distancia es **por calle** (servicio de rutas, `app/services/routing.py`); si el servicio no responde se usa una estimación (línea recta × factor de desvío) marcada como `estimate`, o se rechaza, según la configuración.
- **Configuración** (`/admin/logistica/configuracion`): flota activa y horario, qué pasa fuera de cobertura (solo retiro, entrega el comercio o rechazar), quién paga el envío por defecto (cliente, comercio, Trappi o compartido), costo operativo por km, fórmula de pago al repartidor (base, por km, por entrega, nocturno, alta demanda, viaje largo) y límite de efectivo.
- **Rentabilidad** (`/admin/logistica/rentabilidad`): por pedido, envío cobrado, pago al cadete, costo operativo (km operativos: cadete → local → cliente) y margen.

Cada comercio elige en **/admin/pagos** si entrega con sus cadetes (COMERCIO) o con la flota (TRAPPI), si el superadmin le habilitó la flota en su ficha. Cada pedido guarda una copia del cálculo (zona, km, tarifa, quién paga, comisión, pago estimado): cambiar tarifas o comisiones no toca los pedidos ya hechos. Si no hay ninguna zona cargada, los comercios con flota siguen con su envío de siempre.

Las comisiones (% + fijo, con mínimo y máximo, por plan y por comercio) están en **/admin/configuracion/comisiones**.

## Multi-ciudad
Las ciudades se administran en **/admin/ciudades**:
- **Datos de cada ciudad:** nombre, provincia, centro en el mapa, radio con el que se reconoce por la ubicación del cliente, WhatsApp comercial propio ("Sumá tu comercio") y si está activa.
- **Qué es de una ciudad:** cada comercio, cada repartidor de la flota, cada zona de cobertura y cada pedido. Lo que no tiene ciudad, lo anterior a multi-ciudad, se comparte entre todas.
- **Cómo se decide la ciudad del cliente:**
  1. la que eligió (selector en la web y en la app, visible solo con más de una ciudad activa);
  2. si no eligió, la que contiene su ubicación;
  3. si no hay ubicación, la principal.

  Los listados, la búsqueda y las ofertas muestran solo los comercios de esa ciudad. El link directo a un comercio sigue funcionando.
- **Flota:** la flota de cada ciudad lleva solo los pedidos de su ciudad, y las zonas de una ciudad no se usan en otra.
- **Configuración por ciudad:** en la ficha de cada ciudad se puede tener una configuración propia de flota (horario, cobertura, quién paga el envío), costo operativo, pago al repartidor, efectivo, retiro, radio de ofertas y valores del plan. Lo que queda "como la general" usa Logística → Configuración.
- **Filtro del panel:** el superadmin puede mirar una sola ciudad desde el selector del menú. Se filtran pedidos, comandas, comercios, repartidores, finanzas, logística y liquidaciones.
- **Ciudades nuevas:** se crean ocultas. Conviene cargar comercios, repartidores y zonas, y después activarlas.

La migración 0017 crea la ciudad principal (la de `MAP_DEFAULT_CENTER`; por defecto, Bahía Blanca) y le asigna todo lo que ya existe.

## Pagos online (Mercado Pago Split) y finanzas
Cada comercio conecta **su** cuenta de Mercado Pago por OAuth desde **/admin/pagos** (no se le pide ningún token). El cliente paga con el token del comercio y Trappi se lleva su parte con `marketplace_fee` (comisión + envío de la flota). El pedido no se acepta ni se despacha hasta que Mercado Pago aprueba el pago: el webhook valida la firma `x-signature`, descarta avisos repetidos y **consulta el pago a la API** antes de tocar nada (pedido, importe, moneda y cuenta tienen que coincidir). Los pedidos sin pagar a tiempo se cancelan solos. Las devoluciones se hacen desde **/admin/finanzas/pagos**. Los tokens se guardan cifrados.

Configurar Mercado Pago:
1. En Mercado Pago Developers, crear la aplicación de Trappi (producto *Checkout Pro*, modelo *Marketplace*).
2. Redirect URL de OAuth: `https://<dominio>/admin/pagos/mercadopago/callback` (igual a `MERCADOPAGO_REDIRECT_URI`).
3. Webhooks: URL `https://<dominio>/api/payments/mercadopago/webhook`, evento *Pagos*; copiar la clave secreta a `MERCADOPAGO_WEBHOOK_SECRET`.
4. Cargar `MERCADOPAGO_CLIENT_ID` y `MERCADOPAGO_CLIENT_SECRET` en Render. Para pruebas, `MERCADOPAGO_ENVIRONMENT=sandbox` con usuarios de prueba (vendedor = comercio, comprador = cliente); para cobrar de verdad, `production`.
5. Revisar **Finanzas → Mercado Pago** (`/admin/pagos/diagnostico`): muestra qué variable falta o está mal (sin mostrar secretos), tiene un botón para probar las credenciales con Mercado Pago y lista los últimos avisos recibidos (401 = clave de Webhooks distinta).

**Finanzas** (`/admin/finanzas`): movimientos por cuenta (comercio, caja del repartidor, ganancias del repartidor), que no se borran ni se editan; los ajustes llevan motivo.
- **Efectivo**: el efectivo que cobra un cadete de la flota queda pendiente de rendir. Al llegar a su límite no recibe pedidos en efectivo (sí online, si está configurado así). El cadete ve "Mi caja" en su app.
- **Según el plan**: el pago al local al retirar, el código de retiro y "no se pudo entregar" son solo para **Trappi Delivery** (los cadetes de la flota). En Trappi Delivery no se ofrece transferencia ni se muestra el alias del local: se paga en efectivo con la flota o con Mercado Pago. La transferencia al alias del local es solo para **Trappi Comercio** (y los comercios sin plan de antes).
- **Pago al local al retirar** (como en las apps de delivery): en un pedido en efectivo que lleva la flota, el cadete le paga al local el valor de los productos al retirar (o los productos menos la comisión, según la configuración) y después le cobra al cliente productos + envío. La comanda y el ticket muestran si el pedido es en efectivo o ya está pagado, y cuánto le paga el cadete.
- **No se pudo entregar**: si el cliente no atiende, la dirección está mal o rechaza el pedido, el cadete lo reporta desde la app ("No pude entregar") y vuelve al local. La comanda muestra el aviso. Cuando el local recibe el pedido y le devuelve al cadete lo que le había pagado, lo cancela con "Me devolvió el pedido y le devolví $X": la caja del cadete vuelve a cero y se anula la comisión de esa venta. Si el local se queda con la plata, solo Trappi puede cancelarlo así, y al cadete se le devuelve en su liquidación. Configurable: si el cadete cobra el viaje igual. Un pedido que el cadete ya le pagó al local no se puede volver a "Listo" ni marcar "ya pagó".
- **Código de retiro (anti robo)**: cada delivery de Trappi Delivery tiene un código de 4 números que está solo en la comanda y el ticket del local (en una parte para cortar, que no va en la bolsa). Cuando el cadete de la flota le paga y retira, el local le dicta el código y el cadete lo carga en la app: sin el código correcto no se puede marcar retirado (con límite de intentos), y el local tampoco puede marcarlo "en camino" por su cuenta.
- **Efectivo a rendir**: lo que el cadete tiene que rendir de cada pedido sale de los movimientos de su caja (cobrado al cliente − lo que le pagó al local) y vuelve a $0 cuando rinde. El límite de efectivo cuenta solo eso, no lo que puso de su bolsillo para pagarle al local.
- **Rendiciones** (`/admin/finanzas/rendiciones`): se registran con lo recibido; la diferencia queda como deuda o saldo a favor.
- **Liquidaciones** (`/admin/finanzas/liquidaciones`): de comercios (lo cobrado en efectivo por la flota menos la comisión, o la comisión que adeuda) y de repartidores (viajes + bonos + ajustes). Estados: pendiente, en proceso, pagada, fallida y cancelada. No hay transferencias automáticas: se paga por fuera y se carga el comprobante.
- **Compensar efectivo con la liquidación**: al liquidar a un repartidor, si tiene efectivo sin rendir, se le descuenta de lo que cobra (hasta ese monto) y queda registrado como una rendición compensada. Le transferís solo la diferencia. Si la liquidación falla o se cancela, el efectivo vuelve a quedar sin rendir.
- Los datos de cobro del repartidor (CBU/CVU) se guardan cifrados, se muestran enmascarados y tienen historial.

Toda acción sobre plata queda en **/admin/finanzas/auditoria**.

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
- `SENTRY_DSN` (opcional): DSN del proyecto de Sentry del backend; activa el reporte de errores. `SENTRY_TRACES_SAMPLE_RATE` (por defecto `0.05`) es la fracción de requests que se miden. La versión se toma de `RENDER_GIT_COMMIT`.
- `FIREBASE_SERVICE_ACCOUNT` (opcional): el JSON de la cuenta de servicio de Firebase, para mandar notificaciones push a la app cuando cambia el estado de un pedido. Ver [mobile/README.md](mobile/README.md#notificaciones-push).

- `PUBLIC_BASE_URL` (recomendada): URL pública del sitio, para los avisos y las vueltas de Mercado Pago.
- `FIELD_ENCRYPTION_KEY` (recomendada): clave Fernet para cifrar tokens de Mercado Pago y CBU/CVU (`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`). Sin ella se deriva de `SECRET_KEY`; si se cambia, hay que volver a conectar las cuentas y a cargar los datos de cobro.
- `MERCADOPAGO_ENVIRONMENT` (`sandbox` o `production`), `MERCADOPAGO_CLIENT_ID`, `MERCADOPAGO_CLIENT_SECRET`, `MERCADOPAGO_PUBLIC_KEY`, `MERCADOPAGO_REDIRECT_URI`, `MERCADOPAGO_WEBHOOK_SECRET`. Sin `CLIENT_ID`, `CLIENT_SECRET` y `REDIRECT_URI` no se ofrece el pago online. Sin `WEBHOOK_SECRET` los avisos solo se aceptan en sandbox.
- `ADMIN_2FA_REQUIRED` (opcional): verificación en dos pasos obligatoria para el superadmin. Vacía: sí en producción, no en desarrollo.
- `ROUTING_PROVIDER` (`osrm` o `none`), `ROUTING_URL` (servidor OSRM; el público `router.project-osrm.org` es de demostración, para producción conviene uno propio), `ROUTING_API_KEY` (opcional), `ROUTING_TIMEOUT_SECONDS` (por defecto 4).

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

## Errores (Sentry)
Con `SENTRY_DSN` cargada, el backend reporta a Sentry las excepciones no manejadas y los `logger.error` (por ejemplo, fallas al mandar notificaciones push), con la versión desplegada (`app/services/monitoring.py`). No se envían datos personales: ni cuerpos de requests (nombre, teléfono, dirección), ni cookies, ni el token `?t=` de seguimiento. La app móvil tiene su propio proyecto de Sentry (ver [mobile/README.md](mobile/README.md#errores-sentry)).

## Seguridad del panel
- **Verificación en dos pasos** (códigos de 6 números de Google Authenticator, Microsoft Authenticator, Authy, etc.). Obligatoria para el superadmin en producción: al entrar, si no la tiene, tiene que configurarla antes de usar el panel. Los locales la pueden activar en **Mi cuenta**. Al activarla se muestran 10 códigos de recuperación una sola vez; cada uno sirve una vez. El secreto se guarda cifrado y cada código se puede usar una sola vez.
  - Si alguien perdió el celular y los códigos: el superadmin se la quita desde **Usuarios** ("Quitar dos pasos").
  - Si el que la perdió es el superadmin: desde la consola de Render (el servicio → Shell) `python -m app.reset_2fa <email>`. Al volver a entrar la configura de nuevo. Queda en la auditoría.
  - Cambiar `FIELD_ENCRYPTION_KEY` (o `SECRET_KEY` sin ella) deja ilegibles los secretos: hay que entrar con un código de recuperación o usar el comando.
- **Token CSRF**: cada formulario del panel lleva un token de la sesión y se rechaza cualquier envío sin él, o que venga de otro sitio (`app/services/csrf.py`). En las plantillas nuevas: `{{ csrf_input() }}` dentro de cada `<form method="post">`.
- **Encabezados de seguridad** en todas las respuestas: Content-Security-Policy (solo scripts propios, no se puede meter el sitio dentro de otra página), X-Frame-Options, nosniff, Referrer-Policy y Permissions-Policy. En producción además HSTS (solo HTTPS). El panel no queda guardado en el navegador (`Cache-Control: no-store`).
- **Sesiones**: cambiar la contraseña, activar o quitar los dos pasos, o desactivar un usuario cierra sus sesiones en los otros dispositivos. En **Mi cuenta** hay un botón para cerrarlas a mano. Al desplegar este cambio se cierran una vez todas las sesiones abiertas del panel.

## Límites de intentos (rate limiting)
Usa la IP real del cliente que manda Cloudflare (`CF-Connecting-IP`). Render publica el servicio detrás de Cloudflare, así que la IP de la conexión es la del proxy y la comparten todos los clientes.

Los intentos de ingreso se guardan en la base (tabla `auth_attempts`): no se reinician al desplegar y valen para todas las instancias.
- Login del panel: 5 intentos fallidos cada 5 minutos por IP y cuenta, y 20 cada 15 minutos por cuenta.
- Código de dos pasos: 5 incorrectos cada 5 minutos por usuario.
- App de repartidores: 8 logins fallidos cada 10 minutos; PIN de entrega y código de retiro con su límite por pedido.
- Pedidos nuevos (web y app): 20 cada 10 minutos por IP.

En memoria, por proceso (se consultan en cada pedido y no vale la pena escribir en la base):
- General: 300 consultas por minuto por IP en `/api` y otras 300 en la web. El panel `/admin` y `/static` no cuentan. El exceso recibe un 429 con `Retry-After`.
- `/health/ip` muestra qué IP está usando el servidor para quien consulta. Sirve para verificar que llegue la de Cloudflare.

Con un dominio propio en Cloudflare se puede sumar una regla de rate limiting en el borde (Security → WAF → Rate limiting rules), para frenar ataques antes de que lleguen a Render.

## Seed demo
Ejecutar después de aplicar migraciones:
```bash
python -m app.seed
```

## Próxima evolución
Quedan para más adelante: pagos automáticos a comercios y repartidores (necesitan una integración de transferencias aprobada; hoy se liquida y se carga el comprobante).
