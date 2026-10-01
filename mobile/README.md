# Trappi — app móvil (Android / iOS)

App nativa para clientes hecha con **Expo (React Native) + Expo Router**. Usa la misma base de datos y reglas que la web a través de la API JSON `/api/v1` del backend (`app/routers/mobile_api.py`): comercios, menú, carrito, zonas de entrega, checkout, seguimiento del pedido y opiniones.

## Qué hace
- **Inicio:** rubros, ofertas y comercios ordenados por los que te llegan y por cercanía.
- **Ubicación:** GPS del teléfono o búsqueda de dirección. Con eso se calcula qué comercios llegan y el envío exacto según los anillos de cada local.
- **Comercio y producto:** menú por secciones, agregados obligatorios u opcionales, cantidad y opiniones.
- **Mi pedido:** el carrito se guarda en el teléfono. Los precios se actualizan con el servidor, y si algo se pausó te avisa.
- **Checkout:** delivery o retiro, datos guardados para la próxima vez, cupón y validación de zona y de pedido mínimo. El pedido entra a la pantalla de comandas igual que uno de la web.
- **Seguimiento:** los estados se actualizan solos cada 15 s, con botón de WhatsApp para confirmar y calificación cuando se entrega.

Sin login: los pedidos se guardan en el teléfono con su token firmado, como en la web.

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
- `app.json → expo.extra.apiUrl`: la URL del backend en producción. Hoy apunta a `https://pidomix.onrender.com`; cambiala si el servicio de Render tiene otro nombre o un dominio propio. En desarrollo manda `EXPO_PUBLIC_API_URL`.
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
