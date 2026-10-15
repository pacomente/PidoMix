import Ionicons from '@expo/vector-icons/Ionicons';
import { useEffect, useState } from 'react';
import { Animated, Easing, Pressable, Text, View } from 'react-native';

import { km, money } from '@/lib/format';
import { radius, themed } from '@/lib/theme';
import type { Offer } from '@/lib/types';
import { useColors } from '@/state/prefs';

/** Oferta de viaje estilo Uber: ganancia grande, recorrido, cuánto paga por km, cuenta regresiva y aceptar. */
export function OfferCard({ offer, onAccept, onReject, busy }: { offer: Offer; onAccept: () => void; onReject: () => void; busy: boolean }) {
  const c = useColors(), st = useSt(c);
  // se monta de nuevo con cada oferta (key={offer.id}), así arranca la cuenta desde cero
  const [left, setLeft] = useState(offer.expires_in);
  const [bar] = useState(() => new Animated.Value(offer.expires_in / Math.max(1, offer.seconds)));
  const [showPay, setShowPay] = useState(false);

  useEffect(() => {
    const anim = Animated.timing(bar, { toValue: 0, duration: offer.expires_in * 1000, easing: Easing.linear, useNativeDriver: false });
    anim.start();
    const t = setInterval(() => setLeft(l => Math.max(0, l - 1)), 1000);
    return () => { clearInterval(t); anim.stop(); };
  }, [bar, offer.expires_in]);

  const totalKm = (offer.to_store_km ?? 0) + (offer.trip_km ?? 0);
  const perKm = totalKm >= 0.3 ? offer.earnings / totalKm : null;
  const urgent = left <= 10;

  return (
    <View style={st.card}>
      <View style={st.timerTrack}><Animated.View style={[st.timerFill, urgent && { backgroundColor: c.danger }, { width: bar.interpolate({ inputRange: [0, 1], outputRange: ['0%', '100%'] }) }]} /></View>
      <View style={st.head}>
        <View style={[st.kindPill, offer.own_store && { backgroundColor: c.infoBg }]}>
          <Text style={st.kind}>{offer.own_store ? '🏪 Viaje de tu local' : '⚡ Viaje Trappi'}</Text>
        </View>
        <Text style={st.items}>{offer.items} {offer.items === 1 ? 'producto' : 'productos'}</Text>
      </View>
      <Pressable onPress={() => setShowPay(v => !v)} disabled={!offer.payout?.lines.length} accessibilityRole="button" accessibilityLabel="Ver de dónde sale la ganancia">
        <View style={st.moneyRow}>
          <Text style={st.money}>{money(offer.earnings)}</Text>
          {!!offer.multiplier_text && <View style={st.surge}><Ionicons name="flame" size={15} color="#fff" /><Text style={st.surgeText}>{offer.multiplier_text}</Text></View>}
          {!!offer.payout?.lines.length && <Ionicons name={showPay ? 'chevron-up' : 'information-circle-outline'} size={20} color={c.muted} />}
        </View>
        {showPay && !!offer.payout?.lines.length && (
          <View style={st.payout}>{offer.payout.lines.map((l, i) => <View key={i} style={st.payLine}><Text style={st.payLabel}>{l.label}</Text><Text style={st.payAmt}>{money(l.amount)}</Text></View>)}</View>
        )}
      </Pressable>

      <View style={st.metrics}>
        {totalKm > 0 && <View style={st.metric}><Text style={st.metricVal}>{km(totalKm)}</Text><Text style={st.metricLbl}>en total</Text></View>}
        {offer.to_store_km !== null && <View style={st.metric}><Text style={st.metricVal}>{km(offer.to_store_km)}</Text><Text style={st.metricLbl}>hasta el local</Text></View>}
        {perKm !== null && <View style={st.metric}><Text style={st.metricVal}>{money(perKm)}</Text><Text style={st.metricLbl}>por km</Text></View>}
      </View>

      {offer.paid_online !== undefined && (
        <View style={[st.payTag, offer.paid_online ? st.payOnline : st.payCash]}>
          <Text style={st.payTagText}>{offer.paid_online ? '💳 Pagado online · no cobrás nada' : offer.collect ? `💵 Cobrás ${money(offer.collect)} en efectivo` : '✓ Ya pagado'}</Text>
          {!!offer.pay_store && <Text style={st.payTagText}>Llevá {money(offer.pay_store)} para pagarle al local al retirar</Text>}
        </View>
      )}
      <View style={st.route}>
        <View style={st.rail}><View style={st.dotA} /><View style={st.railLine} /><View style={st.dotB} /></View>
        <View style={{ flex: 1, gap: 14 }}>
          <View><Text style={st.stopTitle}>{offer.store.name}</Text><Text style={st.stopSub} numberOfLines={1}>{offer.store.address || 'Retiro en el local'}</Text></View>
          <View><Text style={st.stopTitle}>Entrega{offer.trip_km !== null ? ` · ${km(offer.trip_km)} desde el local` : ''}</Text><Text style={st.stopSub} numberOfLines={1}>{offer.dropoff.address || 'Dirección del cliente'}</Text></View>
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
      <Text style={st.hint}>Si no aceptás, se le ofrece a otro repartidor.</Text>
    </View>
  );
}

