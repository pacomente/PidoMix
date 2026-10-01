import Constants from 'expo-constants';

import type { Home, Order, ProductDetail, Quote, Store, StoreDetail, UserLocation } from './types';

// URL del backend: EXPO_PUBLIC_API_URL (para desarrollo) o "extra.apiUrl" de app.json (producción)
export const API_URL = (process.env.EXPO_PUBLIC_API_URL || (Constants.expoConfig?.extra?.apiUrl as string | undefined) || 'http://localhost:8000').replace(/\/$/, '');

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(API_URL + '/api/v1' + path, { ...init, headers: { 'Content-Type': 'application/json', Accept: 'application/json', ...(init?.headers || {}) } });
  } catch {
    throw new ApiError('Sin conexión. Revisá tu internet y probá de nuevo.', 0);
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(data?.detail) ? 'Revisá los datos ingresados.' : data?.detail;
    throw new ApiError(data?.error || detail || 'Ocurrió un error. Probá de nuevo en un momento.', response.status);
  }
  return data as T;
}

const qs = (params: Record<string, string | number | boolean | null | undefined>) => {
  const parts = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '').map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`);
  return parts.length ? '?' + parts.join('&') : '';
};
const where = (loc: UserLocation | null) => (loc ? { lat: loc.lat, lng: loc.lng } : {});

export const api = {
  home: (loc: UserLocation | null) => request<Home>('/home' + qs(where(loc))),
  stores: (loc: UserLocation | null, filters: { q?: string; category_id?: number; sort?: string; delivery?: boolean } = {}) =>
    request<{ stores: Store[] }>('/stores' + qs({ ...where(loc), ...filters, delivery: filters.delivery || undefined })),
  store: (slug: string, loc: UserLocation | null) => request<StoreDetail>(`/stores/${encodeURIComponent(slug)}` + qs(where(loc))),
  search: (q: string, loc: UserLocation | null) => request<{ stores: Store[]; products: StoreDetail['menu'][number]['products'] }>('/search' + qs({ q, ...where(loc) })),
  product: (id: number) => request<ProductDetail>(`/products/${id}`),
  quote: (body: object) => request<Quote>('/cart/quote', { method: 'POST', body: JSON.stringify(body) }),
  createOrder: (body: object) => request<{ ok: true; id: number; token: string; whatsapp_url: string | null; total: number }>('/orders', { method: 'POST', body: JSON.stringify(body) }),
  order: (id: number, token: string) => request<Order>(`/orders/${id}` + qs({ t: token })),
  orders: (refs: { id: number; token: string }[]) => request<{ orders: Order[] }>('/orders' + qs({ refs: refs.map(r => `${r.id}:${r.token}`).join(',') })),
  review: (id: number, token: string, rating: number, comment: string) =>
    request<{ ok: true }>(`/orders/${id}/review`, { method: 'POST', body: JSON.stringify({ t: token, rating, comment }) }),
};
