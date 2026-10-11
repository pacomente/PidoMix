import Constants from 'expo-constants';

import type { CashBox, History, RouteInfo, State } from './types';

export const API_URL = (process.env.EXPO_PUBLIC_API_URL || (Constants.expoConfig?.extra?.apiUrl as string | undefined) || 'http://localhost:8000').replace(/\/$/, '');

export class ApiError extends Error {
  constructor(message: string, public status: number, public maintenance = false) {
    super(message);
  }
}

const maintenanceListeners = new Set<() => void>();
export const onMaintenance = (fn: () => void) => { maintenanceListeners.add(fn); return () => { maintenanceListeners.delete(fn); }; };

let token: string | null = null;
export const setToken = (t: string | null) => { token = t; };

// Render (plan gratis) duerme el servidor: mientras despierta responde 502/503/504. Las consultas se reintentan.
const WAKING = new Set([502, 503, 504]);
const RETRIES = [2000, 4000, 8000, 12000];
const wait = (ms: number) => new Promise(r => setTimeout(r, ms));

async function request<T>(path: string, init: RequestInit = {}, retry = !init.method || init.method === 'GET'): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    let res: Response;
    try {
      res = await fetch(API_URL + '/api/courier/v1' + path, {
        ...init,
        headers: { 'Content-Type': 'application/json', Accept: 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}), ...(init.headers || {}) },
      });
    } catch {
      if (retry && attempt < RETRIES.length) { await wait(RETRIES[attempt]); continue; }
      throw new ApiError('Sin conexión. Revisá tus datos móviles.', 0);
    }
    if (res.status === 503) {  // app apagada desde el panel (mantenimiento) o servidor despertando
      const body = await res.clone().json().catch(() => null);
      if (body?.maintenance) {
        maintenanceListeners.forEach(fn => fn());
        throw new ApiError(body.error || 'La app está en mantenimiento.', 503, true);
      }
    }
    if (WAKING.has(res.status) && retry && attempt < RETRIES.length) { await wait(RETRIES[attempt]); continue; }
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new ApiError(data?.error || (WAKING.has(res.status) ? 'El servidor se está iniciando. Probá en un minuto.' : `Error del servidor (${res.status}).`), res.status);
    if (data === null) throw new ApiError('Respuesta inesperada del servidor.', res.status);
    return data as T;
  }
}

const post = <T>(path: string, body: object = {}, retry = false) => request<T>(path, { method: 'POST', body: JSON.stringify(body) }, retry);

export type DriverConfig = {
  app: { enabled: boolean; message: string; min_version: string; download_url: string };
  map_style: string;
  pulse_seconds: number;
  support_whatsapp: string | null;
};

export const api = {
  config: () => request<DriverConfig>('/config'),
  login: (phone: string, pin: string) => post<{ ok: true; token: string; courier: State['courier'] }>('/login', { phone, pin }),
  me: () => request<State>('/me'),
  pulse: (body: { lat?: number; lng?: number; online?: boolean }) => post<State>('/pulse', body),
  /** channel: el canal de Android de esta versión (el servidor manda las ofertas con ese canal y su sonido) */
  registerPush: (pushToken: string, channel: string) => post<{ ok: true }>('/push', { token: pushToken, channel }),
  accept: (offerId: number) => post<State>(`/offers/${offerId}/accept`),
  reject: (offerId: number) => post<State>(`/offers/${offerId}/reject`),
  pickup: (orderId: number, code = '') => post<State>(`/trip/${orderId}/pickup`, { code }),
  deliver: (orderId: number, pin = '') => post<State>(`/trip/${orderId}/deliver`, { pin }),
  release: (orderId: number) => post<State>(`/trip/${orderId}/release`),
  fail: (orderId: number, reason: string, note = '') => post<State>(`/trip/${orderId}/fail`, { reason, note }),
  earnings: () => request<History>('/earnings'),
  cashBox: () => request<CashBox>('/caja'),
  /** recorrido por calle e indicaciones hasta el destino (el backend decide cuál) */
  route: (to: 'trip' | 'suggestion', p: { lat: number; lng: number }) => request<RouteInfo>(`/route?to=${to}&lat=${p.lat}&lng=${p.lng}`, {}, false),
};