const useSt = themed(c => ({
  card: { backgroundColor: c.card, borderRadius: radius.lg, padding: 18, paddingTop: 0, overflow: 'hidden', shadowColor: '#000', shadowOpacity: c.shadow + 0.1, shadowRadius: 20, shadowOffset: { width: 0, height: -4 }, elevation: 12 },
  timerTrack: { height: 6, marginHorizontal: -18, backgroundColor: c.line, marginBottom: 14 },
  timerFill: { height: 6, backgroundColor: c.go },
  head: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  kindPill: { backgroundColor: c.card2, paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill },
  kind: { color: c.ink, fontWeight: '800', fontSize: 13.5 },
  items: { color: c.muted, fontWeight: '700' },
  moneyRow: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  money: { fontSize: 46, fontWeight: '900', color: c.ink, letterSpacing: -1, marginTop: 4, fontVariant: ['tabular-nums'] },
  surge: { flexDirection: 'row', alignItems: 'center', gap: 3, backgroundColor: c.danger, paddingHorizontal: 9, paddingVertical: 4, borderRadius: radius.pill },
  surgeText: { color: '#fff', fontWeight: '900', fontSize: 15 },
  payout: { backgroundColor: c.card2, borderRadius: radius.sm, padding: 10, gap: 4, marginBottom: 4 },
  payLine: { flexDirection: 'row', justifyContent: 'space-between' },
  payLabel: { color: c.muted, fontWeight: '600' },
  payAmt: { color: c.ink, fontWeight: '800' },
  metrics: { flexDirection: 'row', gap: 8, marginTop: 6 },
  metric: { flex: 1, backgroundColor: c.card2, borderRadius: radius.sm, paddingVertical: 8, paddingHorizontal: 10 },
  metricVal: { color: c.ink, fontWeight: '900', fontSize: 16 },
  metricLbl: { color: c.muted, fontSize: 12, fontWeight: '600' },
  payTag: { alignSelf: 'flex-start', paddingHorizontal: 10, paddingVertical: 5, borderRadius: 8, marginTop: 10 },
  payOnline: { backgroundColor: c.infoBg },
  payCash: { backgroundColor: c.cashBg },
  payTagText: { fontWeight: '800', color: c.ink, fontSize: 13.5 },
  route: { flexDirection: 'row', gap: 12, marginTop: 14, marginBottom: 16 },
  rail: { alignItems: 'center', paddingTop: 5, width: 12 },
  dotA: { width: 10, height: 10, borderRadius: 5, backgroundColor: c.ink },
  railLine: { width: 2, flex: 1, backgroundColor: c.line, marginVertical: 3 },
  dotB: { width: 10, height: 10, backgroundColor: c.money },
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
