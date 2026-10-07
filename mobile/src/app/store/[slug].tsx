import Ionicons from '@expo/vector-icons/Ionicons';
import * as Haptics from 'expo-haptics';
import { Image } from 'expo-image';
import { Link, router, Stack, useLocalSearchParams } from 'expo-router';
import { useMemo, useRef, useState } from 'react';
import { Linking, Pressable, RefreshControl, ScrollView, SectionList, StyleSheet, Text, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Carousel, Cover, DealBadge, FleetBadge, ProductTile, StoreLogo } from '@/components/market';
import { confirmReplace, deliveryText, ErrorState, Loading } from '@/components/ui';
import { api } from '@/lib/api';
import { km, money } from '@/lib/format';
import { colors, radius } from '@/lib/theme';
import type { CartLine, Product, Store } from '@/lib/types';
import { useFetch } from '@/lib/useFetch';
import { useApp } from '@/state/app-state';

const COVER = 210;
const FLEET_NOTE = { trappi: 'Lo lleva un repartidor de Trappi.', store: 'Lo lleva un repartidor del local.', mixed: 'Lo lleva un repartidor del local o, si no hay, uno de Trappi.' } as const;

export default function StoreScreen() {
  const { slug } = useLocalSearchParams<{ slug: string }>();
  const insets = useSafeAreaInsets();
  const { location, cart, cartCount, addToCart } = useApp();
  const res = useFetch(() => api.store(slug, location), [slug, location?.lat, location?.lng]);
  const list = useRef<SectionList<Product>>(null);
  const [q, setQ] = useState('');
  const [headerH, setHeaderH] = useState(9999);
  const [solid, setSolid] = useState(false);
  const [stuck, setStuck] = useState(false);
  const [active, setActive] = useState(0);
  const [searchY, setSearchY] = useState(0);
  const input = useRef<TextInput>(null);

  const menu = res.data?.menu;
  const sections = useMemo(() => {
    const term = q.trim().toLowerCase();
    return (menu ?? [])
      .map(m => ({ key: m.key, title: m.title, data: term ? m.products.filter(p => `${p.name} ${p.description ?? ''}`.toLowerCase().includes(term)) : m.products }))
      .filter(m => m.data.length);
  }, [menu, q]);

  if (res.loading && !res.data) return <Loading />;
  if (res.error && !res.data) return <ErrorState message={res.error} onRetry={res.reload} />;
  const { store, reviews, rating_summary } = res.data!;
  const all = (menu ?? []).flatMap(m => m.products);
  const featured = all.filter(p => p.featured && !p.sold_out).slice(0, 10);
  const showFeatured = featured.length >= 2 && all.length > featured.length;
  const bestOff = all.reduce((n, p) => (p.previous_price && p.previous_price > p.price ? Math.max(n, Math.round((1 - p.price / p.previous_price) * 100)) : n), 0);
  const cartHere = cart.length > 0 && cart[0].store_slug === store.slug;
  const cartTotal = cart.reduce((n, x) => n + x.unit_price * x.quantity, 0);

  const add = (p: Product) => {
    if (p.customizable) {
      router.push({ pathname: '/product/[id]', params: { id: String(p.id) } });
      return;
    }
    const line: CartLine = { product_id: p.id, quantity: 1, modifiers: [], name: p.name, unit_price: p.price, modifiers_text: null, store_slug: store.slug, store_name: store.name };
    const done = () => Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
    if (addToCart(line) === 'other_store') confirmReplace(cart[0].store_name, () => { addToCart(line, true); done(); });
    else done();
  };
  const jump = (i: number) => {
    setActive(i);
    list.current?.scrollToLocation({ sectionIndex: i, itemIndex: 0, viewOffset: insets.top + 110, animated: true });
  };
  const goSearch = () => {
    list.current?.getScrollResponder()?.scrollTo({ y: Math.max(0, searchY - insets.top - 70), animated: true });
    setTimeout(() => input.current?.focus(), 350);
  };
  const back = () => (router.canGoBack() ? router.back() : router.replace('/'));

  const tabs = (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={st.tabs} keyboardShouldPersistTaps="handled">
      {sections.map((s, i) => (
        <Pressable key={s.key} onPress={() => jump(i)} style={[st.tab, active === i && st.tabOn]} accessibilityRole="tab" accessibilityState={{ selected: active === i }}>
          <Text style={[st.tabText, active === i && { color: '#fff' }]}>{s.title}</Text>
        </Pressable>
      ))}
    </ScrollView>
  );

  return (
    <View style={{ flex: 1, backgroundColor: '#fff' }}>
      <Stack.Screen options={{ headerShown: false }} />
      <SectionList
        ref={list}
        sections={sections}
        keyExtractor={p => String(p.id)}
        stickySectionHeadersEnabled={false}
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={{ paddingBottom: cartHere && cartCount ? 120 : 40 }}
        scrollEventThrottle={32}
        onScroll={e => {
          const y = e.nativeEvent.contentOffset.y;
          if (y > COVER - 50 !== solid) setSolid(!solid);
          if (y > headerH - insets.top - 110 !== stuck) setStuck(!stuck);
        }}
        onViewableItemsChanged={({ viewableItems }) => {
          const first = viewableItems.find(v => v.section);
          const i = first ? sections.findIndex(s => s.key === (first.section as { key: string }).key) : -1;
          if (i >= 0) setActive(i);
        }}
        onScrollToIndexFailed={() => {}}
        refreshControl={<RefreshControl refreshing={res.refreshing} onRefresh={res.refresh} tintColor={colors.brand} />}
        renderSectionHeader={({ section }) => <Text style={st.h2}>{section.title}</Text>}
        renderItem={({ item }) => <MenuRow product={item} onAdd={() => add(item)} disabled={item.sold_out || !store.is_open} />}
        ListHeaderComponent={
          <View onLayout={e => setHeaderH(e.nativeEvent.layout.height)}>
            <Cover store={store} style={{ height: COVER + insets.top }} />
            <StoreCard store={store} bestOff={bestOff} rating={rating_summary.count ? rating_summary.avg : null} />
            {showFeatured && !q && (
              <View style={{ marginTop: 18 }}>
                <Text style={st.h2}>Destacados</Text>
                <Carousel gap={12}>{featured.map(p => <ProductTile key={p.id} product={p} width={140} showStore={false} />)}</Carousel>
              </View>
            )}
            <View style={st.searchBox} onLayout={e => setSearchY(e.nativeEvent.layout.y)}>
              <Ionicons name="search" size={19} color={colors.muted} />
              <TextInput ref={input} value={q} onChangeText={setQ} placeholder={`Buscar en ${store.name}`} placeholderTextColor={colors.muted} style={st.searchInput} returnKeyType="search" accessibilityLabel="Buscar en el menú" />
              {!!q && <Pressable onPress={() => setQ('')} hitSlop={10} accessibilityLabel="Borrar"><Ionicons name="close-circle" size={20} color={colors.muted} /></Pressable>}
            </View>
            {sections.length > 1 && tabs}
          </View>
        }
        ListEmptyComponent={<Text style={st.empty}>{q ? `No hay productos con "${q.trim()}".` : 'Este comercio todavía no cargó su menú.'}</Text>}
        ListFooterComponent={rating_summary.count > 0 ? (
          <View style={{ marginTop: 18 }}>
            <View style={st.revHead}>
              <Text style={[st.h2, { paddingHorizontal: 0, marginTop: 0 }]}>Opiniones</Text>
              <Text style={st.revAvg}><Ionicons name="star" size={16} color={colors.star} /> {rating_summary.avg.toFixed(1).replace('.', ',')} <Text style={st.muted}>({rating_summary.count})</Text></Text>
            </View>
            <Carousel gap={12}>
              {reviews.map(r => (
                <View key={r.id} style={st.review}>
                  <View style={st.rowBetween}>
                    <Text style={st.revAuthor} numberOfLines={1}>{r.author}</Text>
                    <Text style={{ color: colors.star, letterSpacing: 1 }}>{'★'.repeat(r.rating)}<Text style={{ color: colors.line }}>{'★'.repeat(5 - r.rating)}</Text></Text>
                  </View>
                  {!!r.comment && <Text style={st.revText} numberOfLines={4}>{r.comment}</Text>}
                  {!!r.reply && <View style={st.reply}><Text style={{ fontWeight: '700', color: colors.brand }}>Respuesta del comercio</Text><Text style={{ color: colors.ink }} numberOfLines={3}>{r.reply}</Text></View>}
                </View>
              ))}
            </Carousel>
          </View>
        ) : null}
      />

      {/* botones sobre la portada; al bajar se vuelven una barra con el nombre y las secciones */}
      <View style={[st.top, { paddingTop: insets.top + 6 }, solid && st.topStuck]} pointerEvents="box-none">
        <View style={st.topRow} pointerEvents="box-none">
          <Pressable onPress={back} style={st.round} hitSlop={8} accessibilityLabel="Volver"><Ionicons name="arrow-back" size={22} color={colors.ink} /></Pressable>
          {solid ? <Text style={st.topTitle} numberOfLines={1}>{store.name}</Text> : <View style={{ flex: 1 }} />}
          <Pressable onPress={goSearch} style={st.round} hitSlop={8} accessibilityLabel="Buscar en el menú"><Ionicons name="search" size={21} color={colors.ink} /></Pressable>
          <Pressable onPress={() => router.push('/cart')} style={st.round} hitSlop={8} accessibilityLabel={`Mi pedido, ${cartCount} productos`}>
            <Ionicons name="cart-outline" size={22} color={colors.ink} />
            {cartCount > 0 && <View style={st.badge}><Text style={st.badgeText}>{cartCount}</Text></View>}
          </Pressable>
        </View>
        {stuck && sections.length > 1 && tabs}
      </View>

      {cartHere && cartCount > 0 && (
        <Link href="/cart" asChild>
          <Pressable style={StyleSheet.flatten([st.cartBar, { bottom: insets.bottom + 12 }])} accessibilityLabel="Ver mi pedido">
            <View style={st.cartCount}><Text style={{ color: colors.brand, fontWeight: '800' }}>{cartCount}</Text></View>
            <Text style={st.cartText}>Ver mi pedido</Text>
            <Text style={st.cartText}>{money(cartTotal)}</Text>
          </Pressable>
        </Link>
      )}
    </View>
  );
}

