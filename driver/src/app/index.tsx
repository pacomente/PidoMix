import Ionicons from '@expo/vector-icons/Ionicons';
import { Redirect, router } from 'expo-router';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, Animated, Easing, Pressable, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { DriverMap, type MapTarget } from '@/components/driver-map';
import { OfferCard } from '@/components/offer-card';
import { RideOfferCard } from '@/components/ride-offer-card';
import { RideSheet } from '@/components/ride-sheet';
import { TripSheet } from '@/components/trip-sheet';
import { RoundButton } from '@/components/ui';
import { money } from '@/lib/format';
import { fmtMeters, stepIcon, useGuidance } from '@/lib/guidance';
import { radius, themed } from '@/lib/theme';
import { useColors } from '@/state/prefs';
import { useSession } from '@/state/session';

function pt(p: { lat?: number; lng?: number }) {
  return p.lat !== undefined && p.lng !== undefined ? { lat: p.lat, lng: p.lng } : null;
}

function Searching({ color, track }: { color: string; track: string }) {
  const [x] = useState(() => new Animated.Value(0));
  useEffect(() => {
    const loop = Animated.loop(Animated.timing(x, { toValue: 1, duration: 1400, easing: Easing.inOut(Easing.ease), useNativeDriver: true }));
    loop.start();
    return () => loop.stop();
  }, [x]);
  return (
    <View style={{ height: 4, marginHorizontal: -16, marginTop: -16, marginBottom: 14, backgroundColor: track, overflow: 'hidden' }}>
      <Animated.View style={{ width: 120, height: 4, backgroundColor: color, transform: [{ translateX: x.interpolate({ inputRange: [0, 1], outputRange: [-120, 360] }) }] }} />
    </View>
  );
}

