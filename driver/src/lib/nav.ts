import { Alert, Linking, Platform } from 'react-native';

import type { Point } from './types';

export type NavTarget = Point & { address: string | null };

export function navUrl(p: NavTarget, app: 'google' | 'waze') {
  const has = p.lat !== undefined && p.lng !== undefined;
  if (app === 'waze') return has ? `https://waze.com/ul?ll=${p.lat},${p.lng}&navigate=yes` : `https://waze.com/ul?q=${encodeURIComponent(p.address || '')}&navigate=yes`;
  return `https://www.google.com/maps/dir/?api=1&travelmode=driving&destination=${has ? `${p.lat},${p.lng}` : encodeURIComponent(p.address || '')}`;
}

/** Abre la navegación con la app que eligió en Ajustes; si eligió "preguntar", le ofrece las dos. */
export function openNav(p: NavTarget, app: 'google' | 'waze' | 'ask') {
  const go = (a: 'google' | 'waze') => Linking.openURL(navUrl(p, a)).catch(() => {});
  if (app !== 'ask' || Platform.OS === 'web') { go(app === 'waze' ? 'waze' : 'google'); return; }  // Alert no tiene botones en la web
  Alert.alert('¿Con qué app navegás?', 'Podés dejar una elegida en Ajustes.', [
    { text: 'Google Maps', onPress: () => go('google') },
    { text: 'Waze', onPress: () => go('waze') },
    { text: 'Cancelar', style: 'cancel' },
  ]);
}
