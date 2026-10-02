// Extiende app.json. Las notificaciones push de Android necesitan google-services.json
// (Firebase → Configuración del proyecto → app Android "ar.trappi.app"). Si el archivo no está,
// la app se compila igual, solo que sin avisos push.
const fs = require('fs');
const path = require('path');

module.exports = ({ config }) => {
  const googleServices = path.join(__dirname, 'google-services.json');
  if (!fs.existsSync(googleServices)) return config;
  return { ...config, android: { ...config.android, googleServicesFile: './google-services.json' } };
};
