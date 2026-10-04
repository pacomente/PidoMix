import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { Platform, Vibration } from 'react-native';

Notifications.setNotificationHandler({
  handleNotification: async () => ({ shouldShowBanner: true, shouldShowList: true, shouldPlaySound: true, shouldSetBadge: false }),
});

// canal con el sonido de oferta (el sonido de un canal no se puede cambiar: por eso es uno nuevo)
const CHANNEL = 'ofertas';
const SOUND = 'trappi_viaje.wav';

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
      }).then(() => Notifications.deleteNotificationChannelAsync('viajes').catch(() => {})).then(() => undefined) // el canal de la versión anterior
    : Promise.resolve();
  return channelReady;
}

/** Token de Firebase para que las ofertas suenen con la app en segundo plano. null si no hay permiso o Firebase. */
export async function getPushToken(): Promise<string | null> {
  if (Platform.OS === 'web' || !Device.isDevice) return null;
  try {
    await ensureChannel();
    let perm = await Notifications.getPermissionsAsync();
    if (!perm.granted && perm.canAskAgain) perm = await Notifications.requestPermissionsAsync();
    if (!perm.granted) return null;
    const { data } = await Notifications.getDevicePushTokenAsync();
    return typeof data === 'string' ? data : null;
  } catch {
    return null;
  }
}

/** Aviso fuerte de oferta nueva con la app abierta: vibra y suena. */
export async function alertOffer(earnings: string, store: string) {
  Vibration.vibrate([0, 500, 250, 500, 250, 500]);
  try {
    await ensureChannel();
    await Notifications.scheduleNotificationAsync({
      content: { title: `Nuevo viaje · ${earnings}`, body: `Retirar en ${store}`, sound: SOUND },
      trigger: Platform.OS === 'android' ? { channelId: CHANNEL } : null,
    });
  } catch {
    // sin permiso de notificaciones queda la vibración y la tarjeta en pantalla
  }
}

export const stopAlert = () => Vibration.cancel();
