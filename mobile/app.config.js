// Extiende app.json.
// - Las notificaciones push de Android necesitan google-services.json (Firebase → Configuración del proyecto →
//   app Android "ar.trappi.app"). Si el archivo no está, la app se compila igual, solo que sin avisos push.
// - versionCode (Google Play exige que suba en cada envío): sale de la versión, 1.10.0 -> 11000, 1.10.1 -> 11001,
//   2.0.0 -> 20000. Para subir otra compilación a Play alcanza con subir la versión en app.json.
const fs = require('fs');
const path = require('path');

function versionCode(version) {
  const [major = 0, minor = 0, patch = 0] = String(version).split('.').map(n => parseInt(n, 10) || 0);
  return major * 10000 + minor * 100 + patch;
}

module.exports = ({ config }) => {
  const android = { ...config.android, versionCode: versionCode(config.version) };
  const googleServices = path.join(__dirname, 'google-services.json');
  if (fs.existsSync(googleServices)) android.googleServicesFile = './google-services.json';
  return { ...config, android };
};
