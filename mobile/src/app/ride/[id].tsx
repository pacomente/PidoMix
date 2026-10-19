import Ionicons from '@expo/vector-icons/Ionicons';
import { Stack, router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { ActivityIndicator, Alert, AppState, Linking, Pressable, ScrollView, Share, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { RideMap } from '@/components/ride-map';
import { Button, ErrorState, Loading } from '@/components/ui';
import { api } from '@/lib/api';
import { km, money, timeOf } from '@/lib/format';
import { colors, radius } from '@/lib/theme';
import type { Ride } from '@/lib/types';
import { useFetch } from '@/lib/useFetch';

const DEFAULT_MAP = 'https://tiles.openfreemap.org/styles/liberty';
const POLL_MS = 5000;
const ACTIVE = ['buscando', 'asignado', 'en_puerta', 'en_viaje'];

function banner(r: Ride): { title: string; sub: string } {
  const eta = r.tracking?.eta_min;
  switch (r.status) {
    case 'buscando': return { title: 'Buscando conductor', sub: `Le avisamos a los conductores de ${r.company.name}` };
    case 'asignado': return { title: eta ? `Llega en ${eta} min` : 'Tu conductor va en camino', sub: `Esperalo en ${r.origin.address?.split(',')[0] || 'tu ubicación'}` };
    case 'en_puerta': return { title: 'Tu conductor llegó', sub: 'Decile el PIN al subir' };
    case 'en_viaje': return { title: eta ? `Llegás en ${eta} min` : 'En viaje', sub: r.dest.address?.split(',')[0] || 'Destino' };
    default: return { title: r.label, sub: '' };
  }
}

function Stars({ value, onChange }: { value: number; onChange: (n: number) => void }) {
  return (
    <View style={{ flexDirection: 'row', justifyContent: 'center', gap: 10, marginTop: 12 }}>
      {[1, 2, 3, 4, 5].map(n => (
        <Pressable key={n} onPress={() => onChange(n)} hitSlop={6} accessibilityLabel={`${n} estrellas`}>
          <Ionicons name={n <= value ? 'star' : 'star-outline'} size={36} color={n <= value ? colors.star : '#D5D0DF'} />
        </Pressable>
      ))}
    </View>
  );
}

/** El viaje en curso: conductor, patente, PIN y mapa en vivo. Al llegar, el recibo y la calificación. */
export default function RideDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const insets = useSafeAreaInsets();
  const res = useFetch(() => api.ride(Number(id)).then(r => r.ride), [id]);
  const cfg = useFetch(() => api.config(), []);
  const [busy, setBusy] = useState(false);
  const [stars, setStars] = useState(0);
  const [tags, setTags] = useState<string[]>([]);
  const r = res.data;
  const active = !!r && ACTIVE.includes(r.status);

  useEffect(() => {
    if (!active) return;
    const timer = setInterval(res.refresh, POLL_MS);
    const sub = AppState.addEventListener('change', s => s === 'active' && res.refresh());
    return () => { clearInterval(timer); sub.remove(); };
  }, [active]); // eslint-disable-line react-hooks/exhaustive-deps

  if (res.loading && !r) return <Loading />;
  if (!r) return <ErrorState message={res.error || 'No encontramos el viaje.'} onRetry={res.reload} />;

  const cancel = () => Alert.alert('¿Cancelar el viaje?', r.status === 'buscando' ? 'Todavía no hay conductor asignado.' : 'El conductor ya va en camino.', [
    { text: 'No', style: 'cancel' },
    { text: 'Sí, cancelar', style: 'destructive', onPress: async () => {
      setBusy(true);
      try { res.setData((await api.rideCancel(r.id)).ride); } catch (e) { Alert.alert('No se pudo cancelar', e instanceof Error ? e.message : ''); } finally { setBusy(false); }
    } },
  ]);
  const share = () => Share.share({ message: `Estoy viajando con ${r.company.name}${r.driver ? ` · ${r.driver.name}, ${[r.driver.car_model, r.driver.plate].filter(Boolean).join(' ')}` : ''} hacia ${r.dest.address || 'mi destino'}. Viaje pedido por Trappi.` });
  const safety = () => Alert.alert('Seguridad', 'Si estás en peligro llamá al 911. También podés llamar a la base de la empresa.', [
    { text: 'Llamar al 911', style: 'destructive', onPress: () => Linking.openURL('tel:911') },
    ...(r.company.phone ? [{ text: `Llamar a ${r.company.name}`, onPress: () => Linking.openURL(`tel:${r.company.phone}`) }] : []),
    { text: 'Cerrar', style: 'cancel' as const },
  ]);
  const rate = async () => {
    setBusy(true);
    try { res.setData((await api.rideRate(r.id, stars, tags, '')).ride); } catch (e) { Alert.alert('No se pudo enviar', e instanceof Error ? e.message : ''); } finally { setBusy(false); }
  };

  // ---------- terminado: recibo y calificación ----------
  if (r.status === 'finalizado') {
    return (
      <ScrollView style={{ backgroundColor: colors.bg }} contentContainerStyle={{ padding: 18, paddingTop: insets.top + 24, gap: 14 }}>
        <Stack.Screen options={{ headerShown: false }} />
        <View style={{ alignItems: 'center' }}>
          <View style={st.okIco}><Ionicons name="checkmark" size={34} color={colors.good} /></View>
          <Text style={st.bigTitle}>Llegaste</Text>
          <Text style={st.muted}>{r.dest.address?.split(',')[0]} · {timeOf(r.finished_at)}</Text>
        </View>
        <View style={st.card}>
          <View style={st.between}><Text style={st.muted}>Total</Text><Text style={st.total}>{money(r.total)}</Text></View>
          <View style={st.hr} />
          <View style={st.between}><Text style={st.muted}>Viaje · {km(r.km)}</Text><Text style={st.ink}>{money(r.price)}</Text></View>
          {r.wait_charge > 0 && <View style={st.between}><Text style={st.muted}>Espera</Text><Text style={st.ink}>{money(r.wait_charge)}</Text></View>}
          <View style={st.between}><Text style={st.muted}>Pagado</Text><Text style={st.ink}>💵 Efectivo</Text></View>
          <View style={st.between}><Text style={st.muted}>Empresa</Text><Text style={st.ink}>{r.company.name}</Text></View>
        </View>
        {r.can_rate ? (
          <View style={[st.card, { alignItems: 'center' }]}>
            <Text style={[st.ink, { fontSize: 17, textAlign: 'center' }]}>¿Cómo estuvo tu viaje{r.driver ? ` con ${r.driver.name}` : ''}?</Text>
            <Stars value={stars} onChange={setStars} />
            <View style={st.tags}>
              {r.rating_tags.map(t => {
                const on = tags.includes(t);
                return <Pressable key={t} onPress={() => setTags(on ? tags.filter(x => x !== t) : [...tags, t])} style={[st.tag, on && st.tagOn]}><Text style={[st.tagText, on && { color: colors.brand }]}>{t}</Text></Pressable>;
              })}
            </View>
          </View>
        ) : r.rating ? <View style={[st.card, { alignItems: 'center' }]}><Text style={st.muted}>Calificaste este viaje con {r.rating} ★. ¡Gracias!</Text></View> : null}
        {r.can_rate && <Button title="Enviar calificación" disabled={!stars} loading={busy} onPress={rate} />}
        <Button title="Volver al inicio" variant="ghost" onPress={() => router.replace('/')} />
      </ScrollView>
    );
  }

  // ---------- cancelado o sin conductor ----------
  if (!active) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.bg, padding: 24, justifyContent: 'center', gap: 12 }}>
        <Stack.Screen options={{ title: 'Viaje' }} />
        <Ionicons name={r.status === 'sin_conductor' ? 'car-outline' : 'close-circle-outline'} size={54} color={colors.muted} style={{ alignSelf: 'center' }} />
        <Text style={[st.bigTitle, { textAlign: 'center' }]}>{r.label}</Text>
        {!!r.cancel_reason && <Text style={[st.muted, { textAlign: 'center' }]}>{r.cancel_reason}</Text>}
        <Button title="Pedir otro viaje" onPress={() => router.replace('/ride')} style={{ marginTop: 10 }} />
        <Button title="Volver al inicio" variant="ghost" onPress={() => router.replace('/')} />
      </View>
    );
  }

  // ---------- en curso ----------
  const b = banner(r);
  const d = r.driver;
  return (
    <View style={{ flex: 1 }}>
      <Stack.Screen options={{ headerShown: false }} />
      <RideMap mapStyle={cfg.data?.map_style || DEFAULT_MAP} style={StyleSheet.absoluteFill} vehicle={r.vehicle} fitKey={r.status}
        origin={r.status === 'en_viaje' ? null : r.origin} dest={r.status === 'en_viaje' || r.status === 'buscando' ? r.dest : null} driver={r.tracking?.driver ?? null} />
      <View style={[st.top, { top: insets.top + 10 }]}>
        <Pressable onPress={() => router.replace('/')} hitSlop={8} accessibilityLabel="Volver al inicio"><Ionicons name="chevron-back" size={22} color="#fff" /></Pressable>
        <View style={{ flex: 1 }}><Text style={st.topTitle}>{b.title}</Text>{!!b.sub && <Text style={st.topSub} numberOfLines={1}>{b.sub}</Text>}</View>
        {r.status === 'buscando' && <ActivityIndicator color="#fff" />}
      </View>

      <View style={[st.sheet, { paddingBottom: insets.bottom + 14 }]}>
        <View style={st.grab} />
        {r.status === 'buscando' ? (
          <View style={{ gap: 6 }}>
            <Text style={st.h2}>Buscando conductor…</Text>
            <Text style={st.muted}>{r.company.name} · {r.vehicle === 'moto' ? 'Moto' : 'Auto'} · {money(r.price)} en efectivo</Text>
          </View>
        ) : d && (
          <View style={st.driverRow}>
            <View style={st.avatar}><Text style={st.avatarText}>{d.name[0]}</Text></View>
            <View style={{ flex: 1 }}>
              <Text style={st.driverName}>{d.name}</Text>
              <Text style={st.muted}>{d.rating ? `★ ${d.rating.toFixed(1).replace('.', ',')} · ` : ''}{r.company.name}</Text>
            </View>
            <View style={{ alignItems: 'flex-end', gap: 4 }}>
              {!!d.car_model && <Text style={[st.ink, { fontSize: 13 }]}>{d.car_model}</Text>}
              {!!d.plate && <View style={st.plate}><Text style={st.plateText}>{d.plate}</Text></View>}
            </View>
          </View>
        )}

        {!!r.pin && (
          <View style={st.pinBox}>
            <View style={{ flex: 1 }}><Text style={st.ink}>PIN del viaje</Text><Text style={st.muted}>Decíselo al chofer cuando subas</Text></View>
            <Text style={st.pin}>{r.pin.split('').join(' ')}</Text>
          </View>
        )}

        {r.status !== 'buscando' && (
          <View style={st.actions}>
            {!!d?.phone && <Pressable style={st.action} onPress={() => Linking.openURL(`tel:${d.phone}`)}><Ionicons name="call-outline" size={20} color={colors.ink} /><Text style={st.actionText}>Llamar</Text></Pressable>}
            <Pressable style={st.action} onPress={share}><Ionicons name="share-social-outline" size={20} color={colors.ink} /><Text style={st.actionText}>Compartir</Text></Pressable>
            <Pressable style={st.action} onPress={safety}><Ionicons name="shield-outline" size={20} color={colors.bad} /><Text style={[st.actionText, { color: colors.bad }]}>Seguridad</Text></Pressable>
          </View>
        )}
        <View style={[st.between, { marginTop: 10 }]}>
          <Text style={st.muted} numberOfLines={1}>{r.dest.address?.split(',')[0] || 'Destino'}</Text>
          <Text style={st.ink}>{money(r.price)} · efectivo</Text>
        </View>
        {r.can_cancel && <Pressable onPress={cancel} disabled={busy} style={{ alignSelf: 'center', marginTop: 12 }}><Text style={{ color: colors.bad, fontWeight: '800' }}>Cancelar viaje</Text></Pressable>}
      </View>
    </View>
  );
}

