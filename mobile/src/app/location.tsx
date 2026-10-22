import Ionicons from '@expo/vector-icons/Ionicons';
import * as Location from 'expo-location';
import { router } from 'expo-router';
import { useState } from 'react';
import { Alert, Linking, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

import { Button, s as ui } from '@/components/ui';
import { api } from '@/lib/api';
import { colors, radius } from '@/lib/theme';
import type { SavedAddress, UserLocation } from '@/lib/types';
import { useFetch } from '@/lib/useFetch';
import { useApp } from '@/state/app-state';

type Found = { latitude: number; longitude: number; label: string };

const labelOf = (a: Location.LocationGeocodedAddress | undefined, fallback: string) => {
  if (!a) return fallback;
  const street = [a.street, a.streetNumber].filter(Boolean).join(' ') || a.name;
  return [street, a.city || a.subregion].filter(Boolean).join(', ') || fallback;
};

async function ensurePermission(): Promise<'ok' | 'denied' | 'blocked'> {
  const current = await Location.getForegroundPermissionsAsync();
  if (current.granted) return 'ok';
  if (!current.canAskAgain) return 'blocked';
  const asked = await Location.requestForegroundPermissionsAsync();
  return asked.granted ? 'ok' : asked.canAskAgain ? 'denied' : 'blocked';
}

export default function LocationScreen() {
  const { location, setLocation, account } = useApp();
  // direcciones guardadas en la cuenta: las mismas que en la web
  const saved = useFetch(() => (account ? api.myAddresses().then(r => r.addresses) : Promise.resolve([] as SavedAddress[])), [account?.id]);
  const [label, setLabel] = useState('');
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState<'gps' | 'search' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [blocked, setBlocked] = useState(false);
  const [query, setQuery] = useState('');
  const [found, setFound] = useState<Found[] | null>(null);

  const done = (loc: UserLocation) => { setLocation(loc); router.back(); };

  const useGps = async () => {
    setBusy('gps'); setError(null); setBlocked(false);
    try {
      const perm = await ensurePermission();
      if (perm !== 'ok') { setBlocked(perm === 'blocked'); setError('Necesitamos permiso de ubicación. También podés buscar tu dirección abajo.'); return; }
      if (!(await Location.hasServicesEnabledAsync())) { setError('Activá la ubicación (GPS) del teléfono y probá de nuevo.'); return; }
      const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
      const { latitude, longitude } = pos.coords;
      const addr = await Location.reverseGeocodeAsync({ latitude, longitude }).catch(() => []);
      done({ lat: latitude, lng: longitude, label: labelOf(addr[0], 'Mi ubicación actual') });
    } catch {
      setError('No pudimos obtener tu ubicación. Probá de nuevo o buscá tu dirección.');
    } finally {
      setBusy(null);
    }
  };

  const search = async () => {
    const q = query.trim();
    if (q.length < 3) return;
    setBusy('search'); setError(null); setFound(null);
    try {
      // en Android el geocoder del sistema pide el permiso de ubicación
      await ensurePermission();
      const results = (await Location.geocodeAsync(q)).slice(0, 5);
      const labeled = await Promise.all(results.map(async r => {
        const addr = await Location.reverseGeocodeAsync(r).catch(() => []);
        return { latitude: r.latitude, longitude: r.longitude, label: labelOf(addr[0], q) };
      }));
      setFound(labeled);
      if (!labeled.length) setError('No encontramos esa dirección. Probá agregando la ciudad.');
    } catch {
      setError('No pudimos buscar esa dirección. Revisá tu conexión.');
    } finally {
      setBusy(null);
    }
  };

  const pick = (a: SavedAddress) => {
    if (a.lat != null && a.lng != null) return done({ lat: a.lat, lng: a.lng, label: a.address });
    setQuery(a.address);  // guardada sin el punto del mapa: se busca
  };
  const remove = (a: SavedAddress) => Alert.alert('Borrar dirección', `¿Borrar «${a.label}»?`, [
    { text: 'Cancelar', style: 'cancel' },
    { text: 'Borrar', style: 'destructive', onPress: () => { api.deleteAddress(a.id).then(() => saved.reload()).catch(e => setError(e.message)); } },
  ]);
  const saveCurrent = async (name: string) => {
    if (!location || !name.trim()) return;
    setSaving(true); setError(null);
    try {
      await api.saveAddress({ label: name.trim(), address: location.label, reference: null, lat: location.lat, lng: location.lng });
      setLabel(''); saved.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No se pudo guardar.');
    } finally {
      setSaving(false);
    }
  };
  const already = !!location && !!saved.data?.some(a => a.lat === location.lat && a.lng === location.lng);

  return (
    <ScrollView style={{ backgroundColor: colors.bg }} contentContainerStyle={{ padding: 16, gap: 12 }} keyboardShouldPersistTaps="handled">
      {!!saved.data?.length && (
        <>
          <Text style={[ui.h2, { fontSize: 16 }]}>Mis direcciones</Text>
          {saved.data.map(a => (
            <Pressable key={a.id} style={st.result} onPress={() => pick(a)} onLongPress={() => remove(a)} accessibilityHint="Mantené apretado para borrarla">
              <Ionicons name={a.icon === 'work' ? 'briefcase-outline' : a.icon === 'heart' ? 'heart-outline' : a.icon === 'pin' ? 'location-outline' : 'home-outline'} size={20} color={colors.brand} />
              <View style={{ flex: 1 }}>
                <Text style={{ color: colors.ink, fontWeight: '800' }}>{a.label}</Text>
                <Text style={ui.muted} numberOfLines={1}>{a.address}{a.reference ? ` · ${a.reference}` : ''}</Text>
              </View>
              <Pressable onPress={() => remove(a)} hitSlop={10} accessibilityLabel={`Borrar ${a.label}`}><Ionicons name="trash-outline" size={18} color={colors.muted} /></Pressable>
            </Pressable>
          ))}
        </>
      )}
      <Text style={ui.muted}>La usamos para mostrarte qué comercios llegan hasta vos y cuánto sale el envío. No la compartimos con nadie más que el comercio al que le pedís.</Text>
      <Button title="📍 Usar mi ubicación actual" loading={busy === 'gps'} disabled={busy === 'search'} onPress={useGps} />

      <Text style={[ui.h2, { fontSize: 16, marginTop: 8 }]}>O buscá tu dirección</Text>
      <View style={st.box}>
        <Ionicons name="search" size={18} color={colors.muted} />
        <TextInput value={query} onChangeText={setQuery} placeholder="Ej: San Martín 450, Rosario" placeholderTextColor={colors.muted} style={st.input}
          returnKeyType="search" onSubmitEditing={search} autoCorrect={false} />
      </View>
      <Button title="Buscar" variant="secondary" loading={busy === 'search'} disabled={query.trim().length < 3 || busy === 'gps'} onPress={search} />

      {error && (
        <View style={st.error}>
          <Text style={{ color: colors.bad, fontWeight: '700' }}>{error}</Text>
          {blocked && <Pressable onPress={() => Linking.openSettings()}><Text style={{ color: colors.brand, fontWeight: '800', marginTop: 6 }}>Abrir ajustes</Text></Pressable>}
        </View>
      )}

      {found?.map((f, i) => (
        <Pressable key={i} style={st.result} onPress={() => done({ lat: f.latitude, lng: f.longitude, label: f.label })}>
          <Ionicons name="location-outline" size={20} color={colors.brand} />
          <Text style={{ flex: 1, color: colors.ink, fontWeight: '600' }}>{f.label}</Text>
          <Ionicons name="chevron-forward" size={18} color={colors.muted} />
        </Pressable>
      ))}

      {location && (
        <View style={st.current}>
          <Text style={ui.muted}>Ubicación guardada</Text>
          <Text style={{ color: colors.ink, fontWeight: '700' }}>{location.label}</Text>
          {!!account && !already && (
            <View style={{ marginTop: 8, gap: 8 }}>
              <Text style={{ color: colors.ink, fontWeight: '700' }}>Guardala para la próxima</Text>
              <View style={{ flexDirection: 'row', gap: 8, flexWrap: 'wrap' }}>
                {['Casa', 'Trabajo'].map(n => (
                  <Pressable key={n} disabled={saving} onPress={() => saveCurrent(n)} style={st.chip}><Text style={st.chipText}>{n === 'Casa' ? '🏠' : '💼'} {n}</Text></Pressable>
                ))}
              </View>
              <View style={[st.box, { borderRadius: radius.sm }]}>
                <TextInput value={label} onChangeText={setLabel} placeholder="Otro nombre (ej. Lo de mamá)" placeholderTextColor={colors.muted} style={st.input} maxLength={40}
                  returnKeyType="done" onSubmitEditing={() => saveCurrent(label)} />
                {!!label.trim() && <Pressable onPress={() => saveCurrent(label)} disabled={saving}><Text style={{ color: colors.brand, fontWeight: '800' }}>Guardar</Text></Pressable>}
              </View>
            </View>
          )}
          <Pressable onPress={() => { setLocation(null); router.back(); }}><Text style={{ color: colors.bad, fontWeight: '700', marginTop: 6 }}>Borrar ubicación</Text></Pressable>
        </View>
      )}
    </ScrollView>
  );
}

const st = StyleSheet.create({
  box: { flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: '#fff', borderRadius: radius.pill, paddingHorizontal: 16, borderWidth: 1, borderColor: colors.line },
  input: { flex: 1, paddingVertical: 13, fontSize: 16, color: colors.ink },
  error: { padding: 12, borderRadius: radius.sm, backgroundColor: colors.badSoft },
  result: { flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: '#fff', padding: 14, borderRadius: radius.md, borderWidth: 1, borderColor: colors.line },
  chip: { paddingHorizontal: 14, paddingVertical: 9, borderRadius: 99, borderWidth: 1.5, borderColor: colors.line, backgroundColor: '#fff' },
  chipText: { fontWeight: '800', color: colors.ink },
  current: { marginTop: 8, padding: 14, borderRadius: radius.md, backgroundColor: '#fff', borderWidth: 1, borderColor: colors.line, gap: 2 },
});
