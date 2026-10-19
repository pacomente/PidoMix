import Ionicons from '@expo/vector-icons/Ionicons';
import { useEffect, useState } from 'react';
import { Animated, Easing, Pressable, Text, View } from 'react-native';

import { km, money } from '@/lib/format';
import { radius, themed } from '@/lib/theme';
import type { RideOffer } from '@/lib/types';
import { useColors } from '@/state/prefs';

/** Oferta de un viaje de la empresa: precio, a cuánto está el pasajero, el recorrido y la cuenta regresiva. */
export function RideOfferCard({ offer, onAccept, onReject, busy }: { offer: RideOffer; onAccept: () => void; onReject: () => void; busy: boolean }) {
  const c = useColors(), st = useSt(c);
  const [left, setLeft] = useState(offer.expires_in);
  const [bar] = useState(() => new Animated.Value(offer.expires_in / Math.max(1, offer.seconds)));

  useEffect(() => {
    const anim = Animated.timing(bar, { toValue: 0, duration: offer.expires_in * 1000, easing: Easing.linear, useNativeDriver: false });
    anim.start();
    const t = setInterval(() => setLeft(l => Math.max(0, l - 1)), 1000);
    return () => { clearInterval(t); anim.stop(); };
  }, [bar, offer.expires_in]);

  const urgent = left <= 8;
  const total = (offer.to_pickup_km ?? 0) + offer.trip_km;
  return (
    <View style={st.card}>
      <View style={st.timerTrack}><Animated.View style={[st.timerFill, urgent && { backgroundColor: c.danger }, { width: bar.interpolate({ inputRange: [0, 1], outputRange: ['0%', '100%'] }) }]} /></View>
      <View style={st.head}>
        <View style={st.kindPill}><Ionicons name={offer.vehicle === 'moto' ? 'bicycle' : 'car'} size={15} color={c.ink} /><Text style={st.kind}>Viaje · {offer.company}</Text></View>
        <Text style={st.muted}>1 pasajero</Text>
      </View>
      <Text style={st.money}>{money(offer.price)}</Text>
      <View style={st.metrics}>
        {offer.to_pickup_km !== null && <View style={st.metric}><Text style={st.metricVal}>{km(offer.to_pickup_km)}</Text><Text style={st.metricLbl}>hasta buscarlo</Text></View>}
        <View style={st.metric}><Text style={st.metricVal}>{km(offer.trip_km)}</Text><Text style={st.metricLbl}>de viaje</Text></View>
        {!!offer.trip_minutes && <View style={st.metric}><Text style={st.metricVal}>~{Math.round(offer.trip_minutes)} min</Text><Text style={st.metricLbl}>de viaje</Text></View>}
      </View>
      <View style={st.cash}><Ionicons name="cash-outline" size={16} color={c.cashText} /><Text style={st.cashText}>Cobrás {money(offer.price)} en efectivo{offer.night ? ' · tarifa nocturna' : ''}</Text></View>
      <View style={st.route}>
        <View style={st.rail}><View style={st.dotA} /><View style={st.railLine} /><View style={st.dotB} /></View>
        <View style={{ flex: 1, gap: 14 }}>
          <View><Text style={st.stopTitle} numberOfLines={1}>{offer.pickup.address || 'Ubicación del pasajero'}</Text><Text style={st.stopSub} numberOfLines={1}>{offer.pickup.note || 'Buscar al pasajero'}</Text></View>
          <View><Text style={st.stopTitle} numberOfLines={1}>{offer.dropoff.address || 'Destino'}</Text><Text style={st.stopSub}>Destino</Text></View>
        </View>
      </View>
      <View style={st.actions}>
        <Pressable onPress={onReject} disabled={busy} style={({ pressed }) => [st.reject, pressed && { opacity: 0.7 }]} accessibilityRole="button" accessibilityLabel="Rechazar el viaje">
          <Ionicons name="close" size={26} color={c.ink} />
        </Pressable>
        <Pressable onPress={onAccept} disabled={busy} style={({ pressed }) => [st.accept, busy && { opacity: 0.6 }, pressed && { transform: [{ scale: 0.98 }] }]} accessibilityRole="button" accessibilityLabel={`Aceptar el viaje, quedan ${left} segundos`}>
          <Text style={st.acceptText}>{busy ? 'Aceptando…' : 'Aceptar'}</Text>
          {!busy && <View style={[st.secs, urgent && { backgroundColor: c.danger }]}><Text style={st.secsText}>{left}s</Text></View>}
        </Pressable>
      </View>
      <Text style={st.hint}>{total ? `${km(total)} en total. ` : ''}Si no aceptás, se le ofrece a otro conductor de tu empresa.</Text>
    </View>
  );
}

const useSt = themed(c => ({
  card: { backgroundColor: c.card, borderRadius: radius.lg, padding: 18, paddingTop: 0, overflow: 'hidden', shadowColor: '#000', shadowOpacity: c.shadow + 0.1, shadowRadius: 20, shadowOffset: { width: 0, height: -4 }, elevation: 12 },
  timerTrack: { height: 6, marginHorizontal: -18, backgroundColor: c.line, marginBottom: 14 },
  timerFill: { height: 6, backgroundColor: c.go },
  head: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  kindPill: { flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: c.card2, paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill },
  kind: { color: c.ink, fontWeight: '800', fontSize: 13.5 },
  muted: { color: c.muted, fontWeight: '700' },
  money: { fontSize: 46, fontWeight: '900', color: c.ink, letterSpacing: -1, marginTop: 4, fontVariant: ['tabular-nums'] },
  metrics: { flexDirection: 'row', gap: 8, marginTop: 6 },
  metric: { flex: 1, backgroundColor: c.card2, borderRadius: radius.sm, paddingVertical: 8, paddingHorizontal: 10 },
  metricVal: { color: c.ink, fontWeight: '900', fontSize: 16 },
  metricLbl: { color: c.muted, fontSize: 12, fontWeight: '600' },
  cash: { flexDirection: 'row', alignItems: 'center', gap: 6, alignSelf: 'flex-start', backgroundColor: c.cashBg, paddingHorizontal: 10, paddingVertical: 5, borderRadius: 8, marginTop: 10 },
  cashText: { fontWeight: '800', color: c.cashText, fontSize: 13.5 },
  route: { flexDirection: 'row', gap: 12, marginTop: 14, marginBottom: 16 },
  rail: { alignItems: 'center', paddingTop: 5, width: 12 },
  dotA: { width: 10, height: 10, borderRadius: 5, backgroundColor: c.ink },
  railLine: { width: 2, flex: 1, backgroundColor: c.line, marginVertical: 3 },
  dotB: { width: 10, height: 10, backgroundColor: c.violet },
  stopTitle: { fontWeight: '800', fontSize: 16, color: c.ink },
  stopSub: { color: c.muted, fontSize: 14, marginTop: 1 },
  actions: { flexDirection: 'row', gap: 10 },
  reject: { width: 64, height: 64, borderRadius: 32, backgroundColor: c.card2, alignItems: 'center', justifyContent: 'center' },
  accept: { flex: 1, height: 64, borderRadius: 32, backgroundColor: c.go, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 10 },
  acceptText: { color: '#fff', fontSize: 20, fontWeight: '900' },
  secs: { backgroundColor: 'rgba(255,255,255,.22)', borderRadius: radius.pill, paddingHorizontal: 9, paddingVertical: 3 },
  secsText: { color: '#fff', fontWeight: '900', fontVariant: ['tabular-nums'] },
  hint: { color: c.muted, fontSize: 12.5, textAlign: 'center', marginTop: 10 },
}));
