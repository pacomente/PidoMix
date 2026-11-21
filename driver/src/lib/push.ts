import Constants from 'expo-constants';
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

import { startOfferAlarm, stopOfferAlarm } from './sounds';

Notifications.setNotificationHandler({
  handleNotification: async () => ({ shouldShowBanner: true, shouldShowList: true, shouldPlaySound: true, shouldSetBadge: false }),
});

// canal con el sonido de oferta (el sonido de un canal no se puede cambiar: por eso es uno nuevo)
export const CHANNEL = 'viajes_nuevos';
const SOUND = 'trappi_repartidor_nuevo.wav';
const OLD_CHANNELS = ['ofertas', 'viajes'];  // los de las versiones anteriores

let channelReady: Promise<void> | null = null;
function ensureChannel() {
  channelReady ??= Platform.OS === 'android'
    ? Notifications.setNotificationChannelAsync(CHANNEL, {
        name: 'Viajes nuevos',
        importance: Notifications.AndroidImportance.MAX,
        sound: SOUND,
        vibrationPattern: [0, 400, 200, 400, 200, 400],
        lightColor: '#06C167',
        lockscreenVisibility: Notifications.AndroidNotificationVisibility.PUBLIC,
        bypassDnd: true,
      }).then(() => Promise.all(OLD_CHANNELS.map(id => Notifications.deleteNotificationChannelAsync(id).catch(() => {})))).then(() => undefined)
    : Promise.resolve();
  return channelReady;
}

/** El proyecto de Expo (lo pone EAS al compilar): sin él no hay avisos en iPhone. */
function expoProjectId(): string | undefined {
  return Constants.expoConfig?.extra?.eas?.projectId ?? Constants.easConfig?.projectId ?? undefined;
}

/** Token para que las ofertas suenen con la app en segundo plano: Firebase en Android, Expo en iPhone.
 *  null si no hay permiso (o falta Firebase / el proyecto de Expo). */
export async function getPushToken(): Promise<string | null> {
  if (Platform.OS === 'web' || !Device.isDevice) return null;
  try {
    await ensureChannel();
    let perm = await Notifications.getPermissionsAsync();
    if (!perm.granted && perm.canAskAgain) {
      perm = await Notifications.requestPermissionsAsync({ ios: { allowAlert: true, allowSound: true, allowBadge: false } });
    }
    if (!perm.granted) return null;
    if (Platform.OS === 'ios') {
      const projectId = expoProjectId();
      if (!projectId) return null;
      const { data } = await Notifications.getExpoPushTokenAsync({ projectId });
      return data || null;
    }
    const { data } = await Notifications.getDevicePushTokenAsync();
    return typeof data === 'string' ? data : null;
  } catch {
    return null;
  }
}

/** Aviso fuerte de oferta nueva con la app abierta: suena y vibra cada pocos segundos hasta que acepte o rechace. */
export async function alertOffer() {
  await ensureChannel().catch(() => {});
  await startOfferAlarm();
}

export const stopAlert = stopOfferAlarm;
