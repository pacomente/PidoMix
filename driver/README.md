# Trappi Repartidor — app para repartidores (Android / iOS)

App nativa con estilo **Uber Driver**, hecha con Expo + React Native + Expo Router. Habla con la API `/api/courier/v1` del backend (`app/routers/courier_api.py`). La asignación de viajes está en `app/services/dispatch.py`.

## Cómo funciona
- **Entrar:** con el teléfono y un PIN de 4 dígitos que genera el local o Trappi en el panel (**Repartidores**).
- **Conectarse (GO):** la app manda la ubicación cada 4 segundos mientras está conectado y mantiene la pantalla prendida.
- **Oferta:** cuando un pedido de delivery se confirma, le llega a un repartidor por vez durante 35 segundos.
  - El orden es: primero los propios del local, después la flota de Trappi, del más cercano al más lejano.
  - Suena y vibra. Muestra la ganancia (el costo de envío), la distancia al local y el recorrido.
  - Si no acepta, pasa al siguiente. Si nadie acepta, el local lo asigna a mano desde comandas.
- **Oferta:** ganancia grande (tocándola, de dónde sale), km en total, km hasta el local y cuánto paga por km. El tiempo que queda va adentro del botón "Aceptar" y se pone rojo en los últimos 10 segundos.
- **Viaje:** arriba, los dos pasos (retiro y entrega) y cuántos minutos y km faltan según la ruta por calle.
  1. *Retiro:* dirección del local, botón **Navegar**, contacto y aviso de si el pedido ya está listo. "Retiré el pedido" se confirma **deslizando** (como Uber), así no se marca sin querer en el bolsillo. Si hace falta el código de retiro, se carga con el teclado.
  2. *Entrega:* datos del cliente, cuánto cobrarle, WhatsApp o llamada y "Entregué el pedido" (deslizando, o con el PIN del cliente).
- **Mapa:** en viaje sigue al repartidor como un GPS (más cerca, inclinado y girando hacia donde va). Si mueve el mapa con el dedo deja de seguirlo; el botón redondo de la derecha alterna entre seguirlo y ver todo el recorrido.
- **Batería:** esperando viajes, el GPS anda en modo liviano (cada 30 m o 10 s); en viaje, preciso (cada 10 m o 3 s).
- **Sin señal:** un aviso amarillo "Sin conexión · reintentando…" en vez de un error rojo; la app sigue reintentando sola.
- **Ganancias:** hoy, 7 y 30 días; gráfico de los últimos 7 días (tocar un día filtra sus viajes) y el detalle de cada viaje.
- **Mi caja** (flota de Trappi): efectivo a rendir, ganancias a cobrar y lo ya pagado, con pestañas de movimientos, **rendiciones** (con faltantes o sobrantes) y **liquidaciones** (estado y cuenta enmascarada). Solo lectura.
- **Ajustes:** tema **Automático / Claro / Oscuro** (el oscuro no encandila de noche) y con qué app navega (Google Maps, Waze o preguntar). Se guardan en el teléfono.
- **Mapa de noche:** opcional, desde el panel (**Mapas → Mapa de noche de la app de repartidores**, una URL de estilo MapLibre oscuro). Vacío: se usa el mismo mapa de día.

## Mapa
MapLibre (`@maplibre/maplibre-react-native`) con mapas de OpenStreetMap servidos por [OpenFreeMap](https://openfreemap.org), gratis y sin clave de API. En la web (solo para probar la interfaz) se muestra un fondo liso en vez del mapa (`driver-map.web.tsx`).

## Notificaciones (ofertas con la app en segundo plano)
Usa el mismo proyecto de Firebase que la app de clientes:
1. En Firebase → ⚙ Configuración del proyecto → **Agregar app** → Android, con paquete **`ar.trappi.repartidor`**.
2. Descargá el `google-services.json` nuevo (incluye las dos apps) y ponelo en `driver/google-services.json`. También sirve reemplazar el de `mobile/`.

Sin ese archivo la app funciona igual, pero las ofertas suenan solo con la app abierta.

## Probarla
- **APK:** se compila solo con cada cambio en `driver/` y se publica en https://github.com/pacomente/PidoMix/releases/download/app-android/trappi-repartidor.apk
- **Desarrollo:** usa módulos nativos (mapa), así que no corre en Expo Go. Hace falta una build propia: `npx expo run:android` con Android Studio, o `eas build --profile preview`.
- **Antes de subir cambios:** `npm run typecheck && npm run lint`.
