import Ionicons from '@expo/vector-icons/Ionicons';
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useMemo, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Carousel, ProductTile, StoreRow, Tile } from '@/components/market';
import { Empty, ErrorState, Loading } from '@/components/ui';
import { api } from '@/lib/api';
import { colors, radius } from '@/lib/theme';
import type { Product, Store } from '@/lib/types';
import { useFetch } from '@/lib/useFetch';
import { useApp } from '@/state/app-state';

const SORTS = [{ key: '', label: 'Recomendados' }, { key: 'cerca', label: 'Más cerca' }, { key: 'rapidos', label: 'Más rápidos' }, { key: 'envio', label: 'Envío más barato' }];

function Pill({ label, on, onPress, icon }: { label: string; on?: boolean; onPress: () => void; icon?: React.ComponentProps<typeof Ionicons>['name'] }) {
  return (
    <Pressable onPress={onPress} style={[st.pill, on && st.pillOn]} accessibilityRole="button" accessibilityState={{ selected: !!on }}>
      {icon && <Ionicons name={icon} size={17} color={on ? '#fff' : colors.ink} />}
      <Text style={[st.pillText, on && { color: '#fff' }]}>{label}</Text>
    </Pressable>
  );
}

export default function SearchScreen() {
  const insets = useSafeAreaInsets();
  const params = useLocalSearchParams<{ rubro?: string; rubroName?: string }>();
  const { location, cartCount } = useApp();
  const [q, setQ] = useState('');
  const [tab, setTab] = useState<'stores' | 'products'>('stores');
  const [sort, setSort] = useState(0);
  const [deals, setDeals] = useState(false);
  const [top, setTop] = useState(false);
  const [delivery, setDelivery] = useState(false);
  const [rubro, setRubro] = useState<{ id: number; name: string } | null>(null);
  const [found, setFound] = useState<{ stores: Store[]; products: Product[] } | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [attempt, setAttempt] = useState(0);

  // un rubro elegido desde el inicio
  const [seenRubro, setSeenRubro] = useState<string | undefined>(undefined);
  if (params.rubro !== seenRubro) {
    setSeenRubro(params.rubro);
    if (params.rubro) { setRubro({ id: Number(params.rubro), name: params.rubroName || 'Rubro' }); setQ(''); setTab('stores'); }
  }

  const home = useFetch(() => api.home(location), [location?.lat, location?.lng]);
  const byRubro = useFetch(() => (rubro ? api.stores(location, { category_id: rubro.id, sort: SORTS[sort].key || undefined, delivery }) : Promise.resolve(null)),
    [rubro?.id, location?.lat, location?.lng, sort, delivery]);

  // búsqueda con espera corta para no consultar en cada tecla
  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) return;
    let alive = true;
    const t = setTimeout(() => {
      setLoading(true);
      api.search(term, location)
        .then(r => { if (alive) { setFound(r); setFailed(null); } })
        .catch(e => { if (alive) setFailed(e.message); })
        .finally(() => { if (alive) setLoading(false); });
    }, 300);
    return () => { alive = false; clearTimeout(t); };
  }, [q, location, attempt]);

  const active = q.trim().length >= 2;
  const source = useMemo<{ stores: Store[]; products: Product[] } | null>(
    () => (active ? found : rubro ? { stores: byRubro.data?.stores ?? [], products: [] } : null), [active, found, rubro, byRubro.data]);
  const stores = useMemo(() => {
    let list = source?.stores ?? [];
    if (deals) list = list.filter(s => s.max_discount);
    if (top) list = list.filter(s => (s.rating ?? 0) >= 4.5);
    if (delivery) list = list.filter(s => s.delivery_enabled && s.coverage.covered !== false);
    const key = SORTS[sort].key;
    if (active && key === 'cerca') list = [...list].sort((a, b) => (a.coverage.distance_km ?? 99) - (b.coverage.distance_km ?? 99));
    if (active && key === 'rapidos') list = [...list].sort((a, b) => a.eta_min - b.eta_min);
    if (active && key === 'envio') list = [...list].sort((a, b) => (a.coverage.cost ?? a.delivery_cost) - (b.coverage.cost ?? b.delivery_cost));
    return list;
  }, [source, deals, top, delivery, sort, active]);
  const products = useMemo(() => (source?.products ?? []).filter(p => !deals || p.previous_price), [source, deals]);
  const productsOf = (slug: string) => products.filter(p => p.store?.slug === slug);
  const showing = active || !!rubro;

  return (
    <View style={{ flex: 1, backgroundColor: '#fff' }}>
      <View style={[st.top, { paddingTop: insets.top + 8 }]}>
        {(active || rubro) && <Pressable onPress={() => { setQ(''); setRubro(null); }} hitSlop={10} accessibilityLabel="Volver"><Ionicons name="chevron-back" size={28} color={colors.ink} /></Pressable>}
        <View style={st.box}>
          <TextInput value={q} onChangeText={v => { setQ(v); if (v) setRubro(null); }} placeholder={rubro ? `Buscar en ${rubro.name}` : 'Buscar comercios y platos'} placeholderTextColor={colors.muted}
            style={st.input} returnKeyType="search" autoCorrect={false} accessibilityLabel="Buscar" />
          {q ? <Pressable onPress={() => setQ('')} hitSlop={10} accessibilityLabel="Borrar"><Ionicons name="close" size={22} color={colors.ink} /></Pressable>
            : <Ionicons name="search" size={20} color={colors.ink} />}
        </View>
        <Pressable onPress={() => router.push('/cart')} hitSlop={10} accessibilityLabel={`Mi pedido, ${cartCount} productos`}>
          <Ionicons name="cart-outline" size={28} color={colors.ink} />
          {cartCount > 0 && <View style={st.badge}><Text style={st.badgeText}>{cartCount}</Text></View>}
        </Pressable>
      </View>

      {active && (
        <View style={st.tabs}>
          {(['stores', 'products'] as const).map(k => (
            <Pressable key={k} style={[st.tab, tab === k && st.tabOn]} onPress={() => setTab(k)}>
              <Text style={[st.tabText, tab === k && { color: colors.ink }]}>{k === 'stores' ? 'Comercios' : 'Productos'}</Text>
            </Pressable>
          ))}
        </View>
      )}

      <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ paddingBottom: 32 }}>
        {showing && (
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={st.pills}>
            <Pill label={SORTS[sort].label} icon="swap-vertical" on={sort > 0} onPress={() => setSort(i => (i + 1) % SORTS.length)} />
            <Pill label="Descuentos" icon="pricetag-outline" on={deals} onPress={() => setDeals(v => !v)} />
            <Pill label="4,5 o más" icon="star-outline" on={top} onPress={() => setTop(v => !v)} />
            <Pill label="Con envío" icon="bicycle-outline" on={delivery} onPress={() => setDelivery(v => !v)} />
          </ScrollView>
        )}

        {!showing && (
          <>
            <Text style={st.h2}>Explorá por rubro</Text>
            <View style={st.grid}>
              {(home.data?.store_categories ?? []).map(c => <Tile key={c.id} label={c.name} emoji={c.emoji} onPress={() => setRubro({ id: c.id, name: c.name })} />)}
            </View>
            {!home.data && home.loading && <Loading />}
          </>
        )}

        {active && loading && !found && <Loading />}
        {rubro && byRubro.loading && !byRubro.data && <Loading />}
        {active && failed && <ErrorState message={failed} onRetry={() => setAttempt(a => a + 1)} />}

        {showing && (
          <Text style={st.h2}>{active ? `Resultados para "${q.trim()}"` : rubro?.name}</Text>
        )}

        {showing && tab === 'stores' && stores.map(s => (
          <View key={s.id}>
            <StoreRow store={s} />
            {productsOf(s.slug).length > 0 && <Carousel gap={12}>{productsOf(s.slug).map(p => <ProductTile key={p.id} product={p} width={140} showStore={false} />)}</Carousel>}
          </View>
        ))}
        {active && tab === 'products' && (
          <View style={st.pgrid}>{products.map(p => <ProductTile key={p.id} product={p} width={160} />)}</View>
        )}
        {showing && !loading && !byRubro.loading && ((tab === 'stores' && !stores.length) || (active && tab === 'products' && !products.length)) && (
          <Empty emoji="🔎" title="No encontramos nada" text={active ? `Nada coincide con "${q.trim()}" y esos filtros. Probá con otra palabra.` : 'No hay comercios con esos filtros.'} />
        )}
      </ScrollView>
    </View>
  );
}

