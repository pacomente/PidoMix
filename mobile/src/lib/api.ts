import Constants from 'expo-constants';

import { reportError } from './monitoring';
import type { Home, Order, ProductDetail, Quote, Store, StoreDetail, UserLocation } from './types';

// URL del backend: EXPO_PUBLIC_API_URL (para desarrollo) o "extra.apiUrl" de app.json (producción)
export const API_URL = (process.env.EXPO_PUBLIC_API_URL || (Constants.expoConfig?.extra?.apiUrl as string | undefined) || 'http://localhost:8000').replace(/\/$/, '');

export class ApiError extends Error {
  constructor(message: string, public status: number, public maintenance = false) {
    super(message);
  }
}

// Cuando el servidor dice "app en mantenimiento", la pantalla de mantenimiento se entera al instante
const maintenanceListeners = new Set<() => void>();
export const onMaintenance = (fn: () => void) => { maintenanceListeners.add(fn); return () => { maintenanceListeners.delete(fn); }; };

// Render (plan gratis) apaga el servidor sin uso: mientras despierta responde 502/503/504
// con su propia página de error. Las consultas (GET) se reintentan solas durante ~1 minuto.
const WAKING = new Set([502, 503, 504]);
const RETRY_DELAYS_MS = [2000, 4000, 8000, 12000, 15000, 20000];
const wait = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const retries = !init?.method || init.method === 'GET' ? RETRY_DELAYS_MS : [];
  for (let attempt = 0; ; attempt++) {
    let response: Response;
    try {
      response = await fetch(API_URL + '/api/v1' + path, { ...init, headers: { 'Content-Type': 'application/json', Accept: 'application/json', ...(init?.headers || {}) } });
    } catch {
      if (attempt < retries.length) { await wait(retries[attempt]); continue; }
      throw new ApiError('Sin conexión. Revisá tu internet y probá de nuevo.', 0);
    }
    if (response.status === 503) {  // mantenimiento (apagada desde el panel) o servidor despertando
      const body = await response.clone().json().catch(() => null);
      if (body?.maintenance) {
        maintenanceListeners.forEach(fn => fn());
        throw new ApiError(body.error || 'La app está en mantenimiento.', 503, true);
      }
    }
    if (WAKING.has(response.status) && attempt < retries.length) { await wait(retries[attempt]); continue; }
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = Array.isArray(data?.detail) ? 'Revisá los datos ingresados.' : data?.detail;
      const fallback = WAKING.has(response.status)
        ? `El servidor no está respondiendo (error ${response.status}). Puede estar iniciándose: probá de nuevo en un minuto.`
        : `Ocurrió un error en el servidor (error ${response.status}). Probá de nuevo en un momento.`;
      const error = new ApiError(data?.error || detail || fallback, response.status);
      if (response.status >= 500 && !WAKING.has(response.status)) reportError(error, { path: path.split('?')[0], status: response.status });
      throw error;
    }
    if (data === null) {
      const error = new ApiError(`El servidor respondió algo inesperado (${response.status}). Revisá la dirección del servidor.`, response.status);
      reportError(error, { path: path.split('?')[0], status: response.status });
      throw error;
    }
    return data as T;
  }
}

const qs = (params: Record<string, string | number | boolean | null | undefined>) => {
  const parts = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '').map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`);
  return parts.length ? '?' + parts.join('&') : '';
};
const where = (loc: UserLocation | null) => (loc ? { lat: loc.lat, lng: loc.lng } : {});

export type AppConfig = {
  app: { enabled: boolean; message: string; min_version: string; download_url: string };
  orders: { enabled: boolean; message: string };
  support_whatsapp: string | null;
};

export const api = {
  config: () => request<AppConfig>('/config'),
  home: (loc: UserLocation | null) => request<Home>('/home' + qs(where(loc))),
  stores: (loc: UserLocation | null, filters: { q?: string; category_id?: number; sort?: string; delivery?: boolean } = {}) =>
    request<{ stores: Store[] }>('/stores' + qs({ ...where(loc), ...filters, delivery: filters.delivery || undefined })),
  store: (slug: string, loc: UserLocation | null) => request<StoreDetail>(`/stores/${encodeURIComponent(slug)}` + qs(where(loc))),
  search: (q: string, loc: UserLocation | null) => request<{ stores: Store[]; products: StoreDetail['menu'][number]['products'] }>('/search' + qs({ q, ...where(loc) })),
  product: (id: number) => request<ProductDetail>(`/products/${id}`),
  quote: (body: object) => request<Quote>('/cart/quote', { method: 'POST', body: JSON.stringify(body) }),
  createOrder: (body: object) => request<{ ok: true; id: number; token: string; whatsapp_url: string | null; total: number; pay_path: string | null }>('/orders', { method: 'POST', body: JSON.stringify(body) }),
  order: (id: number, token: string) => request<Order>(`/orders/${id}` + qs({ t: token })),
  orders: (refs: { id: number; token: string }[]) => request<{ orders: Order[] }>('/orders' + qs({ refs: refs.map(r => `${r.id}:${r.token}`).join(',') })),
  registerPush: (id: number, token: string, pushToken: string, platform: string) =>
    request<{ ok: boolean; enabled: boolean }>(`/orders/${id}/push`, { method: 'POST', body: JSON.stringify({ t: token, token: pushToken, platform }) }),
  review: (id: number, token: string, rating: number, comment: string) =>
    request<{ ok: true }>(`/orders/${id}/review`, { method: 'POST', body: JSON.stringify({ t: token, rating, comment }) }),
};
