import Ionicons from '@expo/vector-icons/Ionicons';
import { Redirect, router } from 'expo-router';
import { useEffect, useState } from 'react';
import { ActivityIndicator, Animated, Easing, Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { DriverMap, type MapTarget } from '@/components/driver-map';
import { OfferCard } from '@/components/offer-card';
import { TripSheet } from '@/components/trip-sheet';
import { money } from '@/lib/format';
import { fmtMeters, stepIcon, useGuidance } from '@/lib/guidance';
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
  const { ready, loggedIn, state, position, error, busy, goOnline, goOffline, act, deliver, pickup, fail, lastDelivery, clearDelivery } = useSession();
  const [sheetH, setSheetH] = useState(220);
  const [goingTo, setGoingTo] = useState<string | null>(null);  // la zona a la que eligió ir
  const trip = state?.trip ?? null, demand = state?.demand ?? null;
  const suggestion = !trip && !state?.offer ? demand?.suggestion ?? null : null;
  const zoneKey = suggestion ? `${suggestion.lat.toFixed(3)},${suggestion.lng.toFixed(3)}` : '';
  const going = !!suggestion && goingTo === zoneKey;  // si aparece un viaje o la zona se vacía, deja de ir solo
  const to = trip ? 'trip' : going ? 'suggestion' : null;
  const guide = useGuidance(to, trip ? `${trip.order_id}:${trip.stage}` : zoneKey, position);

  useEffect(() => {
    if (!lastDelivery) return;
    const t = setTimeout(clearDelivery, 4000);
    return () => clearTimeout(t);
  }, [lastDelivery, clearDelivery]);

  if (!ready) return <View style={st.center}><ActivityIndicator color="#fff" size="large" /></View>;
  if (!loggedIn) return <Redirect href="/login" />;
  if (!state) return <View style={st.center}><ActivityIndicator color="#fff" size="large" />{error && <Text style={st.loadErr}>{error}</Text>}</View>;

  const { courier, offer, earnings } = state;
  const hot = demand && demand.level !== 'normal';
  const targets: MapTarget[] = [];
  if (trip) {
    const s = pt(trip.store), c = pt(trip.customer);
    if (trip.stage === 'pickup') { if (s) targets.push({ kind: 'store', point: s, label: trip.store.name }); if (c) targets.push({ kind: 'customer', point: c, label: 'Cliente' }); }
    else if (c) targets.push({ kind: 'customer', point: c, label: trip.customer.name });
  } else if (offer) {
    const s = pt(offer.store), c = pt(offer.dropoff);
    if (s) targets.push({ kind: 'store', point: s, label: offer.store.name });
    if (c) targets.push({ kind: 'customer', point: c, label: 'Entrega' });
  } else if (going && suggestion) {
    targets.push({ kind: 'hotspot', point: { lat: suggestion.lat, lng: suggestion.lng }, label: 'Zona con pedidos' });
  }
  const bannerTop = insets.top + (guide.step ? 160 : 70);

  return (
    <View style={{ flex: 1, backgroundColor: '#E9E9E9' }}>
      <DriverMap me={position} targets={targets} bottomInset={sheetH} path={guide.directions?.geometry} hotspots={!trip && courier.online ? demand?.hotspots ?? [] : []} />

      {/* barra superior: menu y ganancias del dia */}
      <View style={[st.top, { paddingTop: insets.top + 8 }]} pointerEvents="box-none">
        <Pressable style={st.round} onPress={() => router.push('/menu')} accessibilityLabel="Menú"><Ionicons name="menu" size={24} color={colors.ink} /></Pressable>
        <Pressable style={st.earnPill} onPress={() => router.push('/earnings')} accessibilityLabel="Ver ganancias">
          <Text style={st.earnValue}>{money(earnings.today)}</Text>
          <Text style={st.earnLabel}>hoy · {earnings.trips_today} {earnings.trips_today === 1 ? 'viaje' : 'viajes'}</Text>
        </Pressable>
        {hot && demand?.multiplier_text && !trip  // en viaje no: lo que cobra ese viaje ya quedó fijo al aceptarlo
          ? <View style={st.surgePill}><Ionicons name="flame" size={16} color="#fff" /><Text style={st.surgePillText}>{demand.multiplier_text}</Text></View>
          : <View style={[st.round, { opacity: 0 }]} />}
      </View>
      {/* indicaciones: el próximo giro y cuánto falta */}
      {guide.step && (
        <View style={[st.nav, { top: insets.top + 64 }]}>
          <View style={st.navIcon}><Ionicons name={stepIcon(guide.step) as never} size={30} color="#fff" /></View>
          <View style={{ flex: 1 }}>
            {guide.toStep !== null && guide.step.type !== 'arrive' && <Text style={st.navDist}>En {fmtMeters(guide.toStep)}</Text>}
            <Text style={st.navText} numberOfLines={2}>{guide.step.text}</Text>
            {!!guide.directions && <Text style={st.navEta}>{Math.max(1, Math.round(guide.directions.minutes))} min · {guide.directions.km.toFixed(1).replace('.', ',')} km{guide.info?.kind === 'store' ? ' hasta el local' : guide.info?.kind === 'customer' ? ' hasta la entrega' : ' hasta la zona'}</Text>}
          </View>
        </View>
      )}
      {!!error && <View style={[st.error, { top: bannerTop }]}><Text style={st.errorText}>{error}</Text></View>}
      {!error && courier.cash?.blocked && !trip && (
        <View style={[st.cashBlocked, { top: bannerTop }]}>
          <Text style={st.errorText}>BLOQUEADO PARA PEDIDOS EN EFECTIVO</Text>
          <Text style={st.cashBlockedSub}>Tenés {money(courier.cash.pending)} sin rendir (límite {money(courier.cash.limit)}).{courier.cash.online_enabled ? ' Seguís recibiendo pedidos pagados online.' : ''}</Text>
        </View>
      )}
      {lastDelivery && (
        <View style={[st.delivered, { top: bannerTop }]}>
          <Text style={st.deliveredMoney}>+{money(lastDelivery.earnings)}</Text>
          <Text style={st.deliveredText}>¡Pedido #{lastDelivery.order_id} entregado!</Text>
          {!!lastDelivery.collected && <Text style={st.deliveredText}>Cobraste {money(lastDelivery.collected)} en efectivo</Text>}
        </View>
      )}

      {/* parte de abajo: segun el estado */}
      <View style={[st.bottom, { paddingBottom: insets.bottom + (trip ? 0 : 12) }]} onLayout={e => setSheetH(e.nativeEvent.layout.height)}>
        {trip ? (
          <TripSheet trip={trip} busy={busy} onPickup={code => pickup(trip.order_id, code)} onDeliver={pin => deliver(trip.order_id, pin)} onRelease={() => act('release', trip.order_id)} onFail={reason => fail(trip.order_id, reason)} />
        ) : offer ? (
          <View style={{ paddingHorizontal: 12 }}><OfferCard key={offer.id} offer={offer} busy={busy} onAccept={() => act('accept', offer.id)} onReject={() => act('reject', offer.id)} /></View>
        ) : courier.online ? (
          <View style={[st.bar, hot && st.barHot]}>
            <Searching />
            {hot && (
              <View style={st.hotRow}>
                <Ionicons name="flame" size={18} color={colors.danger} />
                <Text style={st.hotText}>{demand!.label}{demand!.multiplier_text ? ` · los viajes pagan ${demand!.multiplier_text}` : ''}</Text>
              </View>
            )}
            {suggestion && (
              <View style={st.suggest}>
                <View style={{ flex: 1 }}>
                  <Text style={st.suggestTitle}>{going ? 'Yendo a la zona con pedidos' : 'Te conviene moverte'}</Text>
                  <Text style={st.suggestText}>{suggestion.text}</Text>
                </View>
                <Pressable onPress={() => setGoingTo(going ? null : zoneKey)} style={[st.suggestBtn, going && st.suggestBtnOff]} accessibilityLabel={going ? 'Dejar de ir a la zona' : 'Llevame a la zona'}>
                  <Text style={[st.suggestBtnText, going && { color: colors.ink }]}>{going ? 'Cancelar' : 'Llevame'}</Text>
                </Pressable>
              </View>
            )}
            <View style={st.barRow}>
              <View style={{ flex: 1 }}>
                <Text style={st.barTitle}>Buscando viajes</Text>
                <Text style={st.barSub}>{demand && demand.waiting > 0 ? `${demand.waiting} ${demand.waiting === 1 ? 'pedido esperando' : 'pedidos esperando'} repartidor en tu ciudad.` : 'Dejá la app abierta: te suena cuando hay un pedido cerca.'}</Text>
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
  barHot: { borderWidth: 2, borderColor: colors.danger },
  hotRow: { flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: '#FFE9E5', marginHorizontal: -16, marginTop: -14, marginBottom: 12, paddingHorizontal: 16, paddingVertical: 8 },
  hotText: { color: colors.danger, fontWeight: '900', fontSize: 15 },
  suggest: { flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: '#F5F5F5', borderRadius: radius.sm, padding: 10, marginBottom: 12 },
  suggestTitle: { fontWeight: '900', color: colors.ink },
  suggestText: { color: colors.muted, fontSize: 13, marginTop: 1 },
  suggestBtn: { backgroundColor: colors.danger, paddingHorizontal: 14, paddingVertical: 9, borderRadius: radius.pill },
  suggestBtnOff: { backgroundColor: '#E2E2E2' },
  suggestBtnText: { color: '#fff', fontWeight: '900' },
  surgePill: { flexDirection: 'row', alignItems: 'center', gap: 4, height: 40, paddingHorizontal: 14, borderRadius: radius.pill, backgroundColor: colors.danger, shadowColor: '#000', shadowOpacity: 0.25, shadowRadius: 8, elevation: 6 },
  surgePillText: { color: '#fff', fontWeight: '900', fontSize: 17 },
  nav: { position: 'absolute', left: 12, right: 12, flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: '#0B3D2E', borderRadius: radius.md, padding: 12, shadowColor: '#000', shadowOpacity: 0.3, shadowRadius: 10, elevation: 8 },
  navIcon: { width: 52, height: 52, borderRadius: 12, backgroundColor: 'rgba(255,255,255,.12)', alignItems: 'center', justifyContent: 'center' },
  navDist: { color: '#9FE8C8', fontWeight: '900', fontSize: 15 },
  navText: { color: '#fff', fontWeight: '900', fontSize: 19 },
  navEta: { color: '#CDE9DD', fontSize: 12.5, marginTop: 2 },
  searchTrack: { height: 4, marginHorizontal: -16, marginTop: -16, marginBottom: 14, backgroundColor: '#EEF3FE', overflow: 'hidden' },
  searchBar: { width: 120, height: 4, backgroundColor: colors.go },
});
