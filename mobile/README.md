# Trappi — app móvil (Android / iOS)

App nativa para clientes hecha con **Expo (React Native) + Expo Router**. Usa la misma base de datos y reglas que la web a través de la API JSON `/api/v1` del backend (`app/routers/mobile_api.py`): comercios, menú, carrito, zonas de entrega, checkout, seguimiento del pedido y opiniones.

## Qué hace
- **Inicio:** rubros, ofertas y comercios ordenados por los que te llegan y por cercanía.
- **Ubicación:** GPS del teléfono o búsqueda de dirección. Con eso se calcula qué comercios llegan y el envío exacto según los anillos de cada local.
- **Comercio y producto:** menú por secciones, agregados obligatorios u opcionales, cantidad y opiniones.
- **Mi pedido:** el carrito se guarda en el teléfono. Los precios se actualizan con el servidor, y si algo se pausó te avisa.
- **Checkout:** delivery o retiro, datos guardados para la próxima vez, cupón y validación de zona y de pedido mínimo. El pedido entra a la pantalla de comandas igual que uno de la web.
- **Seguimiento:** los estados se actualizan solos cada 15 s, con botón de WhatsApp para confirmar y calificación cuando se entrega.

- **Notificaciones push:** cuando el local confirma, prepara, despacha, entrega o cancela el pedido (desde el panel o desde comandas), el cliente recibe un aviso. Al tocarlo se abre el seguimiento.

Sin login: los pedidos se guardan en el teléfono con su token firmado, como en la web.

## Probarla en el celular (APK)
Cada cambio en `mobile/` compila un APK nuevo con GitHub Actions (`.github/workflows/android-apk.yml`) y lo publica en el release [`app-android`](https://github.com/pacomente/PidoMix/releases/tag/app-android). El link de descarga siempre es el mismo:

https://github.com/pacomente/PidoMix/releases/download/app-android/trappi.apk

Abrilo desde el celular, aceptá instalar apps de fuentes desconocidas y listo. Ese APK usa la firma de prueba: sirve para instalarlo a mano, no para subirlo a Play Store (para eso está `eas build --profile production`, más abajo).

## Notificaciones push
Van por **Firebase Cloud Messaging** directo (gratis, sin cuenta de Expo). La app pide permiso al confirmar el pedido y anota el teléfono en ese pedido (`POST /api/v1/orders/{id}/push`). Cada cambio de estado en `/admin/orders/{id}/status` dispara el aviso (`app/services/push.py`). Si un teléfono desinstaló la app, su token se borra solo.

Configuración, una sola vez:
1. Entrá a [console.firebase.google.com](https://console.firebase.google.com) → **Agregar proyecto** (por ejemplo "Trappi"). Google Analytics no hace falta.
2. En el proyecto: ícono de Android → paquete **`ar.trappi.app`** → **Registrar app** → descargá **`google-services.json`**.
3. Poné ese archivo en `mobile/google-services.json` y subilo al repo. No es secreto: va dentro de la app. Otra opción es guardar su contenido en el secreto `GOOGLE_SERVICES_JSON` del repo (GitHub → Settings → Secrets → Actions). El próximo APK ya sale con notificaciones.
4. En Firebase: ⚙ **Configuración del proyecto → Cuentas de servicio → Generar nueva clave privada**. Se descarga un `.json`, que **sí es secreto**.
5. En Render → servicio → **Environment** → agregá `FIREBASE_SERVICE_ACCOUNT` con **todo el contenido** de ese `.json` y guardá (Render redespliega solo).

Sin el paso 3 la app funciona igual, pero sin avisos. Sin el paso 5 el backend no manda nada.

## Desarrollo
```bash
cd mobile
npm install
EXPO_PUBLIC_API_URL=http://<IP-de-tu-PC>:8000 npx expo start
```
Escaneá el QR con **Expo Go**: todos los módulos que usa la app vienen incluidos, así que no hace falta una build de desarrollo. El backend tiene que estar corriendo (`uvicorn app.main:app --host 0.0.0.0`) y el teléfono, en la misma red Wi-Fi.

Antes de subir cambios:
```bash
npm run typecheck && npm run lint && npm run export:android
```

## Configuración
- `app.json → expo.extra.apiUrl`: la URL del backend en producción. Apunta a `https://pidomix-1.onrender.com` (el servicio de Render); cambiala si pasás a un dominio propio. En desarrollo manda `EXPO_PUBLIC_API_URL`.
- El identificador `ar.trappi.app` (Android e iOS) **no se puede cambiar** una vez publicada la app: definilo antes de la primera subida.
- Íconos y splash: `assets/`.

## Publicar (EAS, en la nube, sin Android Studio ni Xcode)
```bash
npm install -g eas-cli   # o: npx eas-cli@latest <comando>
eas login
eas init                 # vincula el proyecto a tu cuenta de Expo (agrega el projectId a app.json)

eas build -p android --profile preview      # APK para probar e instalar directo
eas build -p android --profile production   # AAB para Google Play
eas build -p ios --profile production       # requiere cuenta de Apple Developer
eas submit -p android                       # sube la última build a Play Console
eas submit -p ios                           # sube a App Store Connect / TestFlight
```
Para actualizaciones solo de JavaScript (sin pasar por la tienda) se puede sumar `eas update` más adelante.
