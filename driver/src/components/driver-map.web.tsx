import { StyleSheet, Text, View } from 'react-native';

import { useColors } from '@/state/prefs';

import type { MapHotspot, MapTarget, Me } from './driver-map';

/** En la web (solo para probar la interfaz) no hay mapa nativo: se muestra un fondo con los puntos. */
export function DriverMap({ me, targets, hotspots = [], path, follow }: {
  me: Me | null; targets: MapTarget[]; bottomInset: number; path?: [number, number][] | null; hotspots?: MapHotspot[];
  follow?: boolean; recenter?: number; onUserMove?: () => void;
}) {
  const c = useColors();
  return (
    <View style={[StyleSheet.absoluteFill, st.bg, { backgroundColor: c.dark ? '#1E2126' : '#E5E3DF' }]}>
      {[18, 36, 54, 72].map(t => <View key={`h${t}`} style={[st.road, { top: `${t}%`, backgroundColor: c.dark ? '#2C3038' : '#F7F6F3' }]} />)}
      {[22, 48, 74].map(l => <View key={`v${l}`} style={[st.roadV, { left: `${l}%`, backgroundColor: c.dark ? '#2C3038' : '#F7F6F3' }]} />)}
      {hotspots.map((h, i) => <View key={i} style={[st.zone, { left: `${18 + i * 22}%`, top: `${22 + (i % 2) * 14}%` }]} />)}
      <Text style={[st.txt, { color: c.muted }]}>{me ? `📍 ${me.lat.toFixed(4)}, ${me.lng.toFixed(4)}${follow ? ' · siguiéndote' : ''}` : 'Mapa (solo en el celular)'}{targets.map(t => `\n${t.kind === 'store' ? '🏪' : t.kind === 'hotspot' ? '🔥' : '🏠'} ${t.label}`).join('')}{path ? `\nRuta por calle: ${path.length} puntos` : ''}</Text>
    </View>
  );
}

const st = StyleSheet.create({
  bg: { alignItems: 'center', justifyContent: 'center' },
  road: { position: 'absolute', left: 0, right: 0, height: 10 },
  roadV: { position: 'absolute', top: 0, bottom: 0, width: 10 },
  txt: { textAlign: 'center', fontWeight: '600' },
  zone: { position: 'absolute', width: 130, height: 130, borderRadius: 65, backgroundColor: 'rgba(225,25,0,.22)', borderWidth: 2, borderColor: 'rgba(225,25,0,.7)' },
});
