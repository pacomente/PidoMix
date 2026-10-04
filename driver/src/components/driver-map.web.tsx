import { StyleSheet, Text, View } from 'react-native';

import type { MapTarget } from './driver-map';

/** En la web (solo para probar la interfaz) no hay mapa nativo: se muestra un fondo con los puntos. */
export function DriverMap({ me, targets }: { me: { lat: number; lng: number } | null; targets: MapTarget[]; bottomInset: number }) {
  return (
    <View style={[StyleSheet.absoluteFill, st.bg]}>
      <View style={st.grid} />
      <Text style={st.txt}>{me ? `📍 ${me.lat.toFixed(4)}, ${me.lng.toFixed(4)}` : 'Mapa (solo en el celular)'}{targets.map(t => `\n${t.kind === 'store' ? '🏪' : '🏠'} ${t.label}`).join('')}</Text>
    </View>
  );
}

const st = StyleSheet.create({
  bg: { backgroundColor: '#E5E3DF', alignItems: 'center', justifyContent: 'center' },
  grid: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, opacity: 0.5, borderColor: '#D5D3CF', borderWidth: 1 },
  txt: { color: '#777', textAlign: 'center', fontWeight: '600' },
});
