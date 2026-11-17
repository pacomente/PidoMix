import Ionicons from '@expo/vector-icons/Ionicons';
import { router, Stack, useLocalSearchParams } from 'expo-router';
import { setStatusBarStyle } from 'expo-status-bar';
import { useEffect, useMemo, useState } from 'react';
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { StoreRow } from '@/components/market';
import { Empty, ErrorState, Loading } from '@/components/ui';
import { api } from '@/lib/api';
import { colors, radius } from '@/lib/theme';
import { useFetch } from '@/lib/useFetch';
import { useApp } from '@/state/app-state';

type Filter = 'open' | 'free' | 'near' | 'deals' | 'top';
/** cada rubro con su frase (el súper arranca mostrando el envío gratis) */
const TAGLINE: Record<string, string> = {
  super: 'Lo de todos los días, sin salir de casa', carniceria: 'Cortes del día, por kilo', verduleria: 'Fresco, del día',
  kiosco: 'Para el antojo de cualquier hora', farmacia: 'Lo que necesitás, rápido', bebidas: 'Frías, a domicilio', heladeria: 'Frío y rico', restaurante: 'Lo mejor de tu zona',
};

/** Página de un rubro: portada con su color y emoji, filtros propios y los locales. */
export default function RubroScreen() {
  const { id, name, emoji, accent, key } = useLocalSearchParams<{ id: string; name?: string; emoji?: string; accent?: string; key?: string }>();
  const insets = useSafeAreaInsets();
  const { location } = useApp();
  const color = accent || colors.brand;
  const [on, setOn] = useState<Filter[]>(key === 'super' ? ['free'] : []);
  const res = useFetch(() => api.stores(location, { category_id: Number(id), sort: on.includes('near') ? 'cerca' : undefined }), [id, location?.lat, location?.lng, on.includes('near')]);
  useEffect(() => { setStatusBarStyle('light'); return () => setStatusBarStyle('dark'); }, []);

  const stores = useMemo(() => (res.data?.stores ?? []).filter(s =>
    (!on.includes('open') || s.is_open) && (!on.includes('deals') || s.max_discount || s.coupon) && (!on.includes('top') || (s.rating ?? 0) >= 4.5)
    && (!on.includes('free') || (s.delivery_enabled && s.coverage.cost === 0))), [res.data, on]);
  const toggle = (f: Filter) => setOn(cur => (cur.includes(f) ? cur.filter(x => x !== f) : [...cur, f]));
  const filters: [Filter, string][] = [['free', '🛵 Envío gratis'], ['open', '🟢 Abiertos'], ['near', '📍 Más cerca'], ['deals', '🏷️ Con descuento'], ['top', '⭐ 4,5 o más']];

  return (
    <View style={{ flex: 1, backgroundColor: '#fff' }}>
      <Stack.Screen options={{ headerShown: false }} />
      <ScrollView contentContainerStyle={{ paddingBottom: 30 }} refreshControl={<RefreshControl refreshing={res.refreshing} onRefresh={res.refresh} tintColor={color} />}>
        <View style={[st.cover, { backgroundColor: color, paddingTop: insets.top + 8 }]}>
          <View style={st.glow} />
          <Pressable onPress={() => (router.canGoBack() ? router.back() : router.replace('/'))} style={st.back} accessibilityLabel="Volver"><Ionicons name="arrow-back" size={22} color={colors.ink} /></Pressable>
          <Text style={st.emoji}>{emoji || '🏪'}</Text>
          <Text style={st.title}>{name || 'Rubro'}</Text>
          <Text style={st.sub}>{TAGLINE[key || ''] || 'Los locales de tu zona'}{res.data ? ` · ${res.data.stores.length} ${res.data.stores.length === 1 ? 'local' : 'locales'}` : ''}</Text>
        </View>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={st.filters}>
          {filters.map(([f, label]) => (
            <Pressable key={f} onPress={() => toggle(f)} style={[st.filter, on.includes(f) && { backgroundColor: color, borderColor: color }]} accessibilityRole="checkbox" accessibilityState={{ checked: on.includes(f) }}>
              <Text style={[st.filterText, on.includes(f) && { color: '#fff' }]}>{label}</Text>
            </Pressable>
          ))}
        </ScrollView>
        {res.loading && !res.data ? <Loading /> : res.error && !res.data ? <ErrorState message={res.error} onRetry={res.reload} />
          : stores.length ? stores.map(s => <StoreRow key={s.id} store={s} />)
          : <Empty emoji={emoji || '🔎'} title="No hay locales con esos filtros" text="Probá sacando alguno." />}
      </ScrollView>
    </View>
  );
}

const st = StyleSheet.create({
  cover: { paddingHorizontal: 18, paddingBottom: 22, borderBottomLeftRadius: 28, borderBottomRightRadius: 28, overflow: 'hidden' },
  glow: { position: 'absolute', right: -60, top: -40, width: 240, height: 240, borderRadius: 120, backgroundColor: '#fff', opacity: 0.16 },
  back: { width: 42, height: 42, borderRadius: 21, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center' },
  emoji: { position: 'absolute', right: 18, bottom: 14, fontSize: 92 },
  title: { color: '#fff', fontSize: 30, fontWeight: '900', letterSpacing: -0.8, marginTop: 36 },
  sub: { color: 'rgba(255,255,255,.88)', fontSize: 14, fontWeight: '600', marginTop: 4, marginRight: 110 },
  filters: { paddingHorizontal: 16, paddingVertical: 14, gap: 8 },
  filter: { paddingHorizontal: 14, height: 40, borderRadius: radius.pill, borderWidth: 1.5, borderColor: colors.line, backgroundColor: '#fff', justifyContent: 'center' },
  filterText: { fontWeight: '800', color: colors.ink, fontSize: 14 },
});
