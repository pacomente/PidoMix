import Constants from 'expo-constants';

import type { CashBox, Chat, ChatMessage, History, RouteInfo, State } from './types';

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
/** para mostrar las fotos del pedido (se piden con el token del repartidor) */
export const authImage = (path: string) => ({ uri: API_URL + path, headers: token ? { Authorization: 'Bearer ' + token } : undefined });

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

/** sube una foto (multipart): uri de la cámara del celular */
async function upload<T>(path: string, uri: string, fields: Record<string, string> = {}): Promise<T> {
  const form = new FormData();
  Object.entries(fields).forEach(([k, v]) => form.append(k, v));
  if (uri.startsWith('blob:') || uri.startsWith('data:')) {  // web (solo para probar la interfaz)
    form.append('photo', await (await fetch(uri)).blob(), 'foto.jpg');
  } else {
    form.append('photo', { uri, name: 'foto.jpg', type: 'image/jpeg' } as unknown as Blob);
  }
  let res: Response;
  try {
    res = await fetch(API_URL + '/api/courier/v1' + path, { method: 'POST', body: form, headers: { Accept: 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}) } });
  } catch {
    throw new ApiError('Sin conexión. Revisá tus datos móviles y probá de nuevo.', 0);
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(data?.error || `Error del servidor (${res.status}).`, res.status);
  return data as T;
}

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
  /** llegó a la puerta (el backend valida el GPS) */
  arrived: (orderId: number, p: { lat: number; lng: number } | null) => post<State>(`/trip/${orderId}/arrived`, p ?? {}),
  /** el cliente no apareció: cancela con la foto de prueba */
  noShow: (orderId: number, uri: string) => upload<State>(`/trip/${orderId}/noshow`, uri),
  deliveryPhoto: (orderId: number, uri: string) => upload<State>(`/trip/${orderId}/photo`, uri),
  chat: (orderId: number, thread: string, after = 0) => request<Chat>(`/trip/${orderId}/chat?thread=${thread}&after=${after}`, {}, false),
  chatSend: (orderId: number, thread: string, text: string) => post<{ ok: true; message: ChatMessage }>(`/trip/${orderId}/chat`, { thread, text }),
  chatPhoto: (orderId: number, thread: string, uri: string) => upload<{ ok: true; message: ChatMessage }>(`/trip/${orderId}/chat/photo`, uri, { thread }),
  /** asistente de voz: el texto que dijo el repartidor -> respuesta para decir en voz alta y una acción */
  assistant: (text: string, p: { lat: number; lng: number } | null) =>
    post<{ reply: string; action: { type: 'mute' | 'unmute' | 'navigate_suggestion' | 'open_chat' | 'refresh'; thread?: 'cliente' | 'local' } | null; state: State }>('/assistant', { text, ...(p ?? {}) }),
  /** recorrido por calle e indicaciones hasta el destino (el backend decide cuál) */
  route: (to: 'trip' | 'suggestion', p: { lat: number; lng: number }) => request<RouteInfo>(`/route?to=${to}&lat=${p.lat}&lng=${p.lng}`, {}, false),
};
