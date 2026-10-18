import Ionicons from '@expo/vector-icons/Ionicons';
import * as Location from 'expo-location';
import { Stack, router } from 'expo-router';
import { useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { LoginCard } from '@/components/login-card';
import { initials } from '@/components/market';
import { RideMap } from '@/components/ride-map';
import { Button } from '@/components/ui';
import { api } from '@/lib/api';
import { km, money } from '@/lib/format';
import { load, save } from '@/lib/storage';
import { colors, radius } from '@/lib/theme';
import type { RideOption, RidePlace, RideQuote, RideVehicle } from '@/lib/types';
import { useFetch } from '@/lib/useFetch';
import { useApp } from '@/state/app-state';

const DEFAULT_MAP = 'https://tiles.openfreemap.org/styles/liberty';
type Place = RidePlace & { address: string };

const labelOf = (a: Location.LocationGeocodedAddress | undefined, fallback: string) => {
  if (!a) return fallback;
  const street = [a.street, a.streetNumber].filter(Boolean).join(' ') || a.name;
  return [street, a.city || a.subregion].filter(Boolean).join(', ') || fallback;
};

/** Pedir un viaje: a dónde vas y con qué empresa (con su precio y cuánto tarda). El precio lo calcula el servidor. */
export default function RideScreen() {
  const insets = useSafeAreaInsets();
  const { location, account } = useApp();
  const cfg = useFetch(() => api.config(), []);
  const mapStyle = cfg.data?.map_style || DEFAULT_MAP;
  const [origin, setOrigin] = useState<Place | null>(location ? { lat: location.lat, lng: location.lng, address: location.label } : null);
  const [note, setNote] = useState('');
  const [dest, setDest] = useState<Place | null>(null);
  const [query, setQuery] = useState('');
  const [found, setFound] = useState<Place[] | null>(null);
  const [recent, setRecent] = useState<Place[]>([]);
  const [busy, setBusy] = useState<'gps' | 'search' | 'quote' | 'order' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [quote, setQuote] = useState<RideQuote | null>(null);
  const [vehicle, setVehicle] = useState<RideVehicle>('auto');
  const [picked, setPicked] = useState<RideOption | null>(null);
  const [needLogin, setNeedLogin] = useState(false);

  useEffect(() => { load<Place[]>('ride_recent', []).then(setRecent); }, []);
  // si ya tiene un viaje en curso, se abre ese
  useEffect(() => {
    if (!account) return;
    api.rideCurrent().then(r => { if (r.ride) router.replace({ pathname: '/ride/[id]', params: { id: String(r.ride.id) } }); }).catch(() => {});
  }, [account]);

  const locateMe = async () => {
    setBusy('gps'); setError(null);
    try {
      const perm = await Location.requestForegroundPermissionsAsync();
      if (!perm.granted) { setError('Necesitamos tu ubicación para saber dónde te buscan.'); return; }
      const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High });
      const addr = await Location.reverseGeocodeAsync(pos.coords).catch(() => []);
      setOrigin({ lat: pos.coords.latitude, lng: pos.coords.longitude, address: labelOf(addr[0], 'Mi ubicación') });
    } catch {
      setError('No pudimos obtener tu ubicación. Activá el GPS y probá de nuevo.');
    } finally { setBusy(null); }
  };
  // sin dirección guardada, el origen es donde está parado (pedir el GPS es sincronizar con el sistema)
  // eslint-disable-next-line react-hooks/set-state-in-effect, react-hooks/exhaustive-deps
  useEffect(() => { if (!origin) locateMe(); }, []);

  const search = async () => {
    const q = query.trim();
    if (q.length < 3) return;
    setBusy('search'); setError(null); setFound(null);
    try {
      const results = (await Location.geocodeAsync(q)).slice(0, 5);
      const labeled = await Promise.all(results.map(async r => {
        const addr = await Location.reverseGeocodeAsync(r).catch(() => []);
        return { lat: r.latitude, lng: r.longitude, address: labelOf(addr[0], q) };
      }));
      setFound(labeled);
      if (!labeled.length) setError('No encontramos esa dirección. Probá agregando la ciudad.');
    } catch {
      setError('No pudimos buscar esa dirección. Revisá tu conexión.');
    } finally { setBusy(null); }
  };

  const choose = async (p: Place) => {
    if (!origin) { setError('Primero necesitamos saber dónde te buscan.'); return; }
    setDest(p); setFound(null); setQuery(''); setPicked(null); setBusy('quote'); setError(null);
    const next = [p, ...recent.filter(r => r.address !== p.address)].slice(0, 4);
    setRecent(next); save('ride_recent', next);
    try {
      const q = await api.rideQuote(origin, p);
      setQuote(q);
      const vehicles = [...new Set(q.options.map(o => o.vehicle))];
      const v = vehicles.includes(vehicle) ? vehicle : (vehicles[0] ?? 'auto');
      setVehicle(v);
      setPicked(q.options.find(o => o.vehicle === v && o.available) ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No pudimos calcular el viaje.'); setDest(null);
    } finally { setBusy(null); }
  };

  const confirm = async () => {
    if (!picked || !origin || !dest) return;
    if (!account) { setNeedLogin(true); return; }
    setBusy('order'); setError(null);
    try {
      const r = await api.rideCreate({ company_id: picked.company_id, vehicle: picked.vehicle, origin: { ...origin, note: note.trim() || null }, dest });
      router.replace({ pathname: '/ride/[id]', params: { id: String(r.ride.id) } });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No pudimos pedir el viaje.');
    } finally { setBusy(null); }
  };

  const vehicles = useMemo(() => [...new Set((quote?.options ?? []).map(o => o.vehicle))], [quote]);
  const options = (quote?.options ?? []).filter(o => o.vehicle === vehicle);

  return (
    <View style={{ flex: 1, backgroundColor: '#fff' }}>
      <Stack.Screen options={{ headerShown: false }} />
      <RideMap mapStyle={mapStyle} origin={origin} dest={dest} style={StyleSheet.absoluteFill} fitKey={dest ? 'ruta' : 'origen'} />
      <Pressable onPress={() => (dest ? (setDest(null), setQuote(null)) : router.back())} style={[st.close, { top: insets.top + 10 }]} accessibilityLabel={dest ? 'Cambiar destino' : 'Cerrar'}>
        <Ionicons name={dest ? 'arrow-back' : 'close'} size={22} color={colors.ink} />
      </Pressable>
      {!!quote && dest && <View style={[st.routePill, { top: insets.top + 14 }]}><Text style={st.routePillText}>{km(quote.km)} · {Math.round(quote.minutes)} min</Text></View>}

      <View style={[st.sheet, { paddingBottom: insets.bottom + 14, maxHeight: dest ? '62%' : '70%' }]}>
        <View style={st.grab} />
        {needLogin ? (
          <ScrollView keyboardShouldPersistTaps="handled">
            <LoginCard title="Entrá para pedir tu viaje" text="Cada viaje queda a tu nombre y la empresa sabe a quién busca. Te mandamos un código por email: sin contraseñas."
              onDone={() => { setNeedLogin(false); }} />
          </ScrollView>
        ) : !dest ? (
          <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ gap: 12 }}>
            <Text style={st.h1}>¿A dónde vamos?</Text>
            <View style={st.box}>
              <Pressable style={st.place} onPress={locateMe} accessibilityLabel="Usar mi ubicación actual como origen">
                <View style={st.dotA} />
                <Text style={st.placeText} numberOfLines={1}>{origin?.address || 'Buscando tu ubicación…'}</Text>
                {busy === 'gps' ? <ActivityIndicator color={colors.brand} /> : <Text style={st.hint}>Tu ubicación</Text>}
              </Pressable>
              <View style={st.sep} />
              <View style={st.place}>
                <View style={st.dotB} />
                <TextInput value={query} onChangeText={setQuery} placeholder="Ingresá el destino" placeholderTextColor={colors.muted} style={st.input}
                  returnKeyType="search" onSubmitEditing={search} autoCorrect={false} autoFocus={!!origin} />
                {busy === 'search' ? <ActivityIndicator color={colors.brand} /> : query.trim().length >= 3 && (
                  <Pressable onPress={search} hitSlop={10} accessibilityLabel="Buscar destino"><Ionicons name="search" size={20} color={colors.brand} /></Pressable>)}
              </View>
            </View>
            <TextInput value={note} onChangeText={setNote} maxLength={160} placeholder="Indicación para el conductor (opcional): puerta, esquina…" placeholderTextColor={colors.muted} style={st.note} />
            {!!error && <Text style={st.error}>{error}</Text>}
            {(found ?? recent).map((p, i) => (
              <Pressable key={i} style={st.row} onPress={() => choose(p)}>
                <View style={st.rowIco}><Ionicons name={found ? 'location-outline' : 'time-outline'} size={19} color={colors.ink} /></View>
                <Text style={st.rowText} numberOfLines={2}>{p.address}</Text>
              </Pressable>
            ))}
            <View style={st.safe}><Ionicons name="shield-checkmark-outline" size={18} color={colors.good} />
              <Text style={st.safeText}>Solo empresas habilitadas, con seguro de pasajeros y choferes con licencia profesional.</Text></View>
          </ScrollView>
        ) : busy === 'quote' || !quote ? (
          <View style={{ padding: 30, alignItems: 'center' }}><ActivityIndicator color={colors.brand} size="large" /><Text style={[st.hint, { marginTop: 10 }]}>Buscando empresas y precios…</Text></View>
        ) : (
          <View style={{ flexShrink: 1 }}>
            <View style={st.headRow}><Text style={st.h2}>Elegí tu viaje</Text><Text style={st.hint} numberOfLines={1}>a {dest.address.split(',')[0]}</Text></View>
            {vehicles.length > 1 && (
              <View style={st.seg}>
                {vehicles.map(v => (
                  <Pressable key={v} style={[st.segBtn, vehicle === v && st.segOn]} onPress={() => { setVehicle(v); setPicked(quote.options.find(o => o.vehicle === v && o.available) ?? null); }}>
                    <Ionicons name={v === 'moto' ? 'bicycle-outline' : 'car-outline'} size={17} color={vehicle === v ? colors.ink : colors.muted} />
                    <Text style={[st.segText, vehicle === v && { color: colors.ink }]}>{v === 'moto' ? 'Moto' : 'Auto'}</Text>
                  </Pressable>
                ))}
              </View>
            )}
            <ScrollView style={{ flexShrink: 1 }} contentContainerStyle={{ gap: 10, paddingVertical: 4 }}>
              {!options.length && <Text style={st.hint}>No hay empresas con {vehicle} en tu ciudad.</Text>}
              {options.map(o => {
                const on = picked?.company_id === o.company_id && picked.vehicle === o.vehicle;
                return (
                  <Pressable key={`${o.company_id}-${o.vehicle}`} disabled={!o.available} onPress={() => setPicked(o)}
                    style={[st.opt, on && st.optOn, !o.available && { opacity: 0.5 }]} accessibilityRole="radio" accessibilityState={{ selected: on }}>
                    <View style={[st.logo, { backgroundColor: on ? colors.brand : colors.ink }]}><Text style={st.logoText}>{initials(o.company)}</Text></View>
                    <View style={{ flex: 1 }}>
                      <Text style={st.optName} numberOfLines={1}>{o.company}</Text>
                      <Text style={st.optSub}>{o.rating ? `★ ${o.rating.toFixed(1).replace('.', ',')} · ` : ''}{o.available ? `Llega en ${o.eta_min} min` : 'Sin conductores libres'}</Text>
                    </View>
                    <View style={{ alignItems: 'flex-end' }}>
                      <Text style={st.price}>{money(o.price)}</Text>
                      {o.badge ? <Text style={[st.badge, o.badge === 'Mejor precio' && st.badgeAlt]}>{o.badge}</Text> : <Text style={st.hint}>estimado</Text>}
                    </View>
                  </Pressable>
                );
              })}
            </ScrollView>
            <View style={st.payRow}>
              <Ionicons name="cash-outline" size={19} color={colors.good} />
              <Text style={{ flex: 1, fontWeight: '800', color: colors.ink }}>Efectivo</Text>
              <Text style={st.hint}>{quote.night ? 'Tarifa nocturna · ' : ''}se paga al conductor</Text>
            </View>
            {!!error && <Text style={st.error}>{error}</Text>}
            <Button title={picked ? `Confirmar ${picked.company}` : 'Elegí una empresa'} disabled={!picked} loading={busy === 'order'} onPress={confirm} />
            <Text style={[st.hint, { textAlign: 'center', marginTop: 8 }]}>Precio estimado: se suma la espera si el conductor te espera más de unos minutos.</Text>
          </View>
        )}
      </View>
    </View>
  );
}

