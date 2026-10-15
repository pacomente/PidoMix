import { Camera, GeoJSONSource, Layer, Map, ViewAnnotation, type CameraRef } from '@maplibre/maplibre-react-native';
import { useEffect, useMemo, useRef } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { brand } from '@/lib/theme';
import { useConfig } from '@/state/config';
import { useColors } from '@/state/prefs';


type P = { lat: number; lng: number };
/** la ubicación del repartidor; heading/speed vienen del GPS (rumbo en grados y m/s) */
export type Me = P & { heading?: number | null; speed?: number | null };
export type MapTarget = { kind: 'store' | 'customer' | 'hotspot'; point: P; label: string };
export type MapHotspot = { lat: number; lng: number; radius_m: number; orders: number };

const lngLat = (p: P): [number, number] => [p.lng, p.lat];
const MOVING_MS = 1.5;  // más rápido que esto (m/s) el mapa gira hacia donde va

/** círculo como polígono (MapLibre pinta círculos en píxeles; acá tiene que ser en metros) */
function circle(h: MapHotspot, sides = 32): [number, number][] {
  const out: [number, number][] = [];
  const dLat = h.radius_m / 111_320, dLng = dLat / Math.cos(h.lat * Math.PI / 180);
  for (let i = 0; i <= sides; i++) {
    const a = (i / sides) * 2 * Math.PI;
    out.push([h.lng + dLng * Math.cos(a), h.lat + dLat * Math.sin(a)]);
  }
  return out;
}

/** Mapa a pantalla completa: el repartidor, el local y el cliente, la ruta por calle al próximo destino
 * (o una línea recta si no hay ruta) y las zonas con pedidos esperando en rojo.
 * follow: la cámara lo sigue de cerca, inclinada y girando hacia donde va (como un GPS); si mueve el mapa
 * con el dedo, avisa con onUserMove para que se apague. Sin follow muestra todo el recorrido.
 * recenter: cambiarlo vuelve a encuadrar (el botón de recentrar). */
