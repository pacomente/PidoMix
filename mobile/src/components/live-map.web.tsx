import { StyleSheet, Text, View } from 'react-native';

import type { Tracking } from '@/lib/types';

/** En la web de prueba no hay mapa nativo: se muestra un resumen (la web de Trappi tiene su propio mapa). */
export function LiveMap({ tracking }: { tracking: Tracking; mapStyle: string }) {
  const c = tracking.courier;
  return (
    <View style={st.wrap}>
      <Text style={st.txt}>{c ? `🛵 ${c.lat.toFixed(4)}, ${c.lng.toFixed(4)}` : 'Mapa (solo en el celular)'}{tracking.home ? '\n🏠 Tu casa' : ''}{tracking.store && tracking.stage !== 'to_you' ? '\n🏪 Local' : ''}</Text>
    </View>
  );
}

const st = StyleSheet.create({
  wrap: { height: 230, borderRadius: 16, backgroundColor: '#E5E3DF', alignItems: 'center', justifyContent: 'center' },
  txt: { color: '#777', fontWeight: '600', textAlign: 'center' },
});
