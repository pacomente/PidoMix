import Ionicons from '@expo/vector-icons/Ionicons';
import { Image } from 'expo-image';
import { router } from 'expo-router';
import { useEffect, useMemo, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Ill } from '@/components/kit';
import { openRubro } from '@/components/market';
import { BigStoreCard, shipText, StoreBadge } from '@/components/store-card';
import { Empty, ErrorState, Loading } from '@/components/ui';
import { api } from '@/lib/api';
import { money } from '@/lib/format';
import { colors } from '@/lib/theme';
import type { Product, Store } from '@/lib/types';
import { useFetch } from '@/lib/useFetch';
import { useApp } from '@/state/app-state';

type Mode = 'products' | 'stores' | 'cheap' | 'fast';
const HINTS = ['Tomate', 'Coca Cola', 'Nalga', 'Pan', 'Ibuprofeno', 'Helado'];

/** Buscar en todos los locales: el producto agrupado por comercio, con el precio (por kg) para comparar. */
export default function SearchScreen() {
  const insets = useSafeAreaInsets();
  const { location } = useApp();
  const [q, setQ] = useState('');
  const [mode, setMode] = useState<Mode>('products');
  const [found, setFound] = useState<{ stores: Store[]; products: Product[]; corrected?: string | null; suggestion?: string | null } | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const home = useFetch(() => api.home(location), [location?.lat, location?.lng]);

  // búsqueda con espera corta para no consultar en cada tecla
  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) return;
    let alive = true;
    const t = setTimeout(() => {
      setLoading(true);
      api.search(term, location)
        .then(r => { if (alive) { setFound(r); setFailed(null); if (!r.products.length && r.stores.length) setMode('stores'); } })
        .catch(e => { if (alive) setFailed(e.message); })
        .finally(() => { if (alive) setLoading(false); });
    }, 300);
    return () => { alive = false; clearTimeout(t); };
  }, [q, location, attempt]);

  const active = q.trim().length >= 2;
  const storeInfo = useMemo(() => new Map([...(home.data?.stores ?? []), ...(found?.stores ?? [])].map(s => [s.slug, s])), [home.data, found]);
  // productos agrupados por local (el más barato primero con «Más barato»; el más rápido, por demora)
  const groups = useMemo(() => {
    const by = new Map<string, Product[]>();
    (found?.products ?? []).forEach(p => { const k = p.store?.slug || ''; by.set(k, [...(by.get(k) ?? []), p]); });
    let out = [...by.entries()].map(([slug, items]) => ({ slug, name: items[0].store?.name || '', store: storeInfo.get(slug), items }));
    if (mode === 'cheap') out = out.map(g => ({ ...g, items: [...g.items].sort((a, b) => a.price - b.price) })).sort((a, b) => a.items[0].price - b.items[0].price);
    if (mode === 'fast') out = [...out].sort((a, b) => (a.store?.eta_min ?? 99) - (b.store?.eta_min ?? 99));
    return out;
  }, [found, storeInfo, mode]);
  const stores = useMemo(() => {
    const list = found?.stores ?? [];
    return mode === 'fast' ? [...list].sort((a, b) => a.eta_min - b.eta_min) : list;
  }, [found, mode]);
  const showStores = mode === 'stores' || (active && !groups.length && stores.length > 0);

  return (
    <View style={{ flex: 1, backgroundColor: colors.bg }}>
      <View style={[st.top, { paddingTop: insets.top + 10 }]}>
        <View style={[st.box, active && st.boxOn]}>
          <Ill e="🔍" size={22} />
          <TextInput value={q} onChangeText={setQ} placeholder="Buscá un producto o un local" placeholderTextColor={colors.muted} style={st.input} returnKeyType="search" autoCorrect={false} accessibilityLabel="Buscar" />
          {!!q && <Pressable onPress={() => setQ('')} hitSlop={10} accessibilityLabel="Borrar"><Ionicons name="close" size={20} color={colors.muted} /></Pressable>}
        </View>
        {active && (
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={st.chips} keyboardShouldPersistTaps="handled">
            {([['products', 'Productos'], ['stores', 'Comercios'], ['cheap', 'Más barato'], ['fast', 'Más rápido']] as [Mode, string][]).map(([k, label]) => (
              <Pressable key={k} onPress={() => setMode(k)} style={[st.chip, mode === k && st.chipOn]} accessibilityRole="radio" accessibilityState={{ checked: mode === k }}>
                <Text style={[st.chipText, mode === k && { color: '#fff' }]}>{label}</Text>
              </Pressable>
            ))}
          </ScrollView>
        )}
      </View>

      <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ paddingBottom: 32 }}>
        {!active && (
          <>
            <Text style={st.h2}>Buscá en todos los locales</Text>
            <View style={st.hints}>
              {HINTS.map(t => <Pressable key={t} onPress={() => setQ(t)} style={st.hint} accessibilityRole="button"><Ill e="🔍" size={14} /><Text style={st.hintText}>{t}</Text></Pressable>)}
            </View>
            <Text style={st.h2}>Rubros</Text>
            <View style={st.grid}>
              {(home.data?.store_categories ?? []).map(c => (
                <Pressable key={c.id} style={st.cell} onPress={() => openRubro(c)} accessibilityRole="button" accessibilityLabel={c.name}>
                  <View style={st.cellBox}><Ill e={c.emoji} size={44} /></View>
                  <Text style={st.cellText} numberOfLines={1}>{c.name}</Text>
                </Pressable>
              ))}
            </View>
            {!home.data && home.loading && <Loading />}
          </>
        )}

        {active && loading && !found && <Loading />}
        {active && failed && <ErrorState message={failed} onRetry={() => setAttempt(a => a + 1)} />}
        {active && !!found?.corrected && <Text style={st.note}>Mostrando resultados para <Text style={{ fontWeight: '900' }}>«{found.corrected}»</Text></Text>}

        {active && !showStores && groups.map(g => (
          <View key={g.slug} style={{ marginTop: 14 }}>
            <View style={st.gHead}>
              {g.store ? <StoreBadge store={g.store} size={40} /> : <View style={st.gLogo}><Ill e="🏪" size={26} /></View>}
              <View style={{ flex: 1 }}>
                <Text style={st.gName} numberOfLines={1}>{g.name}</Text>
                {!!g.store && <Text style={st.gMeta}>{g.store.eta_min}–{g.store.eta_max} min · {shipText(g.store)}</Text>}
              </View>
              <Pressable onPress={() => router.push({ pathname: '/store/[slug]', params: { slug: g.slug } })} hitSlop={8}><Text style={st.link}>Ver local</Text></Pressable>
            </View>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ paddingHorizontal: 16, gap: 10 }}>
              {g.items.map(p => <ResultTile key={p.id} p={p} />)}
            </ScrollView>
          </View>
        ))}
        {active && showStores && <View style={{ marginTop: 12 }}>{stores.map(s => <BigStoreCard key={s.id} store={s} />)}</View>}

        {active && !loading && found && !groups.length && !stores.length && (
          <Empty emoji="🔎" title="No encontramos nada" text={`Nada coincide con «${q.trim()}». Probá con otra palabra.`}
            action={found.suggestion ? <Pressable onPress={() => setQ(found.suggestion!)}><Text style={st.link}>¿Quisiste decir {found.suggestion}?</Text></Pressable> : undefined} />
        )}
      </ScrollView>
    </View>
  );
}

