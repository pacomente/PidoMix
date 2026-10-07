import Ionicons from '@expo/vector-icons/Ionicons';
import * as Haptics from 'expo-haptics';
import { Link, router, Stack, useLocalSearchParams } from 'expo-router';
import { Linking, Pressable, RefreshControl, SectionList, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { FleetBadge } from '@/components/market';
import { Chip, confirmReplace, deliveryText, ErrorState, Loading, ProductRow, SectionTitle, Thumb, s as ui } from '@/components/ui';
import { api } from '@/lib/api';
import { km, money } from '@/lib/format';
import { colors, radius } from '@/lib/theme';
import type { CartLine, Product, Store } from '@/lib/types';
import { useFetch } from '@/lib/useFetch';
import { useApp } from '@/state/app-state';

export default function StoreScreen() {
  const { slug } = useLocalSearchParams<{ slug: string }>();
  const insets = useSafeAreaInsets();
  const { location, cart, cartCount, addToCart } = useApp();
  const res = useFetch(() => api.store(slug, location), [slug, location?.lat, location?.lng]);

  if (res.loading && !res.data) return <Loading />;
  if (res.error && !res.data) return <ErrorState message={res.error} onRetry={res.reload} />;
  const { store, menu, reviews, rating_summary } = res.data!;
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

  return (
    <View style={{ flex: 1, backgroundColor: colors.bg }}>
      <Stack.Screen options={{ title: store.name }} />
      <SectionList
        sections={menu.map(m => ({ key: m.key, title: m.title, data: m.products }))}
        keyExtractor={p => String(p.id)}
        stickySectionHeadersEnabled={false}
        contentContainerStyle={{ paddingHorizontal: 16, paddingBottom: cartCount ? 110 : 32 }}
        refreshControl={<RefreshControl refreshing={res.refreshing} onRefresh={res.refresh} tintColor={colors.brand} />}
        renderSectionHeader={({ section }) => <SectionTitle>{section.title}</SectionTitle>}
        renderItem={({ item }) => <ProductRow product={item} onAdd={() => add(item)} disabled={item.sold_out || !store.is_open} />}
        ListHeaderComponent={<StoreHeader store={store} />}
        ListEmptyComponent={<Text style={[ui.muted, { marginTop: 20 }]}>Este comercio todavía no cargó su menú.</Text>}
        ListFooterComponent={rating_summary.count > 0 ? (
          <View>
            <SectionTitle right={<Text style={st.bigRating}>★ {rating_summary.avg.toFixed(1)} <Text style={ui.muted}>({rating_summary.count})</Text></Text>}>Opiniones</SectionTitle>
            {reviews.map(r => (
              <View key={r.id} style={st.review}>
                <View style={ui.row}>
                  <Text style={{ fontWeight: '800', color: colors.ink }}>{r.author}</Text>
                  <Text style={{ color: colors.star, letterSpacing: 1 }}>{'★'.repeat(r.rating)}<Text style={{ color: colors.line }}>{'★'.repeat(5 - r.rating)}</Text></Text>
                </View>
                {!!r.comment && <Text style={{ color: colors.ink, marginTop: 4 }}>{r.comment}</Text>}
                {!!r.reply && <View style={st.reply}><Text style={{ fontWeight: '700', color: colors.brand }}>Respuesta del comercio</Text><Text style={{ color: colors.ink }}>{r.reply}</Text></View>}
              </View>
            ))}
          </View>
        ) : null}
      />
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

function StoreHeader({ store }: { store: Store }) {
  const d = deliveryText(store);
  const c = store.coverage;
  return (
    <View>
      <Thumb uri={store.cover_url} emoji={store.emoji} hue={store.hue} style={st.cover} emojiSize={64} />
      <View style={st.info}>
        <View style={{ flexDirection: 'row', gap: 12, alignItems: 'center' }}>
          {store.logo_url ? <Thumb uri={store.logo_url} emoji={store.emoji} hue={store.hue} size={56} style={{ borderRadius: 14 }} /> : null}
          <View style={{ flex: 1 }}>
            <Text style={ui.h1} numberOfLines={2}>{store.name}</Text>
            <Text style={ui.muted}>{[store.category, store.address].filter(Boolean).join(' · ')}</Text>
          </View>
        </View>
        {!!store.description && <Text style={{ color: colors.ink, marginTop: 8 }}>{store.description}</Text>}
        <View style={st.chips}>
          <Chip label={store.is_open ? 'Abierto' : store.open_text || 'Cerrado'} tone={store.is_open ? 'good' : 'bad'} />
          {store.rating !== null && <Chip label={`★ ${store.rating.toFixed(1)} (${store.rating_count})`} tone="warn" />}
          <Chip label={`🕒 ${store.eta_min}–${store.eta_max} min`} />
          <Chip label={d.text} tone={d.tone} />
          {c.distance_km !== null && <Chip label={`📍 ${km(c.distance_km)}`} />}
          {store.minimum_order > 0 && <Chip label={`Mínimo ${money(store.minimum_order)}`} />}
        </View>
        {!!store.fleet && (
          <View style={st.fleetRow}>
            <FleetBadge store={store} />
            <Text style={st.fleetNote}>{store.fleet === 'trappi' ? 'Lo lleva un repartidor de Trappi.' : store.fleet === 'mixed' ? 'Lo lleva un repartidor del local o, si no hay, uno de Trappi.' : 'Lo lleva un repartidor del local.'}</Text>
          </View>
        )}
        {c.covered === false && (
          <View style={st.warn}><Text style={{ color: colors.bad, fontWeight: '700' }}>Este comercio no llega a tu ubicación{c.max_km ? ` (reparte hasta ${km(c.max_km)})` : ''}. Podés pedir para retirar.</Text></View>
        )}
        {c.covered === null && store.delivery_enabled && c.zoned && (
          <Link href="/location" asChild><Pressable style={st.locHint}><Ionicons name="location" size={16} color={colors.brand} /><Text style={{ color: colors.brand, fontWeight: '700', flex: 1 }}>Marcá tu ubicación para saber el costo exacto del envío</Text></Pressable></Link>
        )}
        {!!store.whatsapp && (
          <Pressable onPress={() => Linking.openURL(`https://wa.me/${store.whatsapp!.replace(/\D/g, '')}`)} style={st.wa}>
            <Ionicons name="logo-whatsapp" size={16} color={colors.good} /><Text style={{ color: colors.good, fontWeight: '700' }}>Consultar por WhatsApp</Text>
          </Pressable>
        )}
      </View>
    </View>
  );
}

const st = StyleSheet.create({
  fleetRow: { flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginTop: 10 },
  fleetNote: { color: colors.muted, fontSize: 13, flexShrink: 1 },
  cover: { height: 170, marginHorizontal: -16 },
  info: { backgroundColor: '#fff', borderRadius: radius.lg, padding: 16, marginTop: -30, borderWidth: 1, borderColor: colors.line },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 12 },
  warn: { marginTop: 12, padding: 12, borderRadius: radius.sm, backgroundColor: colors.badSoft },
  locHint: { marginTop: 12, padding: 12, borderRadius: radius.sm, backgroundColor: colors.brandSoft, flexDirection: 'row', gap: 6, alignItems: 'center' },
  wa: { marginTop: 12, flexDirection: 'row', gap: 6, alignItems: 'center' },
  bigRating: { fontWeight: '800', color: colors.warn, fontSize: 16 },
  review: { backgroundColor: '#fff', borderRadius: radius.md, padding: 14, borderWidth: 1, borderColor: colors.line, marginBottom: 10 },
  reply: { marginTop: 8, padding: 10, borderRadius: radius.sm, backgroundColor: colors.brandSoft, gap: 2 },
  cartBar: { position: 'absolute', left: 16, right: 16, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12, backgroundColor: colors.brand, borderRadius: radius.pill, paddingHorizontal: 14, paddingVertical: 12, shadowColor: '#000', shadowOpacity: 0.2, shadowRadius: 10, shadowOffset: { width: 0, height: 4 }, elevation: 6 },
  cartCount: { backgroundColor: '#fff', width: 30, height: 30, borderRadius: 15, alignItems: 'center', justifyContent: 'center' },
  cartText: { color: '#fff', fontWeight: '800', fontSize: 16 },
});
