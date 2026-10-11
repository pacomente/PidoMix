import * as ImagePicker from 'expo-image-picker';
import { Platform } from 'react-native';

/** Saca una foto con la cámara (en la web, elige un archivo). Devuelve la uri o null si canceló o no dio permiso.
 * Calidad media: el servidor igual la achica y le saca los datos de ubicación. */
export async function takePhoto(): Promise<string | null> {
  try {
    if (Platform.OS !== 'web') {
      const perm = await ImagePicker.requestCameraPermissionsAsync();
      if (!perm.granted) return null;
      const r = await ImagePicker.launchCameraAsync({ mediaTypes: ['images'], quality: 0.5, exif: false });
      return r.canceled ? null : r.assets[0]?.uri ?? null;
    }
    const r = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], quality: 0.5 });
    return r.canceled ? null : r.assets[0]?.uri ?? null;
  } catch {
    return null;
  }
}
