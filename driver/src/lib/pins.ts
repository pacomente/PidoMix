import { brand } from './theme';

export type PinKind = 'store' | 'customer' | 'hotspot' | 'pickup' | 'dropoff';

/** Ícono y color de cada destino en el mapa (pickup y dropoff: los viajes de las empresas). */
export const PIN: Record<PinKind, { icon: string; color: string | null }> = {
  store: { icon: '🏪', color: null }, customer: { icon: '🏠', color: brand.money }, hotspot: { icon: '🔥', color: brand.danger },
  pickup: { icon: '🙋', color: brand.go }, dropoff: { icon: '🏁', color: brand.violet },
};
