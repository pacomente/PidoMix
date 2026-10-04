// Metro con la configuración de Sentry: agrega los "debug ids" para ver el código real en los errores
const { getSentryExpoConfig } = require('@sentry/react-native/metro');

module.exports = getSentryExpoConfig(__dirname);
