import { StyleSheet, Text, View } from 'react-native';

import type { MapHotspot, MapTarget } from './driver-map';

/** En la web (solo para probar la interfaz) no hay mapa nativo: se muestra un fondo con los puntos. */
export function DriverMap({ me, targets, hotspots = [], path }: {
  me: { lat: number; lng: number } | null; targets: MapTarget[]; bottomInset: number; path?: [number, number][] | null; hotspots?: MapHotspot[];
}) {
  return (
    <View style={[StyleSheet.absoluteFill, st.bg]}>
      <View style={st.grid} />
      {hotspots.map((h, i) => <View key={i} style={[st.zone, { left: `${18 + i * 22}%`, top: `${22 + (i % 2) * 14}%` }]} />)}
      <Text style={st.txt}>{me ? `📍 ${me.lat.toFixed(4)}, ${me.lng.toFixed(4)}` : 'Mapa (solo en el celular)'}{targets.map(t => `\n${t.kind === 'store' ? '🏪' : t.kind === 'hotspot' ? '🔥' : '🏠'} ${t.label}`).join('')}{path ? `\nRuta por calle: ${path.length} puntos` : ''}</Text>
    </View>
  );
}

const st = StyleSheet.create({
  bg: { backgroundColor: '#E5E3DF', alignItems: 'center', justifyContent: 'center' },
  grid: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, opacity: 0.5, borderColor: '#D5D3CF', borderWidth: 1 },
  txt: { color: '#777', textAlign: 'center', fontWeight: '600' },
  zone: { position: 'absolute', width: 130, height: 130, borderRadius: 65, backgroundColor: 'rgba(225,25,0,.22)', borderWidth: 2, borderColor: 'rgba(225,25,0,.7)' },
});