function StoreCard({ store, bestOff, rating }: { store: Store; bestOff: number; rating: number | null }) {
  const d = deliveryText(store);
  const c = store.coverage;
  return (
    <View style={st.card}>
      <View style={st.logoWrap}><StoreLogo store={store} size={76} /></View>
      <View style={st.rowBetween}>
        <Text style={st.name} numberOfLines={2}>{store.name}</Text>
        {rating !== null && <Text style={st.rating}><Ionicons name="star" size={15} color={colors.star} /> {rating.toFixed(1).replace('.', ',')} <Text style={st.muted}>({store.rating_count})</Text></Text>}
      </View>
      <Text style={st.muted} numberOfLines={2}>{[store.category, store.description].filter(Boolean).join(' · ')}</Text>

      <View style={st.meta}>
        <View style={st.metaItem}><Ionicons name="time-outline" size={17} color={colors.ink} /><Text style={st.metaText}>{store.eta_min}-{store.eta_max} min</Text></View>
        <View style={st.metaItem}>
          <Ionicons name={store.delivery_enabled ? 'bicycle-outline' : 'storefront-outline'} size={17} color={d.tone === 'good' ? colors.good : colors.ink} />
          <Text style={[st.metaText, d.tone === 'good' && { color: colors.good }, d.tone === 'bad' && { color: colors.bad }]}>{d.text}</Text>
        </View>
        {c.distance_km !== null && <View style={st.metaItem}><Ionicons name="location-outline" size={17} color={colors.ink} /><Text style={st.metaText}>{km(c.distance_km)}</Text></View>}
        {store.minimum_order > 0 && <View style={st.metaItem}><Ionicons name="bag-outline" size={17} color={colors.ink} /><Text style={st.metaText}>Mínimo {money(store.minimum_order)}</Text></View>}
      </View>

      <View style={st.badges}>
        <View style={[st.state, { backgroundColor: store.is_open ? colors.goodSoft : colors.badSoft }]}>
          <Text style={{ color: store.is_open ? colors.good : colors.bad, fontWeight: '800', fontSize: 12.5 }}>{store.is_open ? 'Abierto' : store.open_text || 'Cerrado'}</Text>
        </View>
        {bestOff > 0 && <DealBadge label={`Hasta ${bestOff}% OFF`} />}
        <FleetBadge store={store} />
      </View>
      {!!store.fleet && <Text style={[st.muted, { marginTop: 6 }]}>{FLEET_NOTE[store.fleet]}</Text>}

      {c.covered === false && (
        <View style={st.warn}><Text style={{ color: colors.bad, fontWeight: '700' }}>Este comercio no llega a tu ubicación{c.max_km ? ` (reparte hasta ${km(c.max_km)})` : ''}. Podés pedir para retirar.</Text></View>
      )}
      {c.covered === null && store.delivery_enabled && c.zoned && (
        <Link href="/location" asChild><Pressable style={st.locHint}><Ionicons name="location" size={16} color={colors.brand} /><Text style={{ color: colors.brand, fontWeight: '700', flex: 1 }}>Marcá tu ubicación para saber el costo exacto del envío</Text></Pressable></Link>
      )}
      {(!!store.whatsapp || !!store.address) && (
        <View style={st.links}>
          {!!store.address && <View style={[st.metaItem, { flexShrink: 1 }]}><Ionicons name="storefront-outline" size={16} color={colors.muted} /><Text style={st.muted} numberOfLines={1}>{store.address}</Text></View>}
          {!!store.whatsapp && (
            <Pressable onPress={() => Linking.openURL(`https://wa.me/${store.whatsapp!.replace(/\D/g, '')}`)} style={st.metaItem} accessibilityRole="link">
              <Ionicons name="logo-whatsapp" size={17} color={colors.good} /><Text style={{ color: colors.good, fontWeight: '700' }}>Consultar</Text>
            </Pressable>
          )}
        </View>
      )}
    </View>
  );
}

