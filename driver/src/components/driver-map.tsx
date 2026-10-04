import { Camera, GeoJSONSource, Layer, Map, ViewAnnotation, type CameraRef } from '@maplibre/maplibre-react-native';
import { useEffect, useMemo, useRef } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { colors } from '@/lib/theme';

// Mapas de OpenStreetMap servidos por OpenFreeMap: gratis y sin clave de API
export const MAP_STYLE = 'https://tiles.openfreemap.org/styles/liberty';

type P = { lat: number; lng: number };
export type MapTarget = { kind: 'store' | 'customer'; point: P; label: string };

const lngLat = (p: P): [number, number] => [p.lng, p.lat];

/** Mapa a pantalla completa: el repartidor, el local y el cliente, con una línea al próximo destino. */
export function DriverMap({ me, targets, bottomInset }: { me: P | null; targets: MapTarget[]; bottomInset: number }) {
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
  const route = me && next ? { type: 'Feature' as const, properties: {}, geometry: { type: 'LineString' as const, coordinates: [lngLat(me), lngLat(next.point)] } } : null;

  return (
    <Map style={StyleSheet.absoluteFill} mapStyle={MAP_STYLE} logo={false} compass={false} attributionPosition={{ top: 8, right: 8 }}>
      <Camera ref={camera} initialViewState={{ center: me ? lngLat(me) : [-62.2663, -38.7183], zoom: 14 }} />
      {route && (
        <GeoJSONSource id="ruta" data={route}>
          <Layer id="ruta-borde" type="line" paint={{ 'line-color': '#FFFFFF', 'line-width': 8 }} layout={{ 'line-cap': 'round' }} />
          <Layer id="ruta-linea" type="line" paint={{ 'line-color': colors.ink, 'line-width': 4, 'line-dasharray': [1.5, 1.5] }} layout={{ 'line-cap': 'round' }} />
        </GeoJSONSource>
      )}
      {targets.map(t => (
        <ViewAnnotation key={t.kind} id={t.kind} lngLat={lngLat(t.point)} anchor="bottom">
          <View style={st.pinWrap}>
            <View style={[st.pin, t.kind === 'customer' && { backgroundColor: colors.money }]}><Text style={st.pinIcon}>{t.kind === 'store' ? '🏪' : '🏠'}</Text></View>
            <View style={[st.pinTail, t.kind === 'customer' && { borderTopColor: colors.money }]} />
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
