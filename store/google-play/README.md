# Subir Trappi (app de clientes) a Google Play

Paquete: `ar.trappi.app` · Versión: la de `mobile/app.json` (`version`). El `versionCode` se calcula solo
(1.10.0 → 11000; 1.10.1 → 11001), así que para cada envío nuevo alcanza con subir `version`.

La app de repartidores (`driver/`) no va a Play por ahora: se sigue repartiendo como APK.

## 1. Cuenta de desarrollador

1. Entrá a <https://play.google.com/console/signup> con la cuenta de Google que va a ser dueña de la app.
2. Elegí el tipo de cuenta:
   - **Organización** si Trappi tiene CUIT de empresa (pide número D-U-N-S, gratis, tarda unos días). Puede publicar directo a producción.
   - **Personal**: más rápida, pero Google exige una **prueba cerrada con al menos 12 testers durante 14 días seguidos** antes de dejarte pasar a producción.
3. Pagás USD 25 (una sola vez) y verificás identidad (DNI) y teléfono.

## 2. Clave de subida (una sola vez)

1. GitHub → **Actions → "Clave de subida para Google Play" → Run workflow**.
2. Cuando termine, bajá el artifact **clave-de-subida** (dura 1 día) y abrí `LEEME.txt`.
3. Cargá los 4 secretos en GitHub → **Settings → Secrets and variables → Actions**:
   `ANDROID_UPLOAD_KEYSTORE_BASE64`, `ANDROID_UPLOAD_STORE_PASSWORD`, `ANDROID_UPLOAD_KEY_ALIAS`, `ANDROID_UPLOAD_KEY_PASSWORD`.
4. Guardá `upload.jks` y las contraseñas en un lugar seguro fuera del repo (gestor de contraseñas o un pendrive).
   Si se pierde, se pide un cambio de clave de subida a Google desde Play Console; no se pierde la app.
5. Borrá el artifact de GitHub después de guardar todo.

## 3. Armar el AAB

1. GitHub → **Actions → "App para Google Play" → Run workflow**.
2. Bajá el artifact `trappi-<versión>-google-play` → adentro está `app-release.aab`.

## 4. Crear la app en Play Console

1. **Crear app** → nombre "Trappi", idioma Español (Latinoamérica), App, Gratis; aceptá las declaraciones.
2. **Firma de apps de Google Play**: dejala activada (es lo predeterminado). Google guarda la clave final; vos solo usás la de subida.
3. **Prueba interna** (o **Prueba cerrada** si tu cuenta es personal) → Crear versión → subí `app-release.aab`.
4. Agregá testers por email (o un Grupo de Google) y pasales el link de suscripción.

## 5. Contenido de la app (Panel → "Configurar tu app")

| Sección | Qué poner |
|---|---|
| Política de privacidad | `https://trappi.com.ar/privacidad` |
| Acceso a la app | "Algunas funciones están restringidas". Comercios y menús se ven sin cuenta, pero para pedir hay que entrar con email + código. Creá un Gmail solo para la revisión (por ejemplo `trappi.revision@gmail.com`) y cargá en las instrucciones: ese email, la contraseña del Gmail y "En Mi perfil, ingresá este email; el código de 6 dígitos llega a esa casilla". |
| Anuncios | No contiene anuncios. |
| Clasificación del contenido | Cuestionario IARC, categoría "Todas las demás". Marcá que permite **compras de bienes físicos** y que los usuarios pueden **compartir ubicación**. No hay violencia, apuestas ni chat entre usuarios. |
| Público objetivo | 18 años o más. |
| App de noticias | No. |
| Apps gubernamentales / financieras / de salud | No (la farmacia vende productos, no da servicios de salud). |
| Eliminación de cuenta | URL: `https://trappi.com.ar/eliminar-cuenta`. Desde la app: Mi perfil → Eliminar mi cuenta. |

### Seguridad de los datos

- ¿Recopila o comparte datos? **Sí**. ¿Encriptados en tránsito? **Sí** (todo por HTTPS). ¿El usuario puede pedir que se borren? **Sí**.
- No se venden datos ni se usan para publicidad.

| Tipo de dato | Recopilado | Compartido | Para qué | ¿Opcional? |
|---|---|---|---|---|
| Nombre | Sí | Sí, con el comercio y el repartidor del pedido | Funciones de la app, administración de la cuenta | No |
| Email | Sí | No | Administración de la cuenta, comunicaciones (avisos del pedido; novedades solo si las acepta) | No |
| Teléfono | Sí | Sí, con el comercio y el repartidor | Funciones de la app | No |
| Dirección | Sí | Sí, con el comercio y el repartidor | Funciones de la app | No |
| Ubicación precisa | Sí | Sí, con el comercio y el repartidor (punto de entrega) | Funciones de la app | Sí |
| Ubicación aproximada | Sí | No | Funciones de la app (comercios que llegan) | Sí |
| Historial de compras | Sí | Sí, con el comercio y con Mercado Pago (importe del pago) | Funciones de la app, prevención de fraudes, personalización (recomendaciones, se puede apagar) | No |
| Información de pago | No (la tarjeta la maneja Mercado Pago dentro de su pantalla) | — | — | — |
| Mensajes en la app (Trappi AI) | Sí | No | Funciones de la app | Sí |
| Registros de fallas y diagnóstico | Sí (Sentry) | No | Análisis, arreglar errores | No |
| IDs de dispositivo (token de notificaciones) | Sí | No | Funciones de la app (avisos del pedido) | Sí |

Nota: según Google, mandar datos a un proveedor que procesa por vos (Render, Brevo, Sentry, Firebase) **no** cuenta como "compartir".
Pasarle el pedido al comercio y al repartidor sí, porque son terceros.

## 6. Ficha de Play Store

Textos para copiar en [`ficha.md`](ficha.md). Ícono, gráfico de funciones y capturas en esta carpeta.

## 7. Revisión y producción

1. Enviá la versión de prueba a revisión (la primera tarda de unas horas a 7 días).
2. Cuenta personal: esperá los 14 días con 12 testers activos y pedí el acceso a producción desde el Panel
   (te hace unas preguntas sobre la prueba).
3. Producción → Crear versión → podés "promocionar" la misma versión de la prueba. Países: Argentina.

## Versiones siguientes

1. Subí `version` en `mobile/app.json` (por ejemplo 1.10.0 → 1.10.1) y mergeá.
2. Corré "App para Google Play" y subí el nuevo AAB a la pista que corresponda.
3. Opcional: cargá el secreto `PLAY_SERVICE_ACCOUNT_JSON` (cuenta de servicio con permiso de "Lanzar versiones" en Play Console)
   y el workflow lo sube solo como borrador a la pista que elijas.
