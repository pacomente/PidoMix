import Ionicons from '@expo/vector-icons/Ionicons';
import { useEffect, useRef, useState } from 'react';
import { Linking, Pressable, Text, TextInput, View } from 'react-native';

import { Button, SlideButton } from '@/components/ui';
import { km, money } from '@/lib/format';
import { openNav } from '@/lib/nav';
import { radius, themed } from '@/lib/theme';
import type { DriverRide } from '@/lib/types';
import { useColors, usePrefs } from '@/state/prefs';

const mmss = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;

/** Panel del viaje de la empresa: 1) buscar al pasajero y arrancar con su PIN, 2) llevarlo y cobrar. */
export function RideSheet({ ride, busy, eta, onArrive, onStart, onFinish, onCancel }: {
  ride: DriverRide; busy: boolean; eta?: { minutes: number; km: number } | null;
  onArrive: () => void; onStart: (pin: string) => Promise<string | null>; onFinish: () => void; onCancel: (reason: string) => void;
}) {
  const c = useColors(), st = useSt(c);
  const { navApp } = usePrefs();
  const [pin, setPin] = useState('');
  const [pinError, setPinError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [waited, setWaited] = useState(ride.waited_seconds);
  const sending = useRef(false);
  const onBoard = ride.status === 'en_viaje';
  const first = ride.passenger.name.split(' ')[0];

  // el reloj de la espera en la puerta corre solo entre pulsos
  useEffect(() => {
    setWaited(ride.waited_seconds); // eslint-disable-line react-hooks/set-state-in-effect
    if (ride.waited_seconds === null) return;
    const t = setInterval(() => setWaited(w => (w === null ? null : w + 1)), 1000);
    return () => clearInterval(t);
  }, [ride.waited_seconds]);

  const send = async (value: string) => {
    if (sending.current) return;
    sending.current = true;
    setPinError(null);
    const err = await onStart(value);
    sending.current = false;
    if (err) { setPinError(err); setPin(''); }
  };
  const freeLeft = waited !== null ? ride.wait_free_minutes * 60 - waited : null;
  const target = onBoard ? ride.dropoff : ride.pickup;

  return (
    <View style={st.sheet}>
      <View style={st.grab} />
      <View style={st.steps}>
        <View style={{ flex: 1 }}><View style={[st.stepBar, st.stepOn]} /><Text style={[st.stepTxt, !onBoard && st.stepTxtOn]}>{onBoard ? '✓ Pasajero arriba' : '1 · Buscar pasajero'}</Text></View>
        <View style={{ flex: 1 }}><View style={[st.stepBar, onBoard && st.stepOn]} /><Text style={[st.stepTxt, onBoard && st.stepTxtOn]}>2 · En viaje</Text></View>
      </View>

      {cancelling ? (
        <View style={{ gap: 8 }}>
          <Text style={st.h}>¿Por qué soltás el viaje?</Text>
          <Text style={st.muted}>Se le ofrece a otro conductor de {ride.company.name}. Si el pasajero no aparece, el viaje se cancela.</Text>
          {ride.cancel_reasons.map(r => <Button key={r.code} title={r.label} variant="light" loading={busy} onPress={() => { setCancelling(false); onCancel(r.code); }} />)}
          <Pressable onPress={() => setCancelling(false)} style={st.link}><Text style={[st.linkText, { color: c.muted }]}>Volver</Text></Pressable>
        </View>
      ) : (
        <>
          <View style={st.row}>
            <Text style={st.muted} numberOfLines={1}>{ride.company.name}{eta ? ` · ${Math.max(1, Math.round(eta.minutes))} min · ${km(eta.km)}` : ''}</Text>
            <Text style={st.price}>{money(ride.price)}</Text>
          </View>
          {onBoard ? (
            <>
              <Text style={st.title} numberOfLines={1}>{ride.dropoff.address || 'Destino'}</Text>
              <Text style={st.muted}>Llevás a {first} · {km(ride.trip_km)}</Text>
              <View style={st.collect}>
                <Text style={st.collectLbl}>COBRAR EN EFECTIVO</Text>
                <Text style={st.collectVal}>{money(ride.collect)}</Text>
                <Text style={st.muted}>Si esperaste en la puerta, se suma la espera al terminar.</Text>
              </View>
            </>
          ) : (
            <>
              <View style={st.pax}>
                <View style={st.avatar}><Text style={st.avatarText}>{first[0]}</Text></View>
                <View style={{ flex: 1 }}>
                  <Text style={st.title} numberOfLines={1}>{first}</Text>
                  <Text style={st.muted} numberOfLines={2}>{ride.pickup.address || 'Ubicación del pasajero'}{ride.pickup.note ? ` · ${ride.pickup.note}` : ''}</Text>
                </View>
              </View>
              {ride.status === 'en_puerta' && waited !== null && (
                <View style={[st.wait, freeLeft !== null && freeLeft < 0 && { backgroundColor: c.cashBg }]}>
                  <Ionicons name="time-outline" size={16} color={c.ink} />
                  <Text style={st.waitText}>Esperando {mmss(Math.max(0, waited))}{freeLeft !== null && freeLeft > 0 ? ` · ${Math.ceil(freeLeft / 60)} min gratis` : ride.per_wait_min ? ` · se cobra ${money(ride.per_wait_min)}/min` : ''}</Text>
                </View>
              )}
            </>
          )}

          <View style={st.actions}>
            <Pressable onPress={() => openNav({ lat: target.lat, lng: target.lng, address: target.address }, navApp)} style={({ pressed }) => [st.navBtn, pressed && { opacity: 0.85 }]} accessibilityRole="button" accessibilityLabel="Navegar">
              <Ionicons name="navigate" size={20} color="#fff" /><Text style={st.navBtnText}>Navegar</Text>
            </Pressable>
            {!!ride.passenger.phone && (
              <Pressable onPress={() => Linking.openURL(`tel:${ride.passenger.phone}`)} style={st.action} accessibilityRole="button" accessibilityLabel={`Llamar a ${first}`}>
                <Ionicons name="call-outline" size={20} color={c.ink} /><Text style={st.actionText}>Llamar</Text>
              </Pressable>
            )}
          </View>

          {ride.status === 'asignado' && (
            <Button title={`Llegué · avisarle a ${first}`} icon="flag" variant="light" loading={busy} onPress={onArrive} />
          )}
          {!onBoard ? (
            <View style={{ gap: 8 }}>
              <Text style={st.h}>Pedile el PIN a {first} para arrancar</Text>
              <TextInput value={pin} onChangeText={v => { const d = v.replace(/\D/g, '').slice(0, 4); setPin(d); setPinError(null); if (d.length === 4) send(d); }}
                keyboardType="number-pad" maxLength={4} placeholder="••••" placeholderTextColor={c.muted} accessibilityLabel="PIN del pasajero"
                style={[st.pinInput, !!pinError && { borderColor: c.danger }]} />
              {!!pinError && <Text style={st.pinError}>{pinError}</Text>}
              <SlideButton title="Subió · empezar viaje" loading={busy} disabled={pin.length !== 4} onConfirm={() => send(pin)} />
              {!!ride.cancel_reasons.length && <Pressable onPress={() => setCancelling(true)} style={st.link}><Text style={st.linkText}>No puedo hacer este viaje</Text></Pressable>}
            </View>
          ) : (
            <SlideButton variant="money" title={`Llegamos · cobré ${money(ride.collect)}`} loading={busy} onConfirm={onFinish} />
          )}
          <Text style={st.privacy}>📍 {first} ve en el mapa dónde estás mientras dura el viaje.</Text>
        </>
      )}
    </View>
  );
}

const useSt = themed(c => ({
  sheet: { backgroundColor: c.card, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, padding: 18, paddingTop: 10, gap: 6, shadowColor: '#000', shadowOpacity: c.shadow, shadowRadius: 16, elevation: 12 },
  grab: { alignSelf: 'center', width: 40, height: 5, borderRadius: 3, backgroundColor: c.line, marginBottom: 6 },
  steps: { flexDirection: 'row', gap: 6, marginBottom: 6 },
  stepBar: { height: 4, borderRadius: 2, backgroundColor: c.line },
  stepOn: { backgroundColor: c.go },
  stepTxt: { fontSize: 11.5, fontWeight: '700', color: c.muted, marginTop: 4 },
  stepTxtOn: { color: c.ink },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8, justifyContent: 'space-between' },
  muted: { color: c.muted, fontSize: 13.5, flexShrink: 1 },
  price: { fontWeight: '900', fontSize: 18, color: c.moneyText },
  title: { fontSize: 24, fontWeight: '900', color: c.ink, letterSpacing: -0.4 },
  h: { fontSize: 17, fontWeight: '900', color: c.ink, marginTop: 4 },
  pax: { flexDirection: 'row', alignItems: 'center', gap: 12, marginTop: 4 },
  avatar: { width: 48, height: 48, borderRadius: 24, backgroundColor: c.infoBg, alignItems: 'center', justifyContent: 'center' },
  avatarText: { color: c.go, fontWeight: '900', fontSize: 20 },
  wait: { flexDirection: 'row', alignItems: 'center', gap: 6, alignSelf: 'flex-start', backgroundColor: c.card2, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 8, marginTop: 6 },
  waitText: { color: c.ink, fontWeight: '800', fontSize: 13.5 },
  collect: { marginTop: 8, padding: 12, borderRadius: radius.sm, borderWidth: 1, backgroundColor: c.cashBg, borderColor: c.cashLine, gap: 2 },
  collectLbl: { color: c.cashText, fontWeight: '800', letterSpacing: 0.5, fontSize: 12.5 },
  collectVal: { fontSize: 30, fontWeight: '900', color: c.ink },
  actions: { flexDirection: 'row', gap: 8, marginVertical: 10 },
  navBtn: { flex: 1, minHeight: 50, borderRadius: radius.pill, backgroundColor: c.go, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8 },
  navBtnText: { color: '#fff', fontWeight: '900', fontSize: 17 },
  action: { minHeight: 50, paddingHorizontal: 16, borderRadius: radius.pill, backgroundColor: c.card2, flexDirection: 'row', alignItems: 'center', gap: 6 },
  actionText: { fontSize: 14, fontWeight: '800', color: c.ink },
  pinInput: { alignSelf: 'stretch', textAlign: 'center', fontSize: 40, fontWeight: '900', letterSpacing: 18, paddingVertical: 10, borderRadius: radius.sm, borderWidth: 2, borderColor: c.line, color: c.ink, backgroundColor: c.card2 },
  pinError: { color: c.dangerText, fontWeight: '700', textAlign: 'center' },
  link: { alignItems: 'center', paddingVertical: 8 },
  linkText: { color: c.dangerText, fontWeight: '700' },
  privacy: { color: c.muted, fontSize: 12, marginTop: 4 },
}));
