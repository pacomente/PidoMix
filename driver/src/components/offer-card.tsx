import Ionicons from '@expo/vector-icons/Ionicons';
import { useEffect, useState } from 'react';
import { Animated, Easing, StyleSheet, Text, View } from 'react-native';

import { Button } from '@/components/ui';
import { km, money } from '@/lib/format';
import { colors, radius } from '@/lib/theme';
import type { Offer } from '@/lib/types';

/** Oferta de viaje estilo Uber: ganancia grande, recorrido, cuenta regresiva y aceptar. */
export function OfferCard({ offer, onAccept, onReject, busy }: { offer: Offer; onAccept: () => void; onReject: () => void; busy: boolean }) {
  // se monta de nuevo con cada oferta (key={offer.id}), así arranca la cuenta desde cero
  const [left, setLeft] = useState(offer.expires_in);
  const [bar] = useState(() => new Animated.Value(offer.expires_in / Math.max(1, offer.seconds)));

  useEffect(() => {
    const anim = Animated.timing(bar, { toValue: 0, duration: offer.expires_in * 1000, easing: Easing.linear, useNativeDriver: false });
    anim.start();
    const t = setInterval(() => setLeft(l => Math.max(0, l - 1)), 1000);
    return () => { clearInterval(t); anim.stop(); };
  }, [bar, offer.expires_in]);

  return (
    <View style={st.card}>
      <View style={st.timerTrack}><Animated.View style={[st.timerFill, { width: bar.interpolate({ inputRange: [0, 1], outputRange: ['0%', '100%'] }) }]} /></View>
      <View style={st.head}>
        <Text style={st.kind}>{offer.own_store ? 'Viaje de tu local' : 'Viaje Trappi'} · {offer.items} {offer.items === 1 ? 'producto' : 'productos'}</Text>
        <Text style={st.left}>{left}s</Text>
      </View>
      <Text style={st.money}>{money(offer.earnings)}</Text>
      <Text style={st.sub}>{[offer.to_store_km !== null && `${km(offer.to_store_km)} hasta el local`, offer.trip_km !== null && `${km(offer.trip_km)} de viaje`].filter(Boolean).join(' · ') || 'Ganancia del viaje'}</Text>
      {!!offer.payout?.lines.length && <Text style={st.payout}>{offer.payout.lines.map(l => `${l.label} ${money(l.amount)}`).join(' · ')}</Text>}
      {offer.paid_online !== undefined && (
        <View style={[st.payTag, offer.paid_online ? st.payOnline : st.payCash]}>
          <Text style={st.payTagText}>{offer.paid_online ? '💳 Pagado online · no cobrás nada' : offer.collect ? `💵 Cobrás ${money(offer.collect)} en efectivo` : '✓ Ya pagado'}</Text>
        </View>
      )}
      <View style={st.route}>
        <View style={st.rail}><View style={st.dotA} /><View style={st.railLine} /><View style={st.dotB} /></View>
        <View style={{ flex: 1, gap: 14 }}>
          <View><Text style={st.stopTitle}>{offer.store.name}</Text><Text style={st.stopSub} numberOfLines={1}>{offer.store.address || 'Retiro en el local'}</Text></View>
          <View><Text style={st.stopTitle}>Entrega</Text><Text style={st.stopSub} numberOfLines={1}>{offer.dropoff.address || 'Dirección del cliente'}</Text></View>
        </View>
      </View>
      <View style={st.actions}>
        <Button title="✕" variant="light" onPress={onReject} disabled={busy} style={st.reject} />
        <Button title="Aceptar" variant="go" big onPress={onAccept} loading={busy} style={{ flex: 1 }} />
      </View>
      <View style={st.hint}><Ionicons name="information-circle-outline" size={14} color={colors.muted} /><Text style={st.hintText}>Si no aceptás, se le ofrece a otro repartidor.</Text></View>
    </View>
  );
}

const st = StyleSheet.create({
  payout: { color: colors.muted, fontSize: 12.5, marginTop: 2 },
  payTag: { alignSelf: 'flex-start', paddingHorizontal: 10, paddingVertical: 5, borderRadius: 8, marginTop: 8 },
  payOnline: { backgroundColor: '#E8F1FF' },
  payCash: { backgroundColor: '#FFF6DD' },
  payTagText: { fontWeight: '800', color: colors.ink, fontSize: 13.5 },
  card: { backgroundColor: '#fff', borderRadius: radius.lg, padding: 18, paddingTop: 0, overflow: 'hidden', shadowColor: '#000', shadowOpacity: 0.3, shadowRadius: 20, shadowOffset: { width: 0, height: -4 }, elevation: 12 },
  timerTrack: { height: 6, marginHorizontal: -18, backgroundColor: '#EEE', marginBottom: 14 },
  timerFill: { height: 6, backgroundColor: colors.go },
  head: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  kind: { color: colors.muted, fontWeight: '700', fontSize: 14 },
  left: { fontWeight: '800', fontSize: 16, color: colors.ink, fontVariant: ['tabular-nums'] },
  money: { fontSize: 46, fontWeight: '900', color: colors.ink, letterSpacing: -1, marginTop: 4 },
  sub: { color: colors.muted, fontSize: 15, fontWeight: '600' },
  route: { flexDirection: 'row', gap: 12, marginTop: 16, marginBottom: 18 },
  rail: { alignItems: 'center', paddingTop: 5, width: 12 },
  dotA: { width: 10, height: 10, borderRadius: 5, backgroundColor: colors.ink },
  railLine: { width: 2, flex: 1, backgroundColor: '#CCC', marginVertical: 3 },
  dotB: { width: 10, height: 10, backgroundColor: colors.money },
  stopTitle: { fontWeight: '800', fontSize: 16, color: colors.ink },
  stopSub: { color: colors.muted, fontSize: 14, marginTop: 1 },
  actions: { flexDirection: 'row', gap: 10 },
  reject: { width: 60, minHeight: 60 },
  hint: { flexDirection: 'row', gap: 4, alignItems: 'center', justifyContent: 'center', marginTop: 10 },
  hintText: { color: colors.muted, fontSize: 12.5 },
});