export function DriverMap({ me, targets, bottomInset, path, hotspots = [], follow = false, recenter = 0, onUserMove }: {
  me: Me | null; targets: MapTarget[]; bottomInset: number; path?: [number, number][] | null; hotspots?: MapHotspot[];
  follow?: boolean; recenter?: number; onUserMove?: () => void;
}) {
  const { map_style: day, map_style_night: night } = useConfig();  // proveedor elegido en el panel (por defecto OpenFreeMap)
  const c = useColors();
  const mapStyle = c.dark && night ? night : day;
  const camera = useRef<CameraRef>(null);
  const points = useMemo(() => [...(me ? [me] : []), ...targets.map(t => t.point)], [me, targets]);
  const key = points.map(p => `${p.lat.toFixed(4)},${p.lng.toFixed(4)}`).join('|');
  const padding = { top: 140, left: 60, right: 60, bottom: bottomInset + 40 };

  // seguirlo: centrado en él, más cerca y mirando para adelante
  const moving = !!me && (me.speed ?? 0) > MOVING_MS && me.heading !== null && me.heading !== undefined && me.heading >= 0;
  useEffect(() => {
    if (!follow || !me || !camera.current) return;
    camera.current.easeTo({ center: lngLat(me), zoom: 16.5, pitch: 45, ...(moving ? { bearing: me.heading! } : {}),
      padding: { top: 0, left: 0, right: 0, bottom: bottomInset * 0.6 }, duration: 900 });
  }, [follow, me?.lat, me?.lng, moving, bottomInset, recenter]); // eslint-disable-line react-hooks/exhaustive-deps

  // vista general: todos los puntos en pantalla
  useEffect(() => {
    if (follow || !camera.current || !points.length) return;
    if (points.length === 1) {
      camera.current.easeTo({ center: lngLat(points[0]), zoom: 15, pitch: 0, bearing: 0, duration: 600 });
      return;
    }
    const lngs = points.map(p => p.lng), lats = points.map(p => p.lat);
    camera.current.fitBounds([Math.min(...lngs), Math.min(...lats), Math.max(...lngs), Math.max(...lats)], { padding, duration: 700 });
  }, [follow, key, bottomInset, recenter]); // eslint-disable-line react-hooks/exhaustive-deps

  const next = targets[0];
  const real = !!path && path.length > 1;
  const route = real
    ? { type: 'Feature' as const, properties: {}, geometry: { type: 'LineString' as const, coordinates: path! } }
    : me && next ? { type: 'Feature' as const, properties: {}, geometry: { type: 'LineString' as const, coordinates: [lngLat(me), lngLat(next.point)] } } : null;
  const zones = useMemo(() => ({
    type: 'FeatureCollection' as const,
    features: hotspots.map((h, i) => ({ type: 'Feature' as const, id: i, properties: { orders: h.orders }, geometry: { type: 'Polygon' as const, coordinates: [circle(h)] } })),
  }), [hotspots]);

  return (
    <Map style={StyleSheet.absoluteFill} mapStyle={mapStyle} logo={false} compass={false} attributionPosition={{ top: 8, right: 8 }}
      onRegionWillChange={e => { if (e.nativeEvent.userInteraction) onUserMove?.(); }}>
      <Camera ref={camera} initialViewState={{ center: me ? lngLat(me) : [-62.2663, -38.7183], zoom: 14 }} />
      {hotspots.length > 0 && (
        <GeoJSONSource id="demanda" data={zones}>
          <Layer id="demanda-relleno" type="fill" paint={{ 'fill-color': brand.danger, 'fill-opacity': 0.22 }} />
          <Layer id="demanda-borde" type="line" paint={{ 'line-color': brand.danger, 'line-width': 2, 'line-opacity': 0.7 }} />
        </GeoJSONSource>
      )}
      {route && (
        <GeoJSONSource id="ruta" data={route}>
          <Layer id="ruta-borde" type="line" paint={{ 'line-color': c.dark ? '#0B1A33' : '#FFFFFF', 'line-width': real ? 11 : 8 }} layout={{ 'line-cap': 'round', 'line-join': 'round' }} />
          {real
            ? <Layer id="ruta-linea" type="line" paint={{ 'line-color': brand.go, 'line-width': 7 }} layout={{ 'line-cap': 'round', 'line-join': 'round' }} />
            : <Layer id="ruta-linea" type="line" paint={{ 'line-color': c.ink, 'line-width': 4, 'line-dasharray': [1.5, 1.5] }} layout={{ 'line-cap': 'round' }} />}
        </GeoJSONSource>
      )}
      {targets.map(t => (
        <ViewAnnotation key={t.kind} id={t.kind} lngLat={lngLat(t.point)} anchor="bottom">
          <View style={st.pinWrap}>
            <View style={[st.pin, t.kind === 'customer' && { backgroundColor: brand.money }, t.kind === 'hotspot' && { backgroundColor: brand.danger }]}>
              <Text style={st.pinIcon}>{t.kind === 'store' ? '🏪' : t.kind === 'hotspot' ? '🔥' : '🏠'}</Text>
            </View>
            <View style={[st.pinTail, t.kind === 'customer' && { borderTopColor: brand.money }, t.kind === 'hotspot' && { borderTopColor: brand.danger }]} />
          </View>
        </ViewAnnotation>
      ))}
      {me && (
        <ViewAnnotation id="yo" lngLat={lngLat(me)} anchor="center">
          {moving && follow
            ? <View style={st.arrow}><Text style={st.arrowTxt}>▲</Text></View>  // la cámara ya gira con él: la flecha apunta para arriba
            : <View style={st.meHalo}><View style={st.me} /></View>}
        </ViewAnnotation>
      )}
    </Map>
  );
}

const st = StyleSheet.create({
  pinWrap: { alignItems: 'center' },
  pin: { width: 40, height: 40, borderRadius: 12, backgroundColor: '#000', alignItems: 'center', justifyContent: 'center', borderWidth: 3, borderColor: '#fff' },
  pinIcon: { fontSize: 18 },
  pinTail: { width: 0, height: 0, borderLeftWidth: 7, borderRightWidth: 7, borderTopWidth: 9, borderLeftColor: 'transparent', borderRightColor: 'transparent', borderTopColor: '#000', marginTop: -2 },
  meHalo: { width: 34, height: 34, borderRadius: 17, backgroundColor: 'rgba(39,110,241,.22)', alignItems: 'center', justifyContent: 'center' },
  me: { width: 18, height: 18, borderRadius: 9, backgroundColor: brand.go, borderWidth: 3, borderColor: '#fff' },
  arrow: { width: 36, height: 36, borderRadius: 18, backgroundColor: brand.go, borderWidth: 3, borderColor: '#fff', alignItems: 'center', justifyContent: 'center' },
  arrowTxt: { color: '#fff', fontSize: 16, marginTop: -2 },
});
