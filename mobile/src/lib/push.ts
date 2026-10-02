import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

import { api } from './api';

// Los avisos de pedidos se muestran también con la app abierta
Notifications.setNotificationHandler({
  handleNotification: async () => ({ shouldShowBanner: true, shouldShowList: true, shouldPlaySound: true, shouldSetBadge: false }),
});

let cached: Promise<string | null> | null = null;
const registered = new Set<string>();

/**
 * Token de Firebase del teléfono para recibir avisos de los pedidos. Pide permiso la primera vez.
 * Devuelve null si el usuario no lo da, en emulador/web, o si la app se compiló sin Firebase.
 */
export function getPushToken(): Promise<string | null> {
  if (Platform.OS === 'web' || !Device.isDevice) return Promise.resolve(null);
  cached ??= (async () => {
    try {
      if (Platform.OS === 'android') {
        await Notifications.setNotificationChannelAsync('pedidos', {
          name: 'Estado de tus pedidos',
          importance: Notifications.AndroidImportance.HIGH,
          vibrationPattern: [0, 250, 150, 250],
          lightColor: '#6C2BD9',
        });
      }
      let perm = await Notifications.getPermissionsAsync();
      if (!perm.granted && perm.canAskAgain) perm = await Notifications.requestPermissionsAsync();
      if (!perm.granted) return null;
      const { data } = await Notifications.getDevicePushTokenAsync();
      return typeof data === 'string' ? data : null;
    } catch {
      return null;
    }
  })().then(token => {
    if (!token) cached = null; // se vuelve a intentar la próxima vez (por si después dan el permiso)
    return token;
  });
  return cached;
}

/** Igual que getPushToken pero sin trabar el checkout si el sistema tarda en responder. */
export function getPushTokenQuick(ms = 4000): Promise<string | null> {
  return Promise.race([getPushToken(), new Promise<null>(resolve => setTimeout(() => resolve(null), ms))]);
}

/** Asocia el teléfono a un pedido en curso (una vez por sesión). */
export async function registerOrderPush(orderId: number, orderToken: string) {
  const token = await getPushToken();
  const key = `${orderId}:${token}`;
  if (!token || registered.has(key)) return;
  try {
    await api.registerPush(orderId, orderToken, token, Platform.OS);
    registered.add(key);
  } catch {
    // sin conexión: se reintenta la próxima vez que se abra el pedido
  }
}

/** order_id que viene en los datos de una notificación de Trappi. */
export function orderIdFrom(notification: Notifications.Notification): number | null {
  const id = Number((notification.request.content.data as { order_id?: unknown } | null)?.order_id);
  return Number.isFinite(id) && id > 0 ? id : null;
}
