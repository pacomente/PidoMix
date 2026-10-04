# Trappi Repartidor — app para repartidores (Android / iOS)

App nativa con estilo **Uber Driver**, hecha con Expo + React Native + Expo Router. Habla con la API `/api/courier/v1` del backend (`app/routers/courier_api.py`). La asignación de viajes está en `app/services/dispatch.py`.

## Cómo funciona
- **Entrar:** con el teléfono y un PIN de 4 dígitos que genera el local o Trappi en el panel (**Repartidores**).
- **Conectarse (GO):** la app manda la ubicación cada 4 segundos mientras está conectado y mantiene la pantalla prendida.
- **Oferta:** cuando un pedido de delivery se confirma, le llega a un repartidor por vez durante 35 segundos.
  - El orden es: primero los propios del local, después la flota de Trappi, del más cercano al más lejano.
  - Suena y vibra. Muestra la ganancia (el costo de envío), la distancia al local y el recorrido.
  - Si no acepta, pasa al siguiente. Si nadie acepta, el local lo asigna a mano desde comandas.
- **Viaje:**
  1. *Retiro:* dirección del local, navegación con Google Maps o Waze, contacto y aviso de si el pedido ya está listo. Al marcar "Retiré el pedido", el cliente recibe "Tu pedido va en camino".
  2. *Entrega:* datos del cliente, cuánto cobrarle, WhatsApp o llamada y "Entregué el pedido".
- **Ganancias:** del día, de los últimos 7 y 30 días, con la lista de viajes.

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