const st = StyleSheet.create({
  top: { position: 'absolute', left: 16, right: 16, flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: '#17112B', borderRadius: radius.md, paddingHorizontal: 14, paddingVertical: 12, elevation: 6 },
  topTitle: { color: '#fff', fontWeight: '800', fontSize: 16 },
  topSub: { color: '#CFC8E2', fontSize: 12.5, marginTop: 1 },
  sheet: { position: 'absolute', left: 0, right: 0, bottom: 0, backgroundColor: '#fff', borderTopLeftRadius: 26, borderTopRightRadius: 26, paddingHorizontal: 18, paddingTop: 8, elevation: 16, shadowColor: '#000', shadowOpacity: 0.12, shadowRadius: 18 },
  grab: { width: 40, height: 5, borderRadius: 3, backgroundColor: colors.line, alignSelf: 'center', marginBottom: 14 },
  h2: { fontSize: 20, fontWeight: '800', color: colors.ink },
  muted: { color: colors.muted, fontSize: 13.5 },
  ink: { color: colors.ink, fontWeight: '800' },
  between: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 10 },
  driverRow: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  avatar: { width: 52, height: 52, borderRadius: 26, backgroundColor: colors.brandSoft, alignItems: 'center', justifyContent: 'center' },
  avatarText: { color: colors.brand, fontWeight: '900', fontSize: 20 },
  driverName: { fontWeight: '800', fontSize: 18, color: colors.ink },
  plate: { borderWidth: 2, borderColor: colors.ink, borderRadius: 6, paddingHorizontal: 8, paddingVertical: 2 },
  plateText: { fontWeight: '900', letterSpacing: 2, color: colors.ink, fontSize: 13 },
  pinBox: { flexDirection: 'row', alignItems: 'center', backgroundColor: colors.brandSoft, borderRadius: radius.md, padding: 14, marginTop: 14 },
  pin: { fontSize: 28, fontWeight: '900', color: colors.brand, letterSpacing: 2 },
  actions: { flexDirection: 'row', gap: 10, marginTop: 14 },
  action: { flex: 1, alignItems: 'center', gap: 4, paddingVertical: 12, borderRadius: radius.md, backgroundColor: colors.bg },
  actionText: { fontWeight: '800', color: colors.ink, fontSize: 13 },
  okIco: { width: 64, height: 64, borderRadius: 32, backgroundColor: colors.goodSoft, alignItems: 'center', justifyContent: 'center', marginBottom: 10 },
  bigTitle: { fontSize: 28, fontWeight: '800', color: colors.ink },
  card: { backgroundColor: '#fff', borderRadius: radius.lg, padding: 16, gap: 8, borderWidth: 1, borderColor: colors.line },
  total: { fontSize: 28, fontWeight: '900', color: colors.ink },
  hr: { height: 1, backgroundColor: colors.line, marginVertical: 4 },
  tags: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, justifyContent: 'center', marginTop: 12 },
  tag: { paddingHorizontal: 12, paddingVertical: 7, borderRadius: radius.pill, backgroundColor: colors.bg },
  tagOn: { backgroundColor: colors.brandSoft },
  tagText: { fontWeight: '700', color: colors.ink, fontSize: 13 },
});