export default function Home() {
  const insets = useSafeAreaInsets();
  const c = useColors(), st = useSt(c);
  const { ready, loggedIn, state, position, error, offline, busy, goOnline, goOffline, act, deliver, pickup, fail, rideAct, rideStart, lastDelivery, clearDelivery } = useSession();
  const [sheetH, setSheetH] = useState(220);
  const [goingTo, setGoingTo] = useState<string | null>(null);  // la zona a la que eligió ir
  const [overviewFor, setOverviewFor] = useState<string | null>(null);  // eligió ver todo el recorrido (en vez de seguirlo) para este destino
  const [recenter, setRecenter] = useState(0);
  const trip = state?.trip ?? null, demand = state?.demand ?? null;
  // conductores de empresas de viajes: un viaje (pasajero) en vez de un pedido
  const ride = state?.ride ?? null, rideOffer0 = state?.ride_offer ?? null;
  const suggestion = !trip && !ride && !state?.offer ? demand?.suggestion ?? null : null;
  const zoneKey = suggestion ? `${suggestion.lat.toFixed(3)},${suggestion.lng.toFixed(3)}` : '';
  const going = !!suggestion && goingTo === zoneKey;  // si aparece un viaje o la zona se vacía, deja de ir solo
  const to = trip || ride ? 'trip' : going ? 'suggestion' : null;
  const rideKey = ride ? `r${ride.id}:${ride.status === 'en_viaje' ? 'destino' : 'pasajero'}` : '';
  const destKey = trip ? `${trip.order_id}:${trip.stage}` : ride ? rideKey : zoneKey;
  const guide = useGuidance(to, destKey, position);
  // en viaje (o yendo a una zona) el mapa lo sigue como un GPS; con cada destino nuevo vuelve a seguirlo
  const follow = !!to && !!position && !state?.offer && !rideOffer0 && overviewFor !== `${to}|${destKey}`;

  const offer0 = state?.offer ?? null;
  // los destinos del mapa cambian solo con el viaje, la oferta o la zona elegida (no con cada pulso)
  // una oferta (también la de sumar un pedido al viaje) se muestra primero: tiene pocos segundos para aceptarla
  const targetsKey = offer0 ? `o${offer0.id}` : rideOffer0 ? `ro${rideOffer0.id}` : trip ? `t${trip.order_id}:${trip.stage}` : ride ? rideKey : going ? `z${zoneKey}` : '';
  const targets = useMemo<MapTarget[]>(() => {
    const out: MapTarget[] = [];
    if (rideOffer0) {
      out.push({ kind: 'pickup', point: rideOffer0.pickup, label: 'Pasajero' }, { kind: 'dropoff', point: rideOffer0.dropoff, label: 'Destino' });
    } else if (ride) {
      if (ride.status !== 'en_viaje') out.push({ kind: 'pickup', point: ride.pickup, label: ride.passenger.name.split(' ')[0] });
      out.push({ kind: 'dropoff', point: ride.dropoff, label: 'Destino' });
    } else if (offer0) {
      const s = pt(offer0.store), cu = pt(offer0.dropoff);
      if (s) out.push({ kind: 'store', point: s, label: offer0.store.name });
      if (cu) out.push({ kind: 'customer', point: cu, label: 'Entrega' });
    } else if (trip) {
      const s = pt(trip.store), cu = pt(trip.customer);
      if (trip.stage === 'pickup') { if (s) out.push({ kind: 'store', point: s, label: trip.store.name }); if (cu) out.push({ kind: 'customer', point: cu, label: 'Cliente' }); }
      else if (cu) out.push({ kind: 'customer', point: cu, label: trip.customer.name });
    } else if (going && suggestion) {
      out.push({ kind: 'hotspot', point: { lat: suggestion.lat, lng: suggestion.lng }, label: 'Zona con pedidos' });
    }
    return out;
  }, [targetsKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const followKey = `${to}|${destKey}`;
  const onUserMove = useCallback(() => { if (follow) setOverviewFor(followKey); }, [follow, followKey]);
  const noHotspots = useMemo(() => [], []);

  useEffect(() => {
    if (!lastDelivery) return;
    const t = setTimeout(clearDelivery, 4000);
    return () => clearTimeout(t);
  }, [lastDelivery, clearDelivery]);

  if (!ready) return <View style={st.center}><ActivityIndicator color={c.ink} size="large" /></View>;
  if (!loggedIn) return <Redirect href="/login" />;
  if (!state) return <View style={st.center}><ActivityIndicator color={c.ink} size="large" />{error && <Text style={st.loadErr}>{error}</Text>}</View>;

  const { courier, offer, earnings } = state;
  const rideOffer = state.ride_offer ?? null;
  const hot = demand && demand.level !== 'normal';
  const bannerTop = insets.top + (guide.step ? 160 : 70);
  const toggleView = () => {
    if (!to) { setRecenter(n => n + 1); return; }
    setOverviewFor(follow ? followKey : null);
    setRecenter(n => n + 1);
  };

  return (
    <View style={{ flex: 1, backgroundColor: c.mapBg }}>
      <DriverMap me={position} targets={targets} bottomInset={sheetH} path={offer || rideOffer ? null : guide.directions?.geometry} hotspots={!trip && !ride && courier.online ? demand?.hotspots ?? noHotspots : noHotspots}
        follow={follow} recenter={recenter} onUserMove={onUserMove} />

      {/* barra superior: menú, ganancias del día y demanda */}
      <View style={[st.top, { paddingTop: insets.top + 8 }]} pointerEvents="box-none">
        <RoundButton icon="menu" label="Menú" onPress={() => router.push('/menu')} />
        <Pressable style={st.earnPill} onPress={() => router.push('/earnings')} accessibilityLabel="Ver ganancias">
          <Text style={st.earnValue}>{money(earnings.today)}</Text>
          <Text style={st.earnLabel}>hoy · {earnings.trips_today} {earnings.trips_today === 1 ? 'viaje' : 'viajes'}</Text>
        </Pressable>
        {hot && demand?.multiplier_text && !trip  // en viaje no: lo que cobra ese viaje ya quedó fijo al aceptarlo
          ? <View style={st.surgePill}><Ionicons name="flame" size={16} color="#fff" /><Text style={st.surgePillText}>{demand.multiplier_text}</Text></View>
          : <View style={{ width: 50 }} />}
      </View>
      {/* indicaciones: el próximo giro y cuánto falta */}
      {guide.step && (
        <View style={[st.nav, { top: insets.top + 66 }]}>
          <View style={st.navIcon}><Ionicons name={stepIcon(guide.step) as never} size={30} color="#fff" /></View>
          <View style={{ flex: 1 }}>
            {guide.toStep !== null && guide.step.type !== 'arrive' && <Text style={st.navDist}>En {fmtMeters(guide.toStep)}</Text>}
            <Text style={st.navText} numberOfLines={2}>{guide.step.text}</Text>
            {!!guide.directions && <Text style={st.navEta}>{Math.max(1, Math.round(guide.directions.minutes))} min · {guide.directions.km.toFixed(1).replace('.', ',')} km{ride ? (ride.status === 'en_viaje' ? ' hasta el destino' : ' hasta el pasajero') : guide.info?.kind === 'store' ? ' hasta el local' : guide.info?.kind === 'customer' ? ' hasta la entrega' : ' hasta la zona'}</Text>}
          </View>
        </View>
      )}
      {offline && (
        <View style={[st.offline, { top: bannerTop }]}>
          <Ionicons name="cloud-offline" size={18} color="#3D2A00" />
          <Text style={st.offlineText}>Sin conexión · reintentando…</Text>
        </View>
      )}
      {!!error && !offline && <View style={[st.error, { top: bannerTop }]}><Text style={st.errorText}>{error}</Text></View>}
      {!error && !offline && courier.cash?.blocked && !trip && (
        <Pressable style={[st.cashBlocked, { top: bannerTop }]} onPress={() => router.push('/caja')} accessibilityLabel="Ver mi caja">
          <Text style={st.errorText}>BLOQUEADO PARA PEDIDOS EN EFECTIVO</Text>
          <Text style={st.cashBlockedSub}>Tenés {money(courier.cash.pending)} sin rendir (límite {money(courier.cash.limit)}).{courier.cash.online_enabled ? ' Seguís recibiendo pedidos pagados online.' : ''} Tocá para ver tu caja.</Text>
        </Pressable>
      )}
      {lastDelivery && (
        <View style={[st.delivered, { top: bannerTop }]}>
          <Text style={st.deliveredMoney}>+{money(lastDelivery.earnings)}</Text>
          <Text style={st.deliveredText}>{lastDelivery.ride ? `¡Viaje #${lastDelivery.order_id} terminado!` : `¡Pedido #${lastDelivery.order_id} entregado!`}</Text>
          {!!lastDelivery.collected && <Text style={st.deliveredText}>Cobraste {money(lastDelivery.collected)} en efectivo</Text>}
        </View>
      )}

      {/* recentrar / seguirme: arriba del panel de abajo */}
      {!!position && !offer && !rideOffer && (
        <View style={[st.mapBtns, { bottom: sheetH + 12 }]} pointerEvents="box-none">
          <RoundButton icon={to ? (follow ? 'navigate' : 'locate') : 'locate'} active={follow} onPress={toggleView}
            label={to ? (follow ? 'Ver todo el recorrido' : 'Seguirme en el mapa') : 'Centrar en mi ubicación'} />
        </View>
      )}

      {/* parte de abajo: según el estado */}
      <View style={[st.bottom, { paddingBottom: insets.bottom + (trip || ride ? 0 : 12) }]} onLayout={e => setSheetH(e.nativeEvent.layout.height)}>
        {rideOffer ? (
          <View style={{ paddingHorizontal: 12 }}><RideOfferCard key={rideOffer.id} offer={rideOffer} busy={busy} onAccept={() => rideAct('accept', rideOffer.id)} onReject={() => rideAct('reject', rideOffer.id)} /></View>
        ) : ride ? (
          <RideSheet key={ride.id} ride={ride} busy={busy} eta={guide.directions ? { minutes: guide.directions.minutes, km: guide.directions.km } : null}
            onArrive={() => rideAct('arrive', ride.id)} onStart={pin => rideStart(ride.id, pin)} onFinish={() => rideAct('finish', ride.id)} onCancel={reason => rideAct('cancel', ride.id, reason)} />
        ) : offer ? (
          <View style={{ paddingHorizontal: 12 }}><OfferCard key={offer.id} offer={offer} busy={busy} onAccept={() => act('accept', offer.id)} onReject={() => act('reject', offer.id)} /></View>
        ) : trip ? (
          <TripSheet trip={trip} stops={state.trips ?? []} busy={busy} eta={guide.directions ? { minutes: guide.directions.minutes, km: guide.directions.km } : null}
            onPickup={code => pickup(trip.order_id, code)} onDeliver={pin => deliver(trip.order_id, pin)} onRelease={() => act('release', trip.order_id)} onFail={reason => fail(trip.order_id, reason)} />
        ) : courier.online ? (
          <View style={[st.bar, hot && st.barHot]}>
            <Searching color={hot ? c.danger : c.go} track={c.line} />
            {hot && (
              <View style={st.hotRow}>
                <Ionicons name="flame" size={18} color={c.danger} />
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
                  <Text style={[st.suggestBtnText, going && { color: c.ink }]}>{going ? 'Cancelar' : 'Llevame'}</Text>
                </Pressable>
              </View>
            )}
            <View style={st.barRow}>
              <View style={st.onDot} />
              <View style={{ flex: 1 }}>
                <Text style={st.barTitle}>Buscando viajes</Text>
                <Text style={st.barSub}>{courier.fleet === 'empresa' ? `Viajes de ${courier.company || 'tu empresa'}. Dejá la app abierta: te suena cuando te piden uno.`
                  : demand && demand.waiting > 0 ? `${demand.waiting} ${demand.waiting === 1 ? 'pedido esperando' : 'pedidos esperando'} repartidor en tu ciudad.` : 'Dejá la app abierta: te suena cuando hay un pedido cerca.'}</Text>
              </View>
              <Pressable onPress={goOffline} disabled={busy} style={st.stop} accessibilityLabel="Desconectarse">
                {busy ? <ActivityIndicator color={c.danger} /> : <Ionicons name="hand-left" size={22} color={c.dangerText} />}
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
              {earnings.week > 0 && (
                <Pressable onPress={() => router.push('/earnings')} style={st.weekRow} accessibilityLabel="Ver ganancias">
                  <Text style={st.weekLbl}>Últimos 7 días</Text>
                  <Text style={st.weekVal}>{money(earnings.week)} · {earnings.trips_week} {earnings.trips_week === 1 ? 'viaje' : 'viajes'}</Text>
                  <Ionicons name="chevron-forward" size={16} color={c.muted} />
                </Pressable>
              )}
            </View>
          </View>
        )}
      </View>
    </View>
  );
}

const useSt = themed(c => ({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: c.bg, gap: 16, padding: 24 },
  loadErr: { color: c.ink, textAlign: 'center' },
  top: { position: 'absolute', left: 0, right: 0, top: 0, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 14 },
  earnPill: { backgroundColor: c.inverse, paddingHorizontal: 20, paddingVertical: 8, borderRadius: radius.pill, alignItems: 'center', shadowColor: '#000', shadowOpacity: 0.3, shadowRadius: 8, elevation: 6 },
  earnValue: { color: c.onInverse, fontSize: 22, fontWeight: '900', fontVariant: ['tabular-nums'] },
  earnLabel: { color: c.dark ? '#555' : '#BBB', fontSize: 11.5, fontWeight: '700' },
  cashBlocked: { position: 'absolute', left: 16, right: 16, backgroundColor: '#3A0D08', padding: 12, borderRadius: radius.sm, gap: 2 },
  cashBlockedSub: { color: '#FFD3CC', textAlign: 'center', fontSize: 13 },
  offline: { position: 'absolute', alignSelf: 'center', flexDirection: 'row', alignItems: 'center', gap: 8, backgroundColor: c.warn, paddingHorizontal: 14, paddingVertical: 8, borderRadius: radius.pill, shadowColor: '#000', shadowOpacity: 0.25, shadowRadius: 8, elevation: 6 },
  offlineText: { color: '#3D2A00', fontWeight: '900' },
  error: { position: 'absolute', left: 16, right: 16, backgroundColor: c.danger, padding: 12, borderRadius: radius.sm },
  errorText: { color: '#fff', fontWeight: '700', textAlign: 'center' },
  delivered: { position: 'absolute', left: 40, right: 40, backgroundColor: c.money, padding: 14, borderRadius: radius.md, alignItems: 'center' },
  deliveredMoney: { color: '#fff', fontSize: 30, fontWeight: '900' },
  deliveredText: { color: '#fff', fontWeight: '700' },
  mapBtns: { position: 'absolute', right: 14 },
  bottom: { position: 'absolute', left: 0, right: 0, bottom: 0 },
  go: { width: 96, height: 96, borderRadius: 48, backgroundColor: c.go, alignItems: 'center', justifyContent: 'center', borderWidth: 5, borderColor: c.card, marginBottom: 14, shadowColor: '#000', shadowOpacity: 0.35, shadowRadius: 12, elevation: 10 },
  goText: { color: '#fff', fontSize: 30, fontWeight: '900', letterSpacing: 1 },
  bar: { marginHorizontal: 12, backgroundColor: c.card, borderRadius: radius.md, padding: 16, overflow: 'hidden', shadowColor: '#000', shadowOpacity: c.shadow, shadowRadius: 12, elevation: 8 },
  barRow: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  barTitle: { fontSize: 20, fontWeight: '900', color: c.ink },
  barSub: { color: c.muted, marginTop: 2 },
  onDot: { width: 12, height: 12, borderRadius: 6, backgroundColor: c.money },
  offDot: { width: 12, height: 12, borderRadius: 6, backgroundColor: c.muted },
  stop: { width: 50, height: 50, borderRadius: 25, backgroundColor: c.failBg, alignItems: 'center', justifyContent: 'center' },
  barHot: { borderWidth: 2, borderColor: c.danger },
  hotRow: { flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: c.hotBg, marginHorizontal: -16, marginTop: -14, marginBottom: 12, paddingHorizontal: 16, paddingVertical: 8 },
  hotText: { color: c.dangerText, fontWeight: '900', fontSize: 15 },
  suggest: { flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: c.card2, borderRadius: radius.sm, padding: 10, marginBottom: 12 },
  suggestTitle: { fontWeight: '900', color: c.ink },
  suggestText: { color: c.muted, fontSize: 13, marginTop: 1 },
  suggestBtn: { backgroundColor: c.danger, paddingHorizontal: 14, paddingVertical: 9, borderRadius: radius.pill },
  suggestBtnOff: { backgroundColor: c.line },
  suggestBtnText: { color: '#fff', fontWeight: '900' },
  surgePill: { flexDirection: 'row', alignItems: 'center', gap: 4, height: 40, paddingHorizontal: 14, borderRadius: radius.pill, backgroundColor: c.danger, shadowColor: '#000', shadowOpacity: 0.25, shadowRadius: 8, elevation: 6 },
  surgePillText: { color: '#fff', fontWeight: '900', fontSize: 17 },
  nav: { position: 'absolute', left: 12, right: 12, flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: c.navBg, borderRadius: radius.md, padding: 12, shadowColor: '#000', shadowOpacity: 0.3, shadowRadius: 10, elevation: 8 },
  navIcon: { width: 52, height: 52, borderRadius: 12, backgroundColor: 'rgba(255,255,255,.12)', alignItems: 'center', justifyContent: 'center' },
  navDist: { color: '#9FE8C8', fontWeight: '900', fontSize: 15 },
  navText: { color: '#fff', fontWeight: '900', fontSize: 19 },
  navEta: { color: '#CDE9DD', fontSize: 12.5, marginTop: 2 },
  weekRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 14, paddingTop: 12, borderTopWidth: 1, borderTopColor: c.line },
  weekLbl: { color: c.muted, fontWeight: '700', flex: 1 },
  weekVal: { color: c.ink, fontWeight: '900' },
}));