/** Fila del menú: nombre, descripción y precio; foto a la derecha con el botón "+" encima. */
function MenuRow({ product, onAdd, disabled }: { product: Product; onAdd: () => void; disabled?: boolean }) {
  const off = product.previous_price && product.previous_price > product.price ? Math.round((1 - product.price / product.previous_price) * 100) : 0;
  return (
    <Pressable onPress={disabled ? undefined : onAdd} style={({ pressed }) => [st.prow, pressed && !disabled && { backgroundColor: '#FAF9FC' }, product.sold_out && { opacity: 0.5 }]}
      accessibilityRole="button" accessibilityLabel={`Agregar ${product.name}, ${money(product.price)}`} accessibilityState={{ disabled: !!disabled }}>
      <View style={{ flex: 1, gap: 4 }}>
        <Text style={st.pname}>{product.name}</Text>
        {!!product.description && <Text style={st.muted} numberOfLines={2}>{product.description}</Text>}
        <View style={st.priceRow}>
          <Text style={st.price}>{money(product.price)}</Text>
          {off > 0 && <Text style={st.prev}>{money(product.previous_price)}</Text>}
          {off > 0 && <DealBadge label={`${off}% OFF`} />}
        </View>
        {(product.customizable || product.sold_out) && <Text style={[st.small, product.sold_out && { color: colors.bad }]}>{product.sold_out ? 'Sin stock' : 'Elegí opciones'}</Text>}
      </View>
      {product.image_url ? (
        <View style={st.pimg}>
          <Image source={{ uri: product.image_url }} style={StyleSheet.absoluteFill} contentFit="cover" transition={150} />
          <View style={[st.plus, disabled && { opacity: 0.5 }]}><Ionicons name="add" size={22} color={colors.brand} /></View>
        </View>
      ) : (
        <View style={[st.plus, st.plusAlone, disabled && { opacity: 0.5 }]}><Ionicons name="add" size={22} color={colors.brand} /></View>
      )}
    </Pressable>
  );
}

