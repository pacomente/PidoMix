import Ionicons from '@expo/vector-icons/Ionicons';
import * as Location from 'expo-location';
import { Stack, router } from 'expo-router';
import { useRef, useState } from 'react';
import { ActivityIndicator, KeyboardAvoidingView, Linking, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Ill } from '@/components/kit';
import { LoginCard } from '@/components/login-card';
import { Button } from '@/components/ui';
import { API_URL, api } from '@/lib/api';
import { km, money } from '@/lib/format';
import { getPushTokenQuick } from '@/lib/push';
import { colors, radius } from '@/lib/theme';
import type { ErrandPlace } from '@/lib/types';
import { useFetch } from '@/lib/useFetch';
import { useApp } from '@/state/app-state';

type Which = 'pickup' | 'dropoff';
type Quote = { price: number; km: number; eta_min: number | null; eta_max: number | null };

const KIND_EMOJI: Record<string, string> = { documentos: '📄', llaves: '🔑', paquete: '📦', regalo: '🎁', otro: '➕' };
const SIZE_EMOJI: Record<string, string> = { chico: '✉️', mediano: '🛍', grande: '📦' };

const labelOf = (a: Location.LocationGeocodedAddress | undefined, fallback: string) => {
  if (!a) return fallback;
  const street = [a.street, a.streetNumber].filter(Boolean).join(' ') || a.name;
  return [street, a.city || a.subregion].filter(Boolean).join(', ') || fallback;
};

