// Extiende app.json. Las notificaciones push necesitan google-services.json con la app Android
// "ar.trappi.repartidor" (Firebase → Configuración del proyecto → Agregar app). Si el archivo
// no está, la app se compila igual: las ofertas llegan con la app abierta.
const fs = require('fs');
const path = require('path');

module.exports = ({ config }) => {
  // version web para iPhone sin App Store (trappi.com.ar/repartidor): EXPO_WEB_BASE=/repartidor npm run export:web
  if (process.env.EXPO_WEB_BASE) config = { ...config, experiments: { ...config.experiments, baseUrl: process.env.EXPO_WEB_BASE } };
  const googleServices = path.join(__dirname, 'google-services.json');
  if (!fs.existsSync(googleServices)) return config;
  return { ...config, android: { ...config.android, googleServicesFile: './google-services.json' } };
};