const st = StyleSheet.create({
  top: { position: 'absolute', left: 0, right: 0, top: 0 },
  topStuck: { backgroundColor: '#fff', borderBottomWidth: 1, borderBottomColor: colors.line },
  topRow: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 14, paddingBottom: 8 },
  topTitle: { flex: 1, fontSize: 17, fontWeight: '800', color: colors.ink },
  round: { width: 42, height: 42, borderRadius: 21, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center', shadowColor: '#000', shadowOpacity: 0.12, shadowRadius: 6, shadowOffset: { width: 0, height: 2 }, elevation: 3 },
  badge: { position: 'absolute', top: -3, right: -3, minWidth: 18, height: 18, borderRadius: 9, backgroundColor: '#FFE14D', alignItems: 'center', justifyContent: 'center', paddingHorizontal: 4 },
  badgeText: { color: colors.ink, fontWeight: '800', fontSize: 11 },
  card: { marginTop: -26, marginHorizontal: 0, backgroundColor: '#fff', borderTopLeftRadius: 26, borderTopRightRadius: 26, paddingHorizontal: 16, paddingTop: 50, gap: 4 },
  logoWrap: { position: 'absolute', top: -38, left: 16, borderRadius: 24, borderWidth: 4, borderColor: '#fff', backgroundColor: '#fff', shadowColor: '#000', shadowOpacity: 0.12, shadowRadius: 8, shadowOffset: { width: 0, height: 3 }, elevation: 4 },
  rowBetween: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10 },
  name: { flex: 1, fontSize: 24, fontWeight: '800', color: colors.ink, letterSpacing: -0.5 },
  rating: { fontSize: 15.5, fontWeight: '800', color: colors.ink, marginTop: 5 },
  muted: { color: colors.muted, fontSize: 14 },
  small: { color: colors.brand, fontSize: 13, fontWeight: '700' },
  meta: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 12 },
  metaItem: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  metaText: { fontSize: 14.5, fontWeight: '600', color: colors.ink, marginRight: 8 },
  badges: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 12, alignItems: 'center' },
  state: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 8 },
  warn: { marginTop: 12, padding: 12, borderRadius: radius.sm, backgroundColor: colors.badSoft },
  locHint: { marginTop: 12, padding: 12, borderRadius: radius.sm, backgroundColor: colors.brandSoft, flexDirection: 'row', gap: 6, alignItems: 'center' },
  links: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 12, marginTop: 14, paddingTop: 12, borderTopWidth: 1, borderTopColor: colors.line },
  h2: { fontSize: 21, fontWeight: '800', color: colors.ink, paddingHorizontal: 16, marginTop: 22, marginBottom: 10, letterSpacing: -0.4 },
  searchBox: { flexDirection: 'row', alignItems: 'center', gap: 10, marginHorizontal: 16, marginTop: 20, backgroundColor: '#F2F1F5', borderRadius: radius.pill, paddingHorizontal: 16, height: 48 },
  searchInput: { flex: 1, fontSize: 16, color: colors.ink },
  tabs: { paddingHorizontal: 16, gap: 8, paddingVertical: 10 },
  tab: { paddingHorizontal: 16, height: 38, justifyContent: 'center', borderRadius: radius.pill, backgroundColor: '#F2F1F5' },
  tabOn: { backgroundColor: colors.ink },
  tabText: { fontWeight: '700', color: colors.ink, fontSize: 14.5 },
  empty: { color: colors.muted, paddingHorizontal: 16, marginTop: 24, textAlign: 'center' },
  prow: { flexDirection: 'row', gap: 14, paddingHorizontal: 16, paddingVertical: 14, borderBottomWidth: 1, borderBottomColor: '#F2F1F5' },
  pname: { fontSize: 16.5, fontWeight: '700', color: colors.ink },
  priceRow: { flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginTop: 2 },
  price: { fontSize: 16, fontWeight: '800', color: colors.ink },
  prev: { fontSize: 14, color: colors.muted, textDecorationLine: 'line-through' },
  pimg: { width: 104, height: 104, borderRadius: 16, overflow: 'hidden', backgroundColor: '#F2F1F5' },
  plusAlone: { position: 'relative', right: 0, bottom: 0, alignSelf: 'center', borderWidth: 1, borderColor: colors.line, shadowOpacity: 0, elevation: 0 },
  plus: { position: 'absolute', right: 6, bottom: 6, width: 34, height: 34, borderRadius: 17, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center', shadowColor: '#000', shadowOpacity: 0.15, shadowRadius: 4, shadowOffset: { width: 0, height: 1 }, elevation: 2 },
  revHead: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 16, marginBottom: 10 },
  revAvg: { fontSize: 16, fontWeight: '800', color: colors.ink },
  review: { width: 260, backgroundColor: '#fff', borderRadius: radius.md, padding: 14, borderWidth: 1, borderColor: colors.line, gap: 6 },
  revAuthor: { fontWeight: '800', color: colors.ink, flex: 1 },
  revText: { color: colors.ink, lineHeight: 20 },
  reply: { marginTop: 4, padding: 10, borderRadius: radius.sm, backgroundColor: colors.brandSoft, gap: 2 },
  cartBar: { position: 'absolute', left: 16, right: 16, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12, backgroundColor: colors.brand, borderRadius: radius.pill, paddingHorizontal: 14, paddingVertical: 13, shadowColor: '#000', shadowOpacity: 0.2, shadowRadius: 10, shadowOffset: { width: 0, height: 4 }, elevation: 6 },
  cartCount: { backgroundColor: '#fff', width: 30, height: 30, borderRadius: 15, alignItems: 'center', justifyContent: 'center' },
  cartText: { color: '#fff', fontWeight: '800', fontSize: 16 },
});
