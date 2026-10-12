import * as Location from 'expo-location';
import { activateKeepAwakeAsync, deactivateKeepAwake } from 'expo-keep-awake';
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { AppState } from 'react-native';

import { api, ApiError, setToken } from '@/lib/api';
import { alertOffer, CHANNEL, getPushToken, stopAlert } from '@/lib/push';
import { playConfirm } from '@/lib/sounds';
import { load, remove, save } from '@/lib/storage';
import { useConfig } from '@/state/config';
import type { Delivered, State } from '@/lib/types';

type Coords = { lat: number; lng: number };

type Session = {
  ready: boolean;
  loggedIn: boolean;
  state: State | null;
  position: Coords | null;
  error: string | null;
  busy: boolean;
  lastDelivery: Delivered | null;
  login: (phone: string, pin: string) => Promise<void>;
  logout: () => Promise<void>;
  goOnline: () => Promise<void>;
  goOffline: () => Promise<void>;
  act: (action: 'accept' | 'reject' | 'pickup' | 'release', id: number) => Promise<void>;
  /** entrega con el PIN del cliente; devuelve el error para mostrarlo junto al PIN (o null si salió bien) */
  deliver: (orderId: number, pin: string) => Promise<string | null>;
  /** retiro con el código que le dicta el local; devuelve el error para mostrarlo junto al código (o null si salió bien) */
  pickup: (orderId: number, code: string) => Promise<string | null>;
  /** no pudo entregar: avisa al local (el pedido sigue en sus manos) */
  fail: (orderId: number, reason: string) => Promise<void>;
  clearDelivery: () => void;
  refresh: () => Promise<void>;
};

