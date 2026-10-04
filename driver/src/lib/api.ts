import Constants from 'expo-constants';

import type { History, State } from './types';

export const API_URL = (process.env.EXPO_PUBLIC_API_URL || (Constants.expoConfig?.extra?.apiUrl as string | undefined) || 'http://localhost:8000').replace(/\/$/, '');

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

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
    if (WAKING.has(res.status) && retry && attempt < RETRIES.length) { await wait(RETRIES[attempt]); continue; }
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new ApiError(data?.error || (WAKING.has(res.status) ? 'El servidor se está iniciando. Probá en un minuto.' : `Error del servidor (${res.status}).`), res.status);
    if (data === null) throw new ApiError('Respuesta inesperada del servidor.', res.status);
    return data as T;
  }
}

const post = <T>(path: string, body: object = {}, retry = false) => request<T>(path, { method: 'POST', body: JSON.stringify(body) }, retry);

export const api = {
  login: (phone: string, pin: string) => post<{ ok: true; token: string; courier: State['courier'] }>('/login', { phone, pin }),
  me: () => request<State>('/me'),
  pulse: (body: { lat?: number; lng?: number; online?: boolean }) => post<State>('/pulse', body),
  registerPush: (pushToken: string) => post<{ ok: true }>('/push', { token: pushToken }),
  accept: (offerId: number) => post<State>(`/offers/${offerId}/accept`),
  reject: (offerId: number) => post<State>(`/offers/${offerId}/reject`),
  pickup: (orderId: number) => post<State>(`/trip/${orderId}/pickup`),
  deliver: (orderId: number) => post<State>(`/trip/${orderId}/deliver`),
  release: (orderId: number) => post<State>(`/trip/${orderId}/release`),
  earnings: () => request<History>('/earnings'),
};
