import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { api } from './api';
import type { Directions, RouteInfo, RouteStep } from './types';

type P = { lat: number; lng: number };

/** distancia en metros (aproximación plana: alcanza para unos pocos km) */
export function meters(a: P, b: P) {
  const k = 111_320, x = (b.lng - a.lng) * k * Math.cos(((a.lat + b.lat) / 2) * Math.PI / 180), y = (b.lat - a.lat) * k;
  return Math.sqrt(x * x + y * y);
}

/** índice del vértice del recorrido más cercano al punto, y a cuántos metros está */
function nearest(p: P, d: Directions): [number, number] {
  let best = Infinity, at = 0;
  d.geometry.forEach(([lng, lat], i) => {
    const m = meters(p, { lat, lng });
    if (m < best) { best = m; at = i; }
  });
  return [at, best];
}

export function fmtMeters(m: number) {
  if (m >= 1000) return `${(m / 1000).toFixed(1).replace('.', ',')} km`;
  return `${Math.max(10, Math.round(m / 10) * 10)} m`;
}

const OFF_ROUTE_M = 70;  // más lejos que esto del recorrido: se recalcula
const REFRESH_MS = 90_000;
const MIN_GAP_MS = 15_000;  // entre recálculos por desvío (cuida el servidor de rutas)

/**
 * Indicaciones para llegar al destino del viaje (o a la zona sugerida).
 * key cambia cuando cambia el destino (retiró el pedido, aceptó otro, eligió ir a la zona).
 * El próximo giro sale de dónde está el repartidor sobre el recorrido (no se guarda estado).
 */
export function useGuidance(to: 'trip' | 'suggestion' | null, key: string, me: P | null) {
  const [loaded, setLoaded] = useState<{ key: string; info: RouteInfo | null; at: number } | null>(null);
  const meRef = useRef(me);
  const loading = useRef(false);
  useEffect(() => { meRef.current = me; }, [me]);

  const load = useCallback(async (forKey: string) => {
    const p = meRef.current;
    if (!to || !p || loading.current) return;
    loading.current = true;
    let info: RouteInfo | null = null;
    try { info = await api.route(to, p); } catch { /* sin ruta: el mapa dibuja la línea recta */ }
    loading.current = false;
    setLoaded({ key: forKey, info, at: Date.now() });
  }, [to]);

  const fullKey = `${to}|${key}`;
  const current = to && loaded?.key === fullKey ? loaded : null;
  const info = current?.info ?? null;
  const d = info?.directions ?? null;

  // pide la ruta al cambiar de destino; la recalcula si se desvía o cada tanto
  const hasPos = !!me;
  useEffect(() => {
    if (!to || !hasPos) return;
    if (!current) { load(fullKey); return; }
    const p = meRef.current;
    const age = Date.now() - current.at;
    const stale = age > (d ? REFRESH_MS : 20_000);
    if (stale || (age > MIN_GAP_MS && d && p && nearest(p, d)[1] > OFF_ROUTE_M)) load(fullKey);
  }, [to, fullKey, hasPos, me, current, d, load]);

  const stepAt = useMemo(() => (d ? d.steps.map(st => nearest(st, d)[0]) : []), [d]);
  let step: RouteStep | null = null;
  if (d && d.steps.length) {
    const mine = me ? nearest(me, d)[0] : 0;
    const i = d.steps.findIndex((_, n) => n > 0 && stepAt[n] > mine);
    step = d.steps[i === -1 ? d.steps.length - 1 : i];
  }
  const toStep = step && me ? meters(me, step) : null;
  return { info, directions: d, step, toStep };
}

/** ícono de Ionicons para cada maniobra */
export function stepIcon(step: RouteStep | null): string {
  if (!step) return 'navigate';
  if (step.type === 'arrive') return 'flag';
  if (step.type?.startsWith('roundabout') || step.type === 'rotary' || step.type?.startsWith('exit')) return 'refresh';
  const m = step.modifier || '';
  if (m.includes('uturn')) return 'return-down-back';
  if (m.includes('right')) return 'arrow-redo';
  if (m.includes('left')) return 'arrow-undo';
  return 'arrow-up';
}
