import AsyncStorage from '@react-native-async-storage/async-storage';

const KEY = 'trappi-repartidor:';
export async function load<T>(key: string, fallback: T): Promise<T> {
  try {
    const raw = await AsyncStorage.getItem(KEY + key);
    return raw === null ? fallback : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}
export const save = (key: string, value: unknown) => AsyncStorage.setItem(KEY + key, JSON.stringify(value)).catch(() => {});
export const remove = (key: string) => AsyncStorage.removeItem(KEY + key).catch(() => {});
