import Constants from 'expo-constants';

export const APP_VERSION = Constants.expoConfig?.version ?? '1.0.0';

/** true si la versión instalada es más vieja que la mínima ("1.2" < "1.10.0"). */
export function isOutdated(current: string, minimum: string): boolean {
  const a = current.split('.').map(n => parseInt(n, 10) || 0), b = minimum.split('.').map(n => parseInt(n, 10) || 0);
  for (let i = 0; i < 3; i++) {
    if ((a[i] ?? 0) !== (b[i] ?? 0)) return (a[i] ?? 0) < (b[i] ?? 0);
  }
  return false;
}
