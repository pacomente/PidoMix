import { StyleSheet, Text, View } from 'react-native';

import { useColors } from '@/state/prefs';

import { PIN } from '@/lib/pins';

import type { MapHotspot, MapTarget, Me, MeStyle } from './driver-map';

/** En la web (solo para probar la interfaz) no hay mapa nativo: se muestra un fondo con los puntos. */
export function DriverMap({ me, meStyle = null, targets, hotspots = [], path, follow }: {
  me: Me | null; meStyle?: MeStyle; targets: MapTarget[]; bottomInset: number; path?: [number, number][] | null; hotspots?: MapHotspot[];
  follow?: boolean; recenter?: number; onUserMove?: () => void;
}) {
  const c = useColors();
  return (
    <View style={[StyleSheet.absoluteFill, st.bg, { backgroundColor: c.dark ? '#1E2126' : '#E5E3DF' }]}>
      {[18, 36, 54, 72].map(t => <View key={`h${t}`} style={[st.road, { top: `${t}%`, backgroundColor: c.dark ? '#2C3038' : '#F7F6F3' }]} />)}
      {[22, 48, 74].map(l => <View key={`v${l}`} style={[st.roadV, { left: `${l}%`, backgroundColor: c.dark ? '#2C3038' : '#F7F6F3' }]} />)}
      {hotspots.map((h, i) => <View key={i} style={[st.zone, { left: `${18 + i * 22}%`, top: `${22 + (i % 2) * 14}%` }]} />)}
      {!!meStyle?.avatar && <View style={[st.me, { backgroundColor: meStyle.color || c.go }]}><Text style={{ fontSize: 24 }}>{meStyle.avatar}</Text></View>}
      <Text style={[st.txt, { color: c.muted }]}>{me ? `📍 ${me.lat.toFixed(4)}, ${me.lng.toFixed(4)}${follow ? ' · siguiéndote' : ''}` : 'Mapa (solo en el celular)'}{targets.map(t => `\n${PIN[t.kind].icon} ${t.label}`).join('')}{path ? `\nRuta por calle: ${path.length} puntos` : ''}</Text>
    </View>
  );
}

const st = StyleSheet.create({
  bg: { alignItems: 'center', justifyContent: 'center' },
  road: { position: 'absolute', left: 0, right: 0, height: 10 },
  roadV: { position: 'absolute', top: 0, bottom: 0, width: 10 },
  txt: { textAlign: 'center', fontWeight: '600' },
  me: { width: 48, height: 48, borderRadius: 24, borderWidth: 3, borderColor: '#fff', alignItems: 'center', justifyContent: 'center', marginBottom: 8 },
  zone: { position: 'absolute', width: 130, height: 130, borderRadius: 65, backgroundColor: 'rgba(255,106,43,.35)', borderWidth: 2, borderColor: 'rgba(255,106,43,.45)' },
});
