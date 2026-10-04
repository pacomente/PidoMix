import Ionicons from '@expo/vector-icons/Ionicons';
import { Redirect, router } from 'expo-router';
import { useEffect, useState } from 'react';
import { ActivityIndicator, Animated, Easing, Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { DriverMap, type MapTarget } from '@/components/driver-map';
import { OfferCard } from '@/components/offer-card';
import { TripSheet } from '@/components/trip-sheet';
import { money } from '@/lib/format';
import { colors, radius } from '@/lib/theme';
import { useSession } from '@/state/session';

function pt(p: { lat?: number; lng?: number }) {
  return p.lat !== undefined && p.lng !== undefined ? { lat: p.lat, lng: p.lng } : null;
}

function Searching() {
  const [x] = useState(() => new Animated.Value(0));
  useEffect(() => {
    const loop = Animated.loop(Animated.timing(x, { toValue: 1, duration: 1400, easing: Easing.inOut(Easing.ease), useNativeDriver: true }));
    loop.start();
    return () => loop.stop();
  }, [x]);
  return (
    <View style={st.searchTrack}>
      <Animated.View style={[st.searchBar, { transform: [{ translateX: x.interpolate({ inputRange: [0, 1], outputRange: [-120, 360] }) }] }]} />
    </View>
  );
}

export default function Home() {
  const insets = useSafeAreaInsets();
  const { ready, loggedIn, state, position, error, busy, goOnline, goOffline, act, deliver, lastDelivery, clearDelivery } = useSession();
  const [sheetH, setSheetH] = useState(220);

  useEffect(() => {
    if (!lastDelivery) return;
    const t = setTimeout(clearDelivery, 4000);
    return () => clearTimeout(t);
  }, [lastDelivery, clearDelivery]);

  if (!ready) return <View style={st.center}><ActivityIndicator color="#fff" size="large" /></View>;
  if (!loggedIn) return <Redirect href="/login" />;
  if (!state) return <View style={st.center}><ActivityIndicator color="#fff" size="large" />{error && <Text style={st.loadErr}>{error}</Text>}</View>;

  const { courier, trip, offer, earnings } = state;
  const targets: MapTarget[] = [];
  if (trip) {
    const s = pt(trip.store), c = pt(trip.customer);
    if (trip.stage === 'pickup') { if (s) targets.push({ kind: 'store', point: s, label: trip.store.name }); if (c) targets.push({ kind: 'customer', point: c, label: 'Cliente' }); }
    else if (c) targets.push({ kind: 'customer', point: c, label: trip.customer.name });
  } else if (offer) {
    const s = pt(offer.store), c = pt(offer.dropoff);
    if (s) targets.push({ kind: 'store', point: s, label: offer.store.name });
    if (c) targets.push({ kind: 'customer', point: c, label: 'Entrega' });
  }

  return (
    <View style={{ flex: 1, backgroundColor: '#E9E9E9' }}>
      <DriverMap me={position} targets={targets} bottomInset={sheetH} />

      {/* barra superior: menu y ganancias del dia */}
      <View style={[st.top, { paddingTop: insets.top + 8 }]} pointerEvents="box-none">
        <Pressable style={st.round} onPress={() => router.push('/menu')} accessibilityLabel="Menú"><Ionicons name="menu" size={24} color={colors.ink} /></Pressable>
        <Pressable style={st.earnPill} onPress={() => router.push('/earnings')} accessibilityLabel="Ver ganancias">
          <Text style={st.earnValue}>{money(earnings.today)}</Text>
          <Text style={st.earnLabel}>hoy · {earnings.trips_today} {earnings.trips_today === 1 ? 'viaje' : 'viajes'}</Text>
        </Pressable>
        <View style={[st.round, { opacity: 0 }]} />
      </View>
      {!!error && <View style={[st.error, { top: insets.top + 70 }]}><Text style={st.errorText}>{error}</Text></View>}
      {!error && courier.cash?.blocked && !trip && (
        <View style={[st.cashBlocked, { top: insets.top + 70 }]}>
          <Text style={st.errorText}>BLOQUEADO PARA PEDIDOS EN EFECTIVO</Text>
          <Text style={st.cashBlockedSub}>Tenés {money(courier.cash.pending)} sin rendir (límite {money(courier.cash.limit)}).{courier.cash.online_enabled ? ' Seguís recibiendo pedidos pagados online.' : ''}</Text>
        </View>
      )}
      {lastDelivery && (
        <View style={[st.delivered, { top: insets.top + 70 }]}>
          <Text style={st.deliveredMoney}>+{money(lastDelivery.earnings)}</Text>
          <Text style={st.deliveredText}>¡Pedido #{lastDelivery.order_id} entregado!</Text>
          {!!lastDelivery.collected && <Text style={st.deliveredText}>Cobraste {money(lastDelivery.collected)} en efectivo</Text>}
        </View>
      )}

      {/* parte de abajo: segun el estado */}
      <View style={[st.bottom, { paddingBottom: insets.bottom + (trip ? 0 : 12) }]} onLayout={e => setSheetH(e.nativeEvent.layout.height)}>
        {trip ? (
          <TripSheet trip={trip} busy={busy} onPickup={() => act('pickup', trip.order_id)} onDeliver={pin => deliver(trip.order_id, pin)} onRelease={() => act('release', trip.order_id)} />
        ) : offer ? (
          <View style={{ paddingHorizontal: 12 }}><OfferCard key={offer.id} offer={offer} busy={busy} onAccept={() => act('accept', offer.id)} onReject={() => act('reject', offer.id)} /></View>
        ) : courier.online ? (
          <View style={st.bar}>
            <Searching />
            <View style={st.barRow}>
              <View style={{ flex: 1 }}>
                <Text style={st.barTitle}>Buscando viajes</Text>
                <Text style={st.barSub}>Dejá la app abierta: te suena cuando hay un pedido cerca.</Text>
              </View>
              <Pressable onPress={goOffline} disabled={busy} style={st.stop} accessibilityLabel="Desconectarse">
                {busy ? <ActivityIndicator color={colors.danger} /> : <Ionicons name="hand-left" size={22} color={colors.danger} />}
              </Pressable>
            </View>
          </View>
        ) : (
          <View style={{ alignItems: 'center' }}>
            <Pressable onPress={goOnline} disabled={busy} style={({ pressed }) => [st.go, pressed && { transform: [{ scale: 0.96 }] }]} accessibilityLabel="Conectarse">
              {busy ? <ActivityIndicator color="#fff" size="large" /> : <Text style={st.goText}>GO</Text>}
            </Pressable>
            <View style={[st.bar, { alignSelf: 'stretch' }]}>
              <View style={st.barRow}>
                <View style={st.offDot} />
                <View style={{ flex: 1 }}>
                  <Text style={st.barTitle}>Estás desconectado</Text>
                  <Text style={st.barSub}>Tocá GO para empezar a recibir viajes.</Text>
                </View>
              </View>
            </View>
          </View>
        )}
      </View>
    </View>
  );
}

const st = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: '#000', gap: 16, padding: 24 },
  loadErr: { color: '#fff', textAlign: 'center' },
  top: { position: 'absolute', left: 0, right: 0, top: 0, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 14 },
  round: { width: 48, height: 48, borderRadius: 24, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center', shadowColor: '#000', shadowOpacity: 0.2, shadowRadius: 8, elevation: 6 },
  earnPill: { backgroundColor: '#000', paddingHorizontal: 20, paddingVertical: 8, borderRadius: radius.pill, alignItems: 'center', shadowColor: '#000', shadowOpacity: 0.3, shadowRadius: 8, elevation: 6 },
  earnValue: { color: '#fff', fontSize: 22, fontWeight: '900', fontVariant: ['tabular-nums'] },
  earnLabel: { color: '#BBB', fontSize: 11.5, fontWeight: '700' },
  cashBlocked: { position: 'absolute', left: 16, right: 16, backgroundColor: '#3A0D08', padding: 12, borderRadius: radius.sm, gap: 2 },
  cashBlockedSub: { color: '#FFD3CC', textAlign: 'center', fontSize: 13 },
  error: { position: 'absolute', left: 16, right: 16, backgroundColor: colors.danger, padding: 12, borderRadius: radius.sm },
  errorText: { color: '#fff', fontWeight: '700', textAlign: 'center' },
  delivered: { position: 'absolute', left: 40, right: 40, backgroundColor: colors.money, padding: 14, borderRadius: radius.md, alignItems: 'center' },
  deliveredMoney: { color: '#fff', fontSize: 30, fontWeight: '900' },
  deliveredText: { color: '#fff', fontWeight: '700' },
  bottom: { position: 'absolute', left: 0, right: 0, bottom: 0 },
  go: { width: 96, height: 96, borderRadius: 48, backgroundColor: colors.go, alignItems: 'center', justifyContent: 'center', borderWidth: 5, borderColor: '#fff', marginBottom: 14, shadowColor: '#000', shadowOpacity: 0.35, shadowRadius: 12, elevation: 10 },
  goText: { color: '#fff', fontSize: 30, fontWeight: '900', letterSpacing: 1 },
  bar: { marginHorizontal: 12, backgroundColor: '#fff', borderRadius: radius.md, padding: 16, overflow: 'hidden', shadowColor: '#000', shadowOpacity: 0.2, shadowRadius: 12, elevation: 8 },
  barRow: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  barTitle: { fontSize: 20, fontWeight: '900', color: colors.ink },
  barSub: { color: colors.muted, marginTop: 2 },
  offDot: { width: 12, height: 12, borderRadius: 6, backgroundColor: '#BBB' },
  stop: { width: 50, height: 50, borderRadius: 25, backgroundColor: '#FFF0EE', alignItems: 'center', justifyContent: 'center' },
  searchTrack: { height: 4, marginHorizontal: -16, marginTop: -16, marginBottom: 14, backgroundColor: '#EEF3FE', overflow: 'hidden' },
  searchBar: { width: 120, height: 4, backgroundColor: colors.go },
});