const st = StyleSheet.create({
  close: { position: 'absolute', left: 16, width: 44, height: 44, borderRadius: 22, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center', elevation: 4, shadowColor: '#000', shadowOpacity: 0.15, shadowRadius: 8 },
  routePill: { position: 'absolute', alignSelf: 'center', backgroundColor: '#fff', paddingHorizontal: 14, paddingVertical: 7, borderRadius: radius.pill, elevation: 4 },
  routePillText: { fontWeight: '800', color: colors.ink },
  sheet: { position: 'absolute', left: 0, right: 0, bottom: 0, backgroundColor: '#fff', borderTopLeftRadius: 26, borderTopRightRadius: 26, paddingHorizontal: 18, paddingTop: 8, elevation: 16, shadowColor: '#000', shadowOpacity: 0.12, shadowRadius: 18 },
  grab: { width: 40, height: 5, borderRadius: 3, backgroundColor: colors.line, alignSelf: 'center', marginBottom: 12 },
  h1: { fontSize: 24, fontWeight: '800', color: colors.ink, letterSpacing: -0.4 },
  h2: { fontSize: 20, fontWeight: '800', color: colors.ink, flex: 1 },
  headRow: { flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 10 },
  box: { borderWidth: 1, borderColor: colors.line, borderRadius: radius.md, paddingHorizontal: 14 },
  place: { flexDirection: 'row', alignItems: 'center', gap: 12, minHeight: 52 },
  placeText: { flex: 1, fontWeight: '700', color: colors.ink, fontSize: 15.5 },
  input: { flex: 1, fontSize: 16, color: colors.ink, paddingVertical: 12 },
  sep: { height: 1, backgroundColor: colors.line, marginLeft: 22 },
  dotA: { width: 10, height: 10, borderRadius: 5, backgroundColor: colors.ink },
  dotB: { width: 10, height: 10, backgroundColor: colors.brand },
  hint: { color: colors.muted, fontSize: 13 },
  note: { borderWidth: 1, borderColor: colors.line, borderRadius: radius.md, paddingHorizontal: 14, paddingVertical: 11, fontSize: 14.5, color: colors.ink },
  error: { color: colors.bad, fontWeight: '700' },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 6 },
  rowIco: { width: 38, height: 38, borderRadius: 19, backgroundColor: colors.bg, alignItems: 'center', justifyContent: 'center' },
  rowText: { flex: 1, fontWeight: '700', color: colors.ink, fontSize: 15 },
  safe: { flexDirection: 'row', gap: 10, alignItems: 'center', backgroundColor: colors.goodSoft, padding: 12, borderRadius: radius.md, marginTop: 4 },
  safeText: { flex: 1, color: '#14532D', fontSize: 13 },
  seg: { flexDirection: 'row', backgroundColor: colors.bg, borderRadius: radius.md, padding: 4, marginBottom: 10 },
  segBtn: { flex: 1, flexDirection: 'row', gap: 6, alignItems: 'center', justifyContent: 'center', paddingVertical: 10, borderRadius: 12 },
  segOn: { backgroundColor: '#fff', elevation: 2, shadowColor: '#000', shadowOpacity: 0.08, shadowRadius: 4 },
  segText: { fontWeight: '800', color: colors.muted },
  opt: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: 12, borderRadius: radius.md, borderWidth: 1.5, borderColor: colors.line },
  optOn: { borderColor: colors.brand, backgroundColor: '#FAF7FF' },
  logo: { width: 44, height: 44, borderRadius: 12, alignItems: 'center', justifyContent: 'center' },
  logoText: { color: '#fff', fontWeight: '900' },
  optName: { fontWeight: '800', color: colors.ink, fontSize: 16 },
  optSub: { color: colors.muted, fontSize: 13, marginTop: 1 },
  price: { fontWeight: '900', color: colors.ink, fontSize: 18 },
  badge: { color: colors.good, fontWeight: '800', fontSize: 11.5, marginTop: 2 },
  badgeAlt: { color: colors.brand, backgroundColor: colors.brandSoft, paddingHorizontal: 6, borderRadius: 6, overflow: 'hidden' },
  payRow: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 12 },
});
