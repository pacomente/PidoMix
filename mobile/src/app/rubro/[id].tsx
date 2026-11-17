import Ionicons from '@expo/vector-icons/Ionicons';
import { router, Stack, useLocalSearchParams } from 'expo-router';
import { setStatusBarStyle } from 'expo-status-bar';
import { useEffect, useMemo, useState } from 'react';
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Ill, RubroCover } from '@/components/kit';
import { BigStoreCard } from '@/components/store-card';
import { Empty, ErrorState, Loading } from '@/components/ui';
import { api } from '@/lib/api';
import { colors } from '@/lib/theme';
import { useFetch } from '@/lib/useFetch';
import { useApp } from '@/state/app-state';

type Filter = 'all' | 'free' | 'kg' | 'open' | 'deals';
/** cada rubro con su frase */
const TAGLINE: Record<string, string> = {
  super: 'comprás todo en un pedido', carniceria: 'cortes del día, por kilo', verduleria: 'fresco, del día', kiosco: 'para el antojo de cualquier hora',
  farmacia: 'lo que necesitás, rápido', bebidas: 'frías, a domicilio', heladeria: 'frío y rico', restaurante: 'lo mejor de tu zona',
};

/** Página de un rubro: portada con su degradado e ilustraciones, filtros propios y los locales con su portada. */
export default function RubroScreen() {
  const { id, name, emoji, key } = useLocalSearchParams<{ id: string; name?: string; emoji?: string; key?: string }>();
  const insets = useSafeAreaInsets();
  const { location } = useApp();
  const [f, setF] = useState<Filter>('all');
  const res = useFetch(() => api.stores(location, { category_id: Number(id) }), [id, location?.lat, location?.lng]);
  useEffect(() => { setStatusBarStyle('light'); return () => setStatusBarStyle('dark'); }, []);

  const all = useMemo(() => res.data?.stores ?? [], [res.data]);
  const stores = useMemo(() => all.filter(s => f === 'all' || (f === 'free' && s.delivery_enabled && (s.coverage.cost === 0 || !!s.free_shipping_from))
    || (f === 'kg' && s.sells_by_weight) || (f === 'open' && s.is_open) || (f === 'deals' && (s.max_discount || s.coupon))), [all, f]);
  // los filtros propios del rubro: en súper y carnicería, «Venden por kg»; en todos, envío gratis
  const filters: [Filter, string, string][] = [['all', '', 'Todos'], ['free', '🛵', 'Envío gratis'],
    ...(['super', 'carniceria', 'verduleria', 'fiambreria'].includes(key || '') || all.some(s => s.sells_by_weight) ? [['kg', '⚖', 'Venden por kg'] as [Filter, string, string]] : []),
    ['open', '✅', 'Abiertos'], ['deals', '🏷', 'Con descuento']];

  return (
    <View style={{ flex: 1, backgroundColor: colors.bg }}>
      <Stack.Screen options={{ headerShown: false }} />
      <ScrollView contentContainerStyle={{ paddingBottom: 30 }} refreshControl={<RefreshControl refreshing={res.refreshing} onRefresh={res.refresh} tintColor={colors.brand} />}>
        <RubroCover rubro={key} emoji={emoji} big={70} style={[st.cover, { paddingTop: insets.top + 8 }]}>
          <View style={st.top}>
            <Pressable onPress={() => (router.canGoBack() ? router.back() : router.replace('/'))} style={st.round} accessibilityLabel="Volver"><Ionicons name="chevron-back" size={22} color={colors.ink} /></Pressable>
            <Pressable onPress={() => router.navigate('/search')} style={st.round} accessibilityLabel="Buscar"><Ill e="🔍" size={20} /></Pressable>
          </View>
          <Text style={st.title}>{name || 'Rubro'}</Text>
          <Text style={st.sub}>{res.data ? `${all.length} cerca tuyo · ` : ''}{TAGLINE[key || ''] || 'los locales de tu zona'}</Text>
        </RubroCover>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={st.filters}>
          {filters.map(([k, e, label]) => (
            <Pressable key={k} onPress={() => setF(k)} style={[st.filter, f === k && st.filterOn]} accessibilityRole="radio" accessibilityState={{ checked: f === k }}>
              {!!e && <Ill e={e} size={18} />}<Text style={[st.filterText, f === k && { color: '#fff' }]}>{label}</Text>
            </Pressable>
          ))}
        </ScrollView>
        {res.loading && !res.data ? <Loading /> : res.error && !res.data ? <ErrorState message={res.error} onRetry={res.reload} />
          : stores.length ? stores.map(s => <BigStoreCard key={s.id} store={s} />)
          : <Empty emoji={emoji || '🔎'} title="No hay locales con ese filtro" text="Probá con otro." />}
      </ScrollView>
    </View>
  );
}

const st = StyleSheet.create({
  cover: { paddingHorizontal: 18, paddingBottom: 22, minHeight: 200, borderBottomLeftRadius: 28, borderBottomRightRadius: 28 },
  top: { flexDirection: 'row', justifyContent: 'space-between' },
  round: { width: 42, height: 42, borderRadius: 21, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center' },
  title: { color: '#fff', fontSize: 31, fontWeight: '900', letterSpacing: -0.9, marginTop: 30 },
  sub: { color: 'rgba(255,255,255,.92)', fontSize: 14.5, fontWeight: '600', marginTop: 4, marginRight: 130 },
  filters: { paddingHorizontal: 16, paddingVertical: 14, gap: 8 },
  filter: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 14, height: 40, borderRadius: 99, backgroundColor: '#fff', borderWidth: 1, borderColor: colors.line },
  filterOn: { backgroundColor: colors.ink, borderColor: colors.ink },
  filterText: { fontWeight: '800', color: colors.ink, fontSize: 14 },
});