/** Trappi Mandados: mandar algo de una dirección a otra con los repartidores de Trappi. El precio lo calcula el servidor. */
export default function ErrandScreen() {
  const insets = useSafeAreaInsets();
  const { location, account, rememberOrder } = useApp();
  const cfg = useFetch(() => api.errandsConfig(location), [location?.lat, location?.lng]);
  // tu ubicación y tu cuenta cargan un instante después: hasta que el cliente elija otra cosa, se usan esas
  const [chosenPickup, setPickup] = useState<ErrandPlace | null>(null);
  const pickup = chosenPickup ?? (location ? { lat: location.lat, lng: location.lng, address: location.label } : null);
  const [dropoff, setDropoff] = useState<ErrandPlace | null>(null);
  const [chosenEditing, setEditing] = useState<Which | null | 'auto'>('auto');
  const editing: Which | null = chosenEditing === 'auto' ? (dropoff ? null : pickup ? 'dropoff' : 'pickup') : chosenEditing;
  const [query, setQuery] = useState('');
  const [found, setFound] = useState<ErrandPlace[] | null>(null);
  const [pickupNote, setPickupNote] = useState('');
  const [dropoffNote, setDropoffNote] = useState('');
  const [kind, setKind] = useState('documentos');
  const [size, setSize] = useState('chico');
  const [what, setWhat] = useState('');
  const [chosenSender, setSender] = useState<{ name: string; phone: string } | null>(null);
  const sender = chosenSender ?? { name: [account?.first_name, account?.last_name].filter(Boolean).join(' '), phone: account?.phone || '' };
  const [recipient, setRecipient] = useState({ name: '', phone: '' });
  const [quote, setQuote] = useState<Quote | null>(null);
  const [pay, setPay] = useState<'efectivo' | 'mercadopago'>('efectivo');
  const [busy, setBusy] = useState<'gps' | 'search' | 'quote' | 'order' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [needLogin, setNeedLogin] = useState(false);

  // con las dos direcciones, el servidor calcula el precio con la tarifa de la flota
  const seq = useRef(0);
  const requestQuote = (a: ErrandPlace | null, b: ErrandPlace | null) => {
    setQuote(null);
    if (!a || !b) return;
    const n = ++seq.current;
    setBusy('quote'); setError(null);
    api.errandQuote(a, b)
      .then(q => { if (n === seq.current) setQuote(q); })
      .catch(e => { if (n === seq.current) setError(e instanceof Error ? e.message : 'No pudimos calcular el precio.'); })
      .finally(() => { if (n === seq.current) setBusy(null); });
  };

  const myLocation = async () => {
    setBusy('gps'); setError(null);
    try {
      const perm = await Location.requestForegroundPermissionsAsync();
      if (!perm.granted) { setError('Necesitamos tu ubicación para saber dónde retirar.'); return; }
      const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High });
      const addr = await Location.reverseGeocodeAsync(pos.coords).catch(() => []);
      pick({ lat: pos.coords.latitude, lng: pos.coords.longitude, address: labelOf(addr[0], 'Mi ubicación') });
    } catch {
      setError('No pudimos obtener tu ubicación. Activá el GPS y probá de nuevo.');
    } finally { setBusy(null); }
  };

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

  const pick = (p: ErrandPlace) => {
    if (editing === 'dropoff') { setDropoff(p); requestQuote(pickup, p); } else { setPickup(p); requestQuote(p, dropoff); }
    setEditing(editing === 'pickup' && !dropoff ? 'dropoff' : null);
    setQuery(''); setFound(null);
  };

  const confirm = async () => {
    if (!pickup || !dropoff || !quote) return;
    if (!account) { setNeedLogin(true); return; }
    setBusy('order'); setError(null);
    try {
      const pushToken = await getPushTokenQuick();
      const r = await api.errandCreate({
        pickup: { ...pickup, note: pickupNote.trim() }, dropoff: { ...dropoff, note: dropoffNote.trim() }, kind, size, what: what.trim(),
        sender, recipient, push_token: pushToken || '', platform: Platform.OS, payment_method: pay,
      });
      rememberOrder({ id: r.id, token: r.token, store_name: 'Trappi Mandados', created_at: new Date().toISOString(), fromAccount: true });
      router.replace({ pathname: '/order/[id]', params: { id: String(r.id), nuevo: '1' } });
      if (r.pay_path) Linking.openURL(API_URL + r.pay_path);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No pudimos pedir el mandado.');
    } finally { setBusy(null); }
  };

  const off = cfg.data && !cfg.data.enabled;
  const ready = !!quote && !!sender.name.trim() && sender.phone.replace(/\D/g, '').length >= 6 && !!recipient.name.trim()
    && recipient.phone.replace(/\D/g, '').length >= 6 && (kind !== 'otro' || what.trim().length >= 3);

  const placeRow = (which: Which) => {
    const p = which === 'pickup' ? pickup : dropoff;
    const on = editing === which;
    return (
      <Pressable style={st.place} onPress={() => { setEditing(which); setFound(null); setQuery(''); }} accessibilityRole="button"
        accessibilityLabel={which === 'pickup' ? 'Cambiar dónde se retira' : 'Cambiar dónde se entrega'}>
        <View style={which === 'pickup' ? st.dotA : st.dotB} />
        <View style={{ flex: 1 }}>
          <Text style={st.small}>{which === 'pickup' ? 'RETIRAR EN' : 'ENTREGAR EN'}</Text>
          <Text style={[st.placeText, !p && { color: colors.muted }]} numberOfLines={1}>{p?.address || (which === 'pickup' ? '¿Dónde lo retiramos?' : '¿A dónde lo llevamos?')}</Text>
        </View>
        <Ionicons name={on ? 'chevron-up' : 'pencil'} size={17} color={colors.brand} />
      </Pressable>
    );
  };

  return (
    <KeyboardAvoidingView style={{ flex: 1, backgroundColor: colors.bg }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={[st.top, { paddingTop: insets.top + 8 }]}>
        <Pressable onPress={() => router.back()} style={st.back} accessibilityLabel="Volver"><Ionicons name="arrow-back" size={22} color={colors.ink} /></Pressable>
        <Text style={st.h1}>Nuevo mandado</Text>
      </View>

      {needLogin ? (
        <ScrollView contentContainerStyle={{ padding: 16 }} keyboardShouldPersistTaps="handled">
          <LoginCard title="Entrá para mandar algo" text="El mandado queda a tu nombre y lo seguís en vivo. Te mandamos un código por email: sin contraseñas."
            onDone={() => setNeedLogin(false)} />
        </ScrollView>
      ) : off ? (
        <View style={st.offBox}>
          <Ill e="📦" size={64} />
          <Text style={st.h2}>Todavía no hay mandados en tu ciudad</Text>
          <Text style={[st.hint, { textAlign: 'center' }]}>Cuando los repartidores de Trappi lleguen a tu zona, vas a poder mandar lo que quieras desde acá.</Text>
        </View>
      ) : (
        <>
          <ScrollView contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: 140 }} keyboardShouldPersistTaps="handled">
            <View style={st.box}>
              {placeRow('pickup')}
              {editing === 'pickup' && (
                <View style={st.searchArea}>
                  <Pressable style={st.gps} onPress={myLocation}>
                    {busy === 'gps' ? <ActivityIndicator color={colors.brand} /> : <Ionicons name="locate" size={18} color={colors.brand} />}
                    <Text style={st.gpsText}>Usar mi ubicación</Text>
                  </Pressable>
                </View>
              )}
              <View style={st.sep} />
              {placeRow('dropoff')}
              {!!editing && (
                <View style={st.searchArea}>
                  <View style={st.searchRow}>
                    <TextInput value={query} onChangeText={setQuery} placeholder={editing === 'pickup' ? 'Calle y número de donde se retira' : 'Calle y número de entrega'}
                      placeholderTextColor={colors.muted} style={st.input} returnKeyType="search" onSubmitEditing={search} autoCorrect={false} />
                    {busy === 'search' ? <ActivityIndicator color={colors.brand} /> : (
                      <Pressable onPress={search} hitSlop={10} accessibilityLabel="Buscar dirección"><Ionicons name="search" size={20} color={colors.brand} /></Pressable>)}
                  </View>
                  {(found ?? []).map((p, i) => (
                    <Pressable key={i} style={st.row} onPress={() => pick(p)}>
                      <Ionicons name="location-outline" size={19} color={colors.ink} />
                      <Text style={st.rowText} numberOfLines={2}>{p.address}</Text>
                    </Pressable>
                  ))}
                </View>
              )}
            </View>

            <View style={st.card}>
              <Text style={st.h3}>¿Qué mandás?</Text>
              <View style={st.chips}>
                {(cfg.data?.kinds ?? []).map(k => (
                  <Pressable key={k.code} onPress={() => setKind(k.code)} style={[st.chip, kind === k.code && st.chipOn]} accessibilityRole="radio" accessibilityState={{ selected: kind === k.code }}>
                    <Text style={[st.chipText, kind === k.code && { color: '#fff' }]}>{KIND_EMOJI[k.code] ?? ''} {k.label.replace(/^\S+\s/, '')}</Text>
                  </Pressable>
                ))}
              </View>
              <TextInput value={what} onChangeText={setWhat} maxLength={200} placeholder={kind === 'otro' ? 'Contanos qué es' : 'Detalle (opcional): un sobre, una caja chica…'}
                placeholderTextColor={colors.muted} style={st.field} />
            </View>

            <View style={st.card}>
              <Text style={st.h3}>Tamaño</Text>
              <View style={{ flexDirection: 'row', gap: 8 }}>
                {(cfg.data?.sizes ?? []).map(s => {
                  const [name, sub] = s.label.split(' (');
                  return (
                    <Pressable key={s.code} onPress={() => setSize(s.code)} style={[st.size, size === s.code && st.sizeOn]} accessibilityRole="radio" accessibilityState={{ selected: size === s.code }}>
                      <Text style={{ fontSize: 24 }}>{SIZE_EMOJI[s.code] ?? '📦'}</Text>
                      <Text style={st.sizeName}>{name}</Text>
                      {!!sub && <Text style={st.sizeSub}>{sub.replace(')', '')}</Text>}
                    </Pressable>
                  );
                })}
              </View>
            </View>

            <View style={st.card}>
              <Text style={st.h3}>Quién lo entrega</Text>
              <View style={{ flexDirection: 'row', gap: 8 }}>
                <TextInput value={sender.name} onChangeText={v => setSender({ ...sender, name: v })} placeholder="Nombre" maxLength={80} placeholderTextColor={colors.muted} style={[st.field, { flex: 1 }]} />
                <TextInput value={sender.phone} onChangeText={v => setSender({ ...sender, phone: v })} placeholder="Teléfono" keyboardType="phone-pad" maxLength={30} placeholderTextColor={colors.muted} style={[st.field, { flex: 1 }]} />
              </View>
              <TextInput value={pickupNote} onChangeText={setPickupNote} maxLength={160} placeholder="Indicaciones para retirar: timbre, piso…" placeholderTextColor={colors.muted} style={st.field} />
              <Text style={[st.h3, { marginTop: 6 }]}>Quién lo recibe</Text>
              <View style={{ flexDirection: 'row', gap: 8 }}>
                <TextInput value={recipient.name} onChangeText={v => setRecipient({ ...recipient, name: v })} placeholder="Nombre" maxLength={80} placeholderTextColor={colors.muted} style={[st.field, { flex: 1 }]} />
                <TextInput value={recipient.phone} onChangeText={v => setRecipient({ ...recipient, phone: v })} placeholder="Teléfono" keyboardType="phone-pad" maxLength={30} placeholderTextColor={colors.muted} style={[st.field, { flex: 1 }]} />
              </View>
              <TextInput value={dropoffNote} onChangeText={setDropoffNote} maxLength={160} placeholder="Indicaciones para entregar: oficina, depto…" placeholderTextColor={colors.muted} style={st.field} />
            </View>

            {(cfg.data?.payments?.length ?? 0) > 1 && (
              <View style={st.card}>
                <Text style={st.h3}>¿Cómo pagás?</Text>
                <View style={{ flexDirection: 'row', gap: 8 }}>
                  {([['efectivo', '💵', 'Efectivo', 'al repartidor cuando lo entrega'], ['mercadopago', '💳', 'Mercado Pago', 'ahora, antes de que salga']] as const).map(([code, e, name, sub]) => (
                    <Pressable key={code} onPress={() => setPay(code)} style={[st.size, pay === code && st.sizeOn]} accessibilityRole="radio" accessibilityState={{ selected: pay === code }}>
                      <Text style={{ fontSize: 22 }}>{e}</Text>
                      <Text style={st.sizeName}>{name}</Text>
                      <Text style={st.sizeSub}>{sub}</Text>
                    </Pressable>
                  ))}
                </View>
              </View>
            )}

            <View style={st.safe}>
              <Ionicons name="shield-checkmark-outline" size={18} color={colors.good} />
              <Text style={st.safeText}><Text style={{ fontWeight: '800' }}>Entrega con código:</Text> quien recibe le dice al repartidor un código de 4 números. Sin código, no se entrega.</Text>
            </View>
            {!!cfg.data?.forbidden && <Text style={st.hint}>🚫 {cfg.data.forbidden}</Text>}
            {!!error && <Text style={st.error}>{error}</Text>}
          </ScrollView>

          <View style={[st.bottom, { paddingBottom: insets.bottom + 12 }]}>
            {busy === 'quote' ? <Text style={st.hint}>Calculando el precio…</Text> : quote ? (
              <View style={st.sumRow}>
                <Text style={st.hint}>{km(quote.km)}{quote.eta_min ? ` · llega en ~${quote.eta_max ?? quote.eta_min} min` : ''} · {pay === 'mercadopago' ? '💳 pagás ahora con Mercado Pago' : '💵 efectivo al entregar'}</Text>
              </View>
            ) : <Text style={st.hint}>Poné las dos direcciones para ver el precio.</Text>}
            <Button title={quote ? `Pedir repartidor · ${money(quote.price)}` : 'Pedir repartidor'} disabled={!ready} loading={busy === 'order'} onPress={confirm} />
          </View>
        </>
      )}
    </KeyboardAvoidingView>
  );
}