const Ctx = createContext<Session | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const pulseMs = Math.max(3, useConfig().pulse_seconds) * 1000;  // configurable desde el panel
  const [ready, setReady] = useState(false);
  const [loggedIn, setLoggedIn] = useState(false);
  const [state, setState] = useState<State | null>(null);
  const [position, setPosition] = useState<Coords | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [lastDelivery, setLastDelivery] = useState<Session['lastDelivery']>(null);
  const posRef = useRef<Coords | null>(null);
  const watchRef = useRef<Location.LocationSubscription | null>(null);
  const offerSeen = useRef<number | null>(null);

  const apply = useCallback((s: State) => {
    setState(s);
    setError(null);
    if (s.offer && s.offer.id !== offerSeen.current) {
      offerSeen.current = s.offer.id;
      alertOffer();
    }
    if (!s.offer) stopAlert();
  }, []);

  const handleError = useCallback(async (e: unknown) => {
    if (e instanceof ApiError && e.status === 401) {
      setToken(null); await remove('token'); setLoggedIn(false); setState(null);
      setError('Tu sesión se cerró. Volvé a entrar con tu PIN.');
      return;
    }
    setError(e instanceof Error ? e.message : 'Algo salió mal.');
  }, []);

  const registerPush = useCallback(async () => {
    const t = await getPushToken();
    if (t) api.registerPush(t, CHANNEL).catch(() => {});
  }, []);

  // sesion guardada en el telefono
  useEffect(() => {
    (async () => {
      const t = await load<string | null>('token', null);
      if (t) {
        setToken(t);
        setLoggedIn(true);
        try { apply(await api.me()); registerPush(); } catch (e) { await handleError(e); }
      }
      setReady(true);
    })();
  }, [apply, handleError, registerPush]);

  const startGps = useCallback(async () => {
    const perm = await Location.requestForegroundPermissionsAsync();
    if (!perm.granted) throw new Error('Necesitamos tu ubicación para ofrecerte viajes cercanos. Activala en los ajustes del teléfono.');
    if (!(await Location.hasServicesEnabledAsync())) throw new Error('Prendé la ubicación (GPS) del teléfono.');
    const first = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High }).catch(() => null);
    if (first) { posRef.current = { lat: first.coords.latitude, lng: first.coords.longitude }; setPosition(posRef.current); }
    watchRef.current?.remove();
    watchRef.current = await Location.watchPositionAsync({ accuracy: Location.Accuracy.High, distanceInterval: 15, timeInterval: 5000 }, loc => {
      posRef.current = { lat: loc.coords.latitude, lng: loc.coords.longitude };
      setPosition(posRef.current);
    });
  }, []);

  const stopGps = useCallback(() => { watchRef.current?.remove(); watchRef.current = null; }, []);

  const online = !!state?.courier.online;
  const active = online || !!state?.trip;

  // el pulso: ubicacion -> oferta / viaje en curso
  const pulse = useCallback(async () => {
    try { apply(await api.pulse({ ...(posRef.current ?? {}) })); } catch (e) { await handleError(e); }
  }, [apply, handleError]);

  useEffect(() => {
    if (!loggedIn || !active) return;
    if (!watchRef.current) startGps().catch(e => setError(e.message));
    activateKeepAwakeAsync('trappi-online').catch(() => {});
    const timer = setInterval(pulse, pulseMs);
    const sub = AppState.addEventListener('change', s => s === 'active' && pulse());
    return () => { clearInterval(timer); sub.remove(); deactivateKeepAwake('trappi-online').catch(() => {}); };
  }, [loggedIn, active, pulse, startGps, pulseMs]);

  useEffect(() => { if (!active) stopGps(); }, [active, stopGps]);

  const login = useCallback(async (phone: string, pin: string) => {
    setBusy(true); setError(null);
    try {
      const r = await api.login(phone, pin);
      setToken(r.token); await save('token', r.token); setLoggedIn(true);
      apply(await api.me());
      registerPush();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No pudimos entrar.');
      throw e;
    } finally { setBusy(false); }
  }, [apply, registerPush]);

  const goOnline = useCallback(async () => {
    setBusy(true); setError(null);
    try {
      await startGps();
      apply(await api.pulse({ ...(posRef.current ?? {}), online: true }));
    } catch (e) { await handleError(e); } finally { setBusy(false); }
  }, [apply, handleError, startGps]);

  const goOffline = useCallback(async () => {
    setBusy(true);
    try { apply(await api.pulse({ online: false })); } catch (e) { await handleError(e); } finally { setBusy(false); }
  }, [apply, handleError]);

  const isOnline = !!state?.courier.online;
  const logout = useCallback(async () => {
    try { if (isOnline) await api.pulse({ online: false }); } catch { /* sin conexion: se desconecta solo en 5 min */ }
    stopGps(); setToken(null); await remove('token'); setLoggedIn(false); setState(null);
  }, [isOnline, stopGps]);

  const act = useCallback(async (action: 'accept' | 'reject' | 'pickup' | 'release', id: number) => {
    setBusy(true);
    try {
      const s = await api[action](id);
      if (action === 'accept' || action === 'reject') stopAlert();
      if (action === 'accept' || action === 'pickup') playConfirm();
      if (s.delivered) setLastDelivery(s.delivered);
      apply(s);
    } catch (e) {
      await handleError(e);
      pulse();
    } finally { setBusy(false); }
  }, [apply, handleError, pulse]);

  const deliver = useCallback(async (orderId: number, pin: string) => {
    setBusy(true);
    try {
      const s = await api.deliver(orderId, pin);
      playConfirm();
      if (s.delivered) setLastDelivery(s.delivered);
      apply(s);
      return null;
    } catch (e) {
      if (e instanceof ApiError && (e.status === 409 || e.status === 429)) return e.message;  // PIN mal: se muestra en el panel
      await handleError(e);
      pulse();
      return e instanceof Error ? e.message : 'No se pudo marcar entregado.';
    } finally { setBusy(false); }
  }, [apply, handleError, pulse]);

  const pickup = useCallback(async (orderId: number, code: string) => {
    setBusy(true);
    try {
      apply(await api.pickup(orderId, code));
      playConfirm();
      return null;
    } catch (e) {
      if (e instanceof ApiError && (e.status === 409 || e.status === 429)) return e.message;  // código mal: se muestra en el panel
      await handleError(e);
      pulse();
      return e instanceof Error ? e.message : 'No se pudo marcar retirado.';
    } finally { setBusy(false); }
  }, [apply, handleError, pulse]);

  const fail = useCallback(async (orderId: number, reason: string) => {
    setBusy(true);
    try { apply(await api.fail(orderId, reason)); } catch (e) { await handleError(e); pulse(); } finally { setBusy(false); }
  }, [apply, handleError, pulse]);

  const value = useMemo<Session>(() => ({
    ready, loggedIn, state, position, error, busy, lastDelivery, login, logout, goOnline, goOffline, act, deliver, pickup, fail,
    clearDelivery: () => setLastDelivery(null), refresh: pulse,
  }), [ready, loggedIn, state, position, error, busy, lastDelivery, login, logout, goOnline, goOffline, act, deliver, pickup, fail, pulse]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSession(): Session {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error('useSession debe usarse dentro de <SessionProvider>');
  return ctx;
}