const st = StyleSheet.create({
  top: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 16, paddingBottom: 10, backgroundColor: '#fff' },
  box: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: '#F2F1F5', borderRadius: radius.pill, paddingHorizontal: 18, height: 50 },
  input: { flex: 1, fontSize: 16.5, color: colors.ink },
  badge: { position: 'absolute', top: -4, right: -6, minWidth: 18, height: 18, borderRadius: 9, backgroundColor: colors.brand, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 4 },
  badgeText: { color: '#fff', fontWeight: '800', fontSize: 11 },
  tabs: { flexDirection: 'row', borderBottomWidth: 1, borderBottomColor: colors.line },
  tab: { flex: 1, alignItems: 'center', paddingVertical: 14, borderBottomWidth: 3, borderBottomColor: 'transparent' },
  tabOn: { borderBottomColor: colors.ink },
  tabText: { fontSize: 17, fontWeight: '700', color: colors.muted },
  pills: { paddingHorizontal: 16, gap: 10, paddingVertical: 14 },
  pill: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 16, height: 44, borderRadius: radius.pill, backgroundColor: '#F2F1F5' },
  pillOn: { backgroundColor: colors.ink },
  pillText: { fontWeight: '700', color: colors.ink, fontSize: 15 },
  h2: { fontSize: 22, fontWeight: '800', color: colors.ink, paddingHorizontal: 16, marginTop: 14, marginBottom: 4, letterSpacing: -0.4 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 14, paddingHorizontal: 16, paddingTop: 12 },
  pgrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 14, paddingHorizontal: 16, paddingTop: 8 },
});