const st = StyleSheet.create({
  top: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 16, paddingBottom: 8, backgroundColor: colors.bg },
  back: { width: 40, height: 40, borderRadius: 20, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center' },
  h1: { fontSize: 24, fontWeight: '900', color: colors.ink, letterSpacing: -0.4 },
  h2: { fontSize: 20, fontWeight: '900', color: colors.ink, textAlign: 'center' },
  h3: { fontSize: 15, fontWeight: '800', color: colors.ink },
  box: { backgroundColor: '#fff', borderRadius: 20, paddingHorizontal: 14, paddingVertical: 4 },
  card: { backgroundColor: '#fff', borderRadius: 20, padding: 14, gap: 10 },
  place: { flexDirection: 'row', alignItems: 'center', gap: 12, minHeight: 58 },
  small: { fontSize: 10.5, fontWeight: '800', color: colors.muted, letterSpacing: 0.5 },
  placeText: { fontWeight: '800', color: colors.ink, fontSize: 15 },
  dotA: { width: 12, height: 12, borderRadius: 6, backgroundColor: colors.brand },
  dotB: { width: 12, height: 12, borderRadius: 3, backgroundColor: colors.ink },
  sep: { height: 1, backgroundColor: colors.line, marginLeft: 24 },
  searchArea: { paddingBottom: 10, gap: 6 },
  searchRow: { flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: colors.bg, borderRadius: 12, paddingHorizontal: 12 },
  input: { flex: 1, fontSize: 15, color: colors.ink, paddingVertical: 11 },
  gps: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 6 },
  gpsText: { color: colors.brand, fontWeight: '800' },
  row: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 8 },
  rowText: { flex: 1, fontWeight: '700', color: colors.ink },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  chip: { paddingHorizontal: 12, paddingVertical: 7, borderRadius: radius.pill, backgroundColor: colors.bg },
  chipOn: { backgroundColor: colors.ink },
  chipText: { fontWeight: '800', color: colors.ink, fontSize: 13 },
  field: { backgroundColor: colors.bg, borderRadius: 12, paddingHorizontal: 12, paddingVertical: 10, fontSize: 14.5, color: colors.ink },
  size: { flex: 1, alignItems: 'center', gap: 2, paddingVertical: 10, borderRadius: 14, backgroundColor: colors.bg, borderWidth: 2, borderColor: 'transparent' },
  sizeOn: { backgroundColor: colors.brandSoft, borderColor: colors.brand },
  sizeName: { fontWeight: '800', color: colors.ink, fontSize: 13 },
  sizeSub: { color: colors.muted, fontSize: 11, textAlign: 'center' },
  safe: { flexDirection: 'row', gap: 10, alignItems: 'center', backgroundColor: colors.goodSoft, padding: 12, borderRadius: radius.md },
  safeText: { flex: 1, color: '#14532D', fontSize: 13 },
  hint: { color: colors.muted, fontSize: 12.5 },
  error: { color: colors.bad, fontWeight: '700' },
  bottom: { position: 'absolute', left: 0, right: 0, bottom: 0, backgroundColor: '#fff', paddingHorizontal: 16, paddingTop: 10, gap: 8,
    borderTopLeftRadius: 22, borderTopRightRadius: 22, elevation: 12, shadowColor: '#000', shadowOpacity: 0.1, shadowRadius: 14 },
  sumRow: { flexDirection: 'row', alignItems: 'center' },
  offBox: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 30, gap: 10 },
});
