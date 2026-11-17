import { StyleSheet, Text, View } from 'react-native';

import type { Tracking } from '@/lib/types';

/** En la web de prueba no hay mapa nativo: un plano dibujado con las calles, tu casa y el repartidor. */
export function LiveMap({ tracking, full }: { tracking: Tracking; mapStyle: string; full?: boolean }) {
  return (
    <View style={full ? [StyleSheet.absoluteFill, st.bg] : [st.wrap, st.bg]} accessibilityLabel="Plano con el recorrido de tu repartidor">
      {[18, 44, 70].map(t => <View key={`h${t}`} style={[st.road, { top: `${t}%`, left: -20, right: -20, height: 16, transform: [{ rotate: t === 44 ? '-4deg' : '3deg' }] }]} />)}
      {[22, 72].map(l => <View key={`v${l}`} style={[st.road, { left: `${l}%`, top: -20, bottom: -20, width: 16, transform: [{ rotate: '2deg' }] }]} />)}
      <View style={[st.block, { left: '38%', top: '50%', width: 110, height: 90, backgroundColor: '#D9F3E3' }]} />
      <View style={[st.block, { left: '6%', top: '25%', width: 50, height: 80, backgroundColor: '#DCEBFF' }]} />
      <View style={st.route} />
      {!!tracking.home && <View style={[st.pin, { right: '20%', top: '16%' }]}><Text style={{ fontSize: 22 }}>🏠</Text></View>}
      {!!tracking.courier && (
        <View style={[st.me, { left: '24%', top: '52%', backgroundColor: tracking.color || '#6C2BD9' }]}>
          <Text style={{ fontSize: 26 }}>{tracking.avatar || '🛵'}</Text>
        </View>
      )}
      {!tracking.courier && <Text style={st.txt}>Todavía no tenemos la ubicación del repartidor</Text>}
    </View>
  );
}

const st = StyleSheet.create({
  wrap: { height: 230, borderRadius: 16, overflow: 'hidden' },
  bg: { backgroundColor: '#E8E5EE', overflow: 'hidden' },
  road: { position: 'absolute', backgroundColor: '#fff' },
  block: { position: 'absolute', borderRadius: 14 },
  route: { position: 'absolute', left: '30%', top: '24%', width: '48%', height: '34%', borderTopWidth: 5, borderRightWidth: 5, borderColor: '#6C2BD9', borderStyle: 'dashed', borderTopRightRadius: 30 },
  pin: { position: 'absolute', width: 46, height: 46, borderRadius: 16, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center', shadowColor: '#000', shadowOpacity: 0.18, shadowRadius: 8, elevation: 4 },
  me: { position: 'absolute', width: 58, height: 58, borderRadius: 29, borderWidth: 4, borderColor: '#fff', alignItems: 'center', justifyContent: 'center',
    shadowColor: '#FF6FB5', shadowOpacity: 0.6, shadowRadius: 18, elevation: 6 },
  txt: { position: 'absolute', alignSelf: 'center', top: '40%', color: '#777', fontWeight: '700' },
});
