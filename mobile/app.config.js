// Extiende app.json.
// - Las notificaciones push de Android necesitan google-services.json (Firebase → Configuración del proyecto →
//   app Android "ar.trappi.app"). Si el archivo no está, la app se compila igual, solo que sin avisos push.
// - versionCode (Google Play exige que suba en cada envío): sale de la versión, 1.10.0 -> 11000, 1.10.1 -> 11001,
//   2.0.0 -> 20000. Para subir otra compilación a Play alcanza con subir la versión en app.json.
// - La cámara (escanear el QR de Puntos Trappi) es opcional: sin esto Google Play la toma como obligatoria y deja afuera
//   tablets, Chromebooks y otros dispositivos sin cámara trasera. Sin cámara, el código del ticket se escribe a mano.
const fs = require('fs');
const path = require('path');
const { withAndroidManifest } = require('expo/config-plugins');

const OPTIONAL_FEATURES = ['android.hardware.camera', 'android.hardware.camera.autofocus', 'android.hardware.camera.any'];

function withOptionalCamera(config) {
  return withAndroidManifest(config, cfg => {
    const manifest = cfg.modResults.manifest;
    manifest.$['xmlns:tools'] = manifest.$['xmlns:tools'] || 'http://schemas.android.com/tools';
    const features = (manifest['uses-feature'] || []).filter(f => !OPTIONAL_FEATURES.includes(f.$['android:name']));
    for (const name of OPTIONAL_FEATURES) {
      features.push({ $: { 'android:name': name, 'android:required': 'false', 'tools:replace': 'android:required' } });
    }
    manifest['uses-feature'] = features;
    return cfg;
  });
}

function versionCode(version) {
  const [major = 0, minor = 0, patch = 0] = String(version).split('.').map(n => parseInt(n, 10) || 0);
  return major * 10000 + minor * 100 + patch;
}

module.exports = ({ config }) => {
  const android = { ...config.android, versionCode: versionCode(config.version) };
  const googleServices = path.join(__dirname, 'google-services.json');
  if (fs.existsSync(googleServices)) android.googleServicesFile = './google-services.json';
  return withOptionalCamera({ ...config, android });
};
