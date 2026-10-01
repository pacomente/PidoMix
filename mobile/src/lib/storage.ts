import AsyncStorage from '@react-native-async-storage/async-storage';

/** Lectura/escritura JSON en el teléfono que nunca rompe la app si el almacenamiento falla. */
export async function load<T>(key: string, fallback: T): Promise<T> {
  try {
    const raw = await AsyncStorage.getItem('trappi:' + key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

export async function save(key: string, value: unknown): Promise<void> {
  try {
    await AsyncStorage.setItem('trappi:' + key, JSON.stringify(value));
  } catch {
    // sin espacio o almacenamiento no disponible: la app sigue funcionando en memoria
  }
}