/** Producto encontrado: ilustración o foto, «+», precio (por kg) y nombre. */
function ResultTile({ p }: { p: Product }) {
  return (
    <Pressable onPress={() => router.push({ pathname: '/product/[id]', params: { id: String(p.id) } })} style={st.tile} disabled={p.sold_out}
      accessibilityRole="button" accessibilityLabel={`${p.name}, ${money(p.price)}${p.weight ? ' el kilo' : ''}`}>
      <View style={st.timg}>
        {p.image_url ? <Image source={{ uri: p.image_url }} style={StyleSheet.absoluteFill} contentFit="cover" /> : <Ill e={p.emoji} size={58} />}
        <View style={st.plus}><Ionicons name="add" size={20} color={colors.brand} /></View>
      </View>
      <Text style={st.price}>{money(p.price)}{!!p.weight && <Text style={st.kg}> /kg</Text>}</Text>
      <Text style={st.name} numberOfLines={2}>{p.name}</Text>
      {p.weight ? <View style={st.kgTag}><Text style={st.kgTagText}>⚖ por kg</Text></View>
        : !!p.unit_price_text && <Text style={st.unit}>{p.unit_price_text}</Text>}
    </Pressable>
  );
}

const st = StyleSheet.create({
  top: { backgroundColor: '#fff', paddingHorizontal: 16, paddingBottom: 10, borderBottomWidth: 1, borderBottomColor: colors.line },
  box: { flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: '#F7F6FA', borderRadius: 18, paddingHorizontal: 14, height: 52, borderWidth: 2, borderColor: 'transparent' },
  boxOn: { borderColor: colors.brand, backgroundColor: '#fff' },
  input: { flex: 1, fontSize: 16.5, color: colors.ink, fontWeight: '600' },
  chips: { gap: 8, paddingTop: 12 },
  chip: { paddingHorizontal: 15, height: 38, borderRadius: 99, backgroundColor: '#fff', borderWidth: 1, borderColor: colors.line, justifyContent: 'center' },
  chipOn: { backgroundColor: colors.ink, borderColor: colors.ink },
  chipText: { fontWeight: '800', color: colors.ink, fontSize: 14 },
  h2: { fontSize: 20, fontWeight: '900', color: colors.ink, paddingHorizontal: 16, marginTop: 18, marginBottom: 10, letterSpacing: -0.4 },
  hints: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, paddingHorizontal: 16 },
  hint: { flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: '#fff', borderRadius: 99, paddingHorizontal: 12, paddingVertical: 8, borderWidth: 1, borderColor: colors.line },
  hintText: { fontWeight: '700', color: colors.ink },
  grid: { flexDirection: 'row', flexWrap: 'wrap', paddingHorizontal: 11, rowGap: 10 },
  cell: { width: '25%', paddingHorizontal: 5 },
  cellBox: { backgroundColor: '#fff', borderRadius: 20, aspectRatio: 1, alignItems: 'center', justifyContent: 'center' },
  cellText: { fontSize: 12.5, fontWeight: '800', color: colors.ink, textAlign: 'center', marginTop: 6 },
  note: { color: colors.ink, paddingHorizontal: 16, marginTop: 12 },
  gHead: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 16, marginBottom: 10 },
  gLogo: { width: 40, height: 40, borderRadius: 12, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center' },
  gName: { fontWeight: '900', color: colors.ink, fontSize: 16.5 },
  gMeta: { color: colors.muted, fontSize: 12.5 },
  link: { color: colors.brand, fontWeight: '800', fontSize: 14 },
  tile: { width: 118, backgroundColor: '#fff', borderRadius: 18, padding: 8, gap: 2 },
  timg: { height: 94, borderRadius: 14, backgroundColor: '#FFF1F2', alignItems: 'center', justifyContent: 'center', overflow: 'hidden', marginBottom: 4 },
  plus: { position: 'absolute', right: 5, bottom: 5, width: 28, height: 28, borderRadius: 14, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center',
    shadowColor: '#000', shadowOpacity: 0.12, shadowRadius: 4, shadowOffset: { width: 0, height: 1 }, elevation: 2 },
  price: { fontWeight: '900', color: colors.ink, fontSize: 15 },
  kg: { fontSize: 12, color: colors.ink, fontWeight: '800' },
  name: { color: colors.ink, fontSize: 12.5, lineHeight: 16 },
  kgTag: { alignSelf: 'flex-start', backgroundColor: '#FFF7E6', borderRadius: 8, paddingHorizontal: 6, paddingVertical: 2, marginTop: 3 },
  kgTagText: { fontSize: 11, fontWeight: '800', color: '#92400E' },
  unit: { fontSize: 11, color: colors.muted, marginTop: 2 },
});
