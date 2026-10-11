import { Camera, GeoJSONSource, Layer, Map, ViewAnnotation, type CameraRef } from '@maplibre/maplibre-react-native';
import { useEffect, useMemo, useRef } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { colors } from '@/lib/theme';
import { useConfig } from '@/state/config';


type P = { lat: number; lng: number };
export type MapTarget = { kind: 'store' | 'customer' | 'hotspot'; point: P; label: string };
export type MapHotspot = { lat: number; lng: number; radius_m: number; orders: number };

const lngLat = (p: P): [number, number] => [p.lng, p.lat];

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
 * (o una línea recta si no hay ruta) y las zonas con pedidos esperando en rojo. */
export function DriverMap({ me, targets, bottomInset, path, hotspots = [] }: {
  me: P | null; targets: MapTarget[]; bottomInset: number; path?: [number, number][] | null; hotspots?: MapHotspot[];
}) {
  const { map_style: mapStyle } = useConfig();  // proveedor elegido en el panel (por defecto OpenFreeMap)
  const camera = useRef<CameraRef>(null);
  const points = useMemo(() => [...(me ? [me] : []), ...targets.map(t => t.point)], [me, targets]);
  const key = points.map(p => `${p.lat.toFixed(4)},${p.lng.toFixed(4)}`).join('|');

  useEffect(() => {
    if (!camera.current || !points.length) return;
    if (points.length === 1) {
      camera.current.easeTo({ center: lngLat(points[0]), zoom: 15, duration: 600 });
      return;
    }
    const lngs = points.map(p => p.lng), lats = points.map(p => p.lat);
    camera.current.fitBounds([Math.min(...lngs), Math.min(...lats), Math.max(...lngs), Math.max(...lats)], {
      padding: { top: 120, left: 60, right: 60, bottom: bottomInset + 40 }, duration: 700,
    });
  }, [key, bottomInset]); // eslint-disable-line react-hooks/exhaustive-deps

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
    <Map style={StyleSheet.absoluteFill} mapStyle={mapStyle} logo={false} compass={false} attributionPosition={{ top: 8, right: 8 }}>
      <Camera ref={camera} initialViewState={{ center: me ? lngLat(me) : [-62.2663, -38.7183], zoom: 14 }} />
      {hotspots.length > 0 && (
        <GeoJSONSource id="demanda" data={zones}>
          <Layer id="demanda-relleno" type="fill" paint={{ 'fill-color': colors.danger, 'fill-opacity': 0.22 }} />
          <Layer id="demanda-borde" type="line" paint={{ 'line-color': colors.danger, 'line-width': 2, 'line-opacity': 0.7 }} />
        </GeoJSONSource>
      )}
      {route && (
        <GeoJSONSource id="ruta" data={route}>
          <Layer id="ruta-borde" type="line" paint={{ 'line-color': '#FFFFFF', 'line-width': real ? 10 : 8 }} layout={{ 'line-cap': 'round', 'line-join': 'round' }} />
          {real
            ? <Layer id="ruta-linea" type="line" paint={{ 'line-color': colors.go, 'line-width': 6 }} layout={{ 'line-cap': 'round', 'line-join': 'round' }} />
            : <Layer id="ruta-linea" type="line" paint={{ 'line-color': colors.ink, 'line-width': 4, 'line-dasharray': [1.5, 1.5] }} layout={{ 'line-cap': 'round' }} />}
        </GeoJSONSource>
      )}
      {targets.map(t => (
        <ViewAnnotation key={t.kind} id={t.kind} lngLat={lngLat(t.point)} anchor="bottom">
          <View style={st.pinWrap}>
            <View style={[st.pin, t.kind === 'customer' && { backgroundColor: colors.money }, t.kind === 'hotspot' && { backgroundColor: colors.danger }]}>
              <Text style={st.pinIcon}>{t.kind === 'store' ? '🏪' : t.kind === 'hotspot' ? '🔥' : '🏠'}</Text>
            </View>
            <View style={[st.pinTail, t.kind === 'customer' && { borderTopColor: colors.money }, t.kind === 'hotspot' && { borderTopColor: colors.danger }]} />
          </View>
        </ViewAnnotation>
      ))}
      {me && (
        <ViewAnnotation id="yo" lngLat={lngLat(me)} anchor="center">
          <View style={st.meHalo}><View style={st.me} /></View>
        </ViewAnnotation>
      )}
    </Map>
  );
}

const st = StyleSheet.create({
  pinWrap: { alignItems: 'center' },
  pin: { width: 40, height: 40, borderRadius: 12, backgroundColor: colors.ink, alignItems: 'center', justifyContent: 'center', borderWidth: 3, borderColor: '#fff' },
  pinIcon: { fontSize: 18 },
  pinTail: { width: 0, height: 0, borderLeftWidth: 7, borderRightWidth: 7, borderTopWidth: 9, borderLeftColor: 'transparent', borderRightColor: 'transparent', borderTopColor: colors.ink, marginTop: -2 },
  meHalo: { width: 34, height: 34, borderRadius: 17, backgroundColor: 'rgba(39,110,241,.22)', alignItems: 'center', justifyContent: 'center' },
  me: { width: 18, height: 18, borderRadius: 9, backgroundColor: colors.go, borderWidth: 3, borderColor: '#fff' },
});
