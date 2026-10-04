import * as Sentry from '@sentry/react-native';
import Constants from 'expo-constants';

// DSN de Sentry de la app: EXPO_PUBLIC_SENTRY_DSN (al compilar) o "extra.sentryDsn" de app.json. Vacío = apagado.
const DSN = (process.env.EXPO_PUBLIC_SENTRY_DSN || (Constants.expoConfig?.extra?.sentryDsn as string | undefined) || '').trim();

export const monitoringEnabled = !!DSN && !__DEV__;

if (monitoringEnabled) {
  Sentry.init({
    dsn: DSN,
    environment: 'production',
    release: `trappi-repartidor@${Constants.expoConfig?.version ?? '1.0.0'}`,
    sendDefaultPii: false,
    tracesSampleRate: 0,
    // los pedidos llevan nombre, teléfono y dirección: no se mandan cuerpos de requests ni el token de seguimiento
    beforeBreadcrumb(crumb) {
      if (crumb.category === 'fetch' || crumb.category === 'xhr') {
        const url = typeof crumb.data?.url === 'string' ? crumb.data.url.replace(/([?&](?:t|refs)=)[^&]*/g, '$1[oculto]') : crumb.data?.url;
        return { ...crumb, data: { ...crumb.data, url } };
      }
      return crumb;
    },
  });
}

/** Errores inesperados (no los de "sin conexión" o validación, que ya se le muestran al usuario). */
export function reportError(error: unknown, context?: Record<string, unknown>) {
  if (monitoringEnabled) Sentry.captureException(error, context ? { extra: context } : undefined);
}

export const wrapRoot = <P extends Record<string, unknown>>(Component: React.ComponentType<P>) => (monitoringEnabled ? Sentry.wrap(Component) : Component);
