import { Camera, Map, ViewAnnotation, type CameraRef } from '@maplibre/maplibre-react-native';
import { useEffect, useRef } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { colors } from '@/lib/theme';
import type { Tracking } from '@/lib/types';

const EMOJI: Record<string, string> = { moto: '🛵', bici: '🚲', auto: '🚗', pie: '🚶' };
type P = { lat: number; lng: number };
const ll = (p: P): [number, number] => [p.lng, p.lat];

/** Mapa del seguimiento: el local, tu casa y el repartidor moviéndose (mapa gratis de OpenFreeMap). */
export function LiveMap({ tracking, mapStyle }: { tracking: Tracking; mapStyle: string }) {
  const camera = useRef<CameraRef>(null);
  const { courier, store, home, stage } = tracking;
  const pts = [courier, stage === 'to_you' ? null : store, home].filter(Boolean) as P[];
  const fitKey = `${stage}|${courier ? 1 : 0}`;  // se encuadra al cambiar de etapa, no en cada movimiento

  useEffect(() => {
    if (!camera.current || !pts.length) return;
    if (pts.length === 1) { camera.current.easeTo({ center: ll(pts[0]), zoom: 15, duration: 500 }); return; }
    const lngs = pts.map(p => p.lng), lats = pts.map(p => p.lat);
    camera.current.fitBounds([Math.min(...lngs), Math.min(...lats), Math.max(...lngs), Math.max(...lats)], { padding: { top: 40, bottom: 40, left: 40, right: 40 }, duration: 600 });
  }, [fitKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const start = pts[0] ?? { lat: -38.7183, lng: -62.2663 };
  return (
    <View style={st.wrap} accessible accessibilityLabel="Mapa con el recorrido de tu repartidor">
      <Map style={StyleSheet.absoluteFill} mapStyle={mapStyle} logo={false} compass={false} attributionPosition={{ bottom: 4, right: 4 }}>
        <Camera ref={camera} initialViewState={{ center: ll(start), zoom: 14 }} />
        {!!store && stage !== 'to_you' && <ViewAnnotation id="local" lngLat={ll(store)} anchor="center"><View style={st.pin}><Text style={st.emoji}>🏪</Text></View></ViewAnnotation>}
        {!!home && <ViewAnnotation id="casa" lngLat={ll(home)} anchor="center"><View style={st.pin}><Text style={st.emoji}>🏠</Text></View></ViewAnnotation>}
        {!!courier && <ViewAnnotation id="repartidor" lngLat={ll(courier)} anchor="center"><View style={[st.pin, st.me]}><Text style={st.emoji}>{EMOJI[tracking.vehicle] || '🛵'}</Text></View></ViewAnnotation>}
      </Map>
    </View>
  );
}

const st = StyleSheet.create({
  wrap: { height: 230, borderRadius: 16, overflow: 'hidden', backgroundColor: '#E5E3DF' },
  pin: { width: 36, height: 36, borderRadius: 18, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center', shadowColor: '#000', shadowOpacity: 0.25, shadowRadius: 6, elevation: 4 },
  me: { backgroundColor: colors.brand, borderWidth: 3, borderColor: '#fff' },
  emoji: { fontSize: 18 },
});
