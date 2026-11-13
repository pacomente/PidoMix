// Extiende app.json.
// - Las notificaciones push necesitan google-services.json con la app Android "ar.trappi.repartidor"
//   (Firebase → Configuración del proyecto → Agregar app). Si el archivo no está, la app se compila igual:
//   las ofertas llegan con la app abierta.
// - versionCode (Google Play exige que suba en cada envío): sale de la versión, 1.9.0 -> 10900, 1.9.1 -> 10901.
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
