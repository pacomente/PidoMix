import Ionicons from '@expo/vector-icons/Ionicons';
import { Image } from 'expo-image';
import { router, useFocusEffect } from 'expo-router';
import { setStatusBarStyle } from 'expo-status-bar';
import { useCallback, type ReactNode } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View, type StyleProp, type ViewStyle } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { deliveryText } from '@/components/ui';
import { km, money } from '@/lib/format';
import { colors, radius } from '@/lib/theme';
import type { Product, Store } from '@/lib/types';
import { useApp } from '@/state/app-state';

/** Iniciales de un comercio sin logo: "Burger Mix" -> "BM". */
export const initials = (name: string) => name.split(/\s+/).filter(w => /^[\p{L}\p{N}]/u.test(w)).slice(0, 2).map(w => w[0]).join('').toUpperCase() || 'T';
const tone = (hue: number, l: number, sat = 42) => `hsl(${hue}, ${sat}%, ${l}%)`;

/** Etiqueta amarilla de descuento ("Hasta 30% OFF"). */
export function DealBadge({ label, style }: { label: string; style?: StyleProp<ViewStyle> }) {
  return <View style={[s.deal, style]}><Text style={s.dealText}>{label}</Text></View>;
}

/** Logo del comercio (o sus iniciales en un color propio). */
export function StoreLogo({ store, size = 56 }: { store: Pick<Store, 'name' | 'logo_url' | 'hue'>; size?: number }) {
  return (
    <View style={[s.logo, { width: size, height: size, borderRadius: size * 0.28, backgroundColor: store.logo_url ? '#fff' : tone(store.hue, 46) }]}>
      {store.logo_url ? <Image source={{ uri: store.logo_url }} style={StyleSheet.absoluteFill} contentFit="cover" />
        : <Text style={[s.logoText, { fontSize: size * 0.34 }]}>{initials(store.name)}</Text>}
    </View>
  );
}

/** Portada (o un fondo suave del color del comercio). */
function Cover({ store, style, children }: { store: Store; style: StyleProp<ViewStyle>; children?: ReactNode }) {
  return (
    <View style={[style, { backgroundColor: store.cover_url ? colors.line : tone(store.hue, 94, 45), overflow: 'hidden' }]}>
      {store.cover_url ? <Image source={{ uri: store.cover_url }} style={StyleSheet.absoluteFill} contentFit="cover" transition={150} />
        : <View style={[StyleSheet.absoluteFill, { alignItems: 'center', justifyContent: 'center' }]}><Ionicons name="storefront-outline" size={44} color={tone(store.hue, 78, 30)} /></View>}
      {children}
    </View>
  );
}

function Meta({ store, compact }: { store: Store; compact?: boolean }) {
  const d = deliveryText(store);
  return (
    <View style={s.metaWrap}>
      <View style={s.metaRow}><Ionicons name="time-outline" size={16} color={colors.ink} /><Text style={s.meta}>{store.eta_min}-{store.eta_max} min</Text></View>
      <View style={s.metaRow}>
        <Ionicons name={store.delivery_enabled ? 'bicycle-outline' : 'storefront-outline'} size={16} color={d.tone === 'good' ? colors.brand : colors.ink} />
        <Text style={[s.meta, d.tone === 'good' && s.free, d.tone === 'bad' && { color: colors.bad }]}>{d.tone === 'good' ? 'Gratis' : d.text.replace('Envío ', '')}</Text>
      </View>
      {!compact && store.coverage.distance_km !== null && (
        <View style={s.metaRow}><Ionicons name="location-outline" size={16} color={colors.ink} /><Text style={s.meta}>{km(store.coverage.distance_km)}</Text></View>
      )}
    </View>
  );
}

const openStore = (slug: string) => router.push({ pathname: '/store/[slug]', params: { slug } });

/** Tarjeta grande para los carruseles: foto, etiqueta de descuento y abajo logo, nombre, nota, demora y envío. */
export function StoreTile({ store, width = 290 }: { store: Store; width?: number }) {
  return (
    <Pressable style={({ pressed }) => [{ width }, pressed && { opacity: 0.85 }]} onPress={() => openStore(store.slug)} accessibilityLabel={`Abrir ${store.name}`}>
      <Cover store={store} style={[s.tileCover, !store.is_open && { opacity: 0.6 }]}>
        {!!store.max_discount && <DealBadge label={`Hasta ${store.max_discount}% OFF`} style={s.badgeTL} />}
        {!store.is_open && <View style={s.closed}><Text style={s.closedText}>{store.open_text || 'Cerrado'}</Text></View>}
      </Cover>
      <View style={s.tileFoot}>
        <StoreLogo store={store} size={54} />
        <View style={{ flex: 1, gap: 2 }}>
          <View style={s.rowBetween}>
            <Text style={s.name} numberOfLines={1}>{store.name}</Text>
            {store.rating !== null && <Rating value={store.rating} />}
          </View>
          <Meta store={store} compact />
        </View>
      </View>
    </Pressable>
  );
}

/** Logo grande sobre la foto (para "Los más populares"). */
export function StoreBubble({ store }: { store: Store }) {
  return (
    <Pressable style={({ pressed }) => [{ width: 150, gap: 6 }, pressed && { opacity: 0.85 }]} onPress={() => openStore(store.slug)} accessibilityLabel={`Abrir ${store.name}`}>
      <Cover store={store} style={s.bubble}><View style={s.bubbleLogo}><StoreLogo store={store} size={62} /></View></Cover>
      <Text style={s.bubbleName} numberOfLines={1}>{store.name}</Text>
    </Pressable>
  );
}

/** Fila de comercio (listados y búsqueda): logo, nombre, nota, rubro, demora, envío y distancia. */
export function StoreRow({ store }: { store: Store }) {
  return (
    <Pressable style={({ pressed }) => [s.row, pressed && { opacity: 0.85 }, store.coverage.covered === false && { opacity: 0.7 }]} onPress={() => openStore(store.slug)} accessibilityLabel={`Abrir ${store.name}`}>
      <StoreLogo store={store} size={64} />
      <View style={{ flex: 1, gap: 3 }}>
        {(!store.delivery_enabled || !store.is_open) && (
          <View style={s.pillRow}>
            {!store.delivery_enabled && <View style={[s.pill, { backgroundColor: '#2F6FED' }]}><Text style={s.pillText}>Solo retiro en el local</Text></View>}
            {!store.is_open && <View style={[s.pill, { backgroundColor: colors.ink }]}><Text style={s.pillText}>{store.open_text || 'Cerrado'}</Text></View>}
          </View>
        )}
        <View style={s.rowBetween}><Text style={s.rowName} numberOfLines={1}>{store.name}</Text>{store.rating !== null && <Rating value={store.rating} />}</View>
        {!!store.category && <Text style={s.muted} numberOfLines={1}>{store.category}</Text>}
        <Meta store={store} />
        {!!store.max_discount && <DealBadge label={`Hasta ${store.max_discount}% OFF`} style={{ marginTop: 4 }} />}
      </View>
    </Pressable>
  );
}

export function Rating({ value }: { value: number }) {
  return <View style={s.metaRow}><Ionicons name="star" size={16} color={colors.ink} /><Text style={s.rating}>{value.toFixed(1).replace('.', ',')}</Text></View>;
}

/** Producto en carrusel: foto sobre gris, descuento, "+" sobre la foto, nombre y precio. */
export function ProductTile({ product, width = 150, showStore = true }: { product: Product; width?: number; showStore?: boolean }) {
  const off = product.previous_price ? Math.round((1 - product.price / product.previous_price) * 100) : 0;
  const open = () => router.push({ pathname: '/product/[id]', params: { id: String(product.id) } });
  return (
    <Pressable style={({ pressed }) => [{ width }, pressed && { opacity: 0.85 }]} onPress={open} accessibilityLabel={`Ver ${product.name}`} disabled={product.sold_out}>
      <View style={[s.pimg, { height: width }]}>
        {product.image_url ? <Image source={{ uri: product.image_url }} style={StyleSheet.absoluteFill} contentFit="cover" transition={150} />
          : <Ionicons name="restaurant-outline" size={34} color="#C4C0D0" />}
        {off > 0 && <DealBadge label={`${off}% OFF`} style={s.badgeTL} />}
        <View style={s.plus}><Ionicons name="add" size={24} color={colors.ink} /></View>
      </View>
      <Text style={s.pname} numberOfLines={2}>{product.name}</Text>
      <Text style={s.pprice}>{money(product.price)}</Text>
      {!!product.previous_price && <Text style={s.pdel}>{money(product.previous_price)}</Text>}
      {showStore && !!product.store && <Text style={s.muted} numberOfLines={1}>{product.store.name}</Text>}
    </Pressable>
  );
}

/** Título de sección con "Ver todos" opcional. */
export function Section({ title, action, onAction, children }: { title: string; action?: string; onAction?: () => void; children: ReactNode }) {
  return (
    <View style={{ marginTop: 26 }}>
      <View style={[s.rowBetween, { paddingHorizontal: 16, marginBottom: 12 }]}>
        <Text style={s.h2}>{title}</Text>
        {!!action && <Pressable onPress={onAction} hitSlop={10}><Text style={s.link}>{action}</Text></Pressable>}
      </View>
      {children}
    </View>
  );
}

export function Carousel({ children, gap = 14 }: { children: ReactNode; gap?: number }) {
  return <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ paddingHorizontal: 16, gap }}>{children}</ScrollView>;
}

/** Encabezado violeta: dirección, carrito y buscador (como la portada de la app). */
export function BrandHeader({ children, search = true, title }: { children?: ReactNode; search?: boolean; title?: string }) {
  const insets = useSafeAreaInsets();
  const { location, cartCount } = useApp();
  // sobre el violeta, la hora y la batería van en blanco (y se vuelven oscuras al salir)
  useFocusEffect(useCallback(() => { setStatusBarStyle('light'); return () => setStatusBarStyle('dark'); }, []));
  return (
    <View style={[s.header, { paddingTop: insets.top + 10 }]}>
      <View style={s.rowBetween}>
        {title ? <Text style={s.headerTitle}>{title}</Text> : (
          <Pressable style={s.addr} onPress={() => router.push('/location')} accessibilityLabel="Cambiar dirección de entrega" hitSlop={8}>
            <Text style={s.addrText} numberOfLines={1}>{location ? location.label : 'Elegí tu dirección'}</Text>
            <Ionicons name="chevron-down" size={22} color="#fff" />
          </Pressable>
        )}
        <Pressable onPress={() => router.push('/cart')} accessibilityLabel={`Mi pedido, ${cartCount} productos`} hitSlop={10} style={{ padding: 4 }}>
          <Ionicons name="cart-outline" size={28} color="#fff" />
          {cartCount > 0 && <View style={s.cartBadge}><Text style={s.cartBadgeText}>{cartCount}</Text></View>}
        </Pressable>
      </View>
      {search && (
        <Pressable style={s.search} onPress={() => router.navigate('/search')} accessibilityRole="search" accessibilityLabel="Buscar">
          <Text style={s.searchText}>Comercios, platos y productos</Text>
          <View style={s.searchBtn}><Ionicons name="search" size={20} color="#fff" /></View>
        </Pressable>
      )}
      {children}
    </View>
  );
}

/** Acceso grande con ícono (rubros, "Trappi AI"). */
export function Tile({ label, icon, emoji, onPress, wide }: { label: string; icon?: React.ComponentProps<typeof Ionicons>['name']; emoji?: string; onPress: () => void; wide?: boolean }) {
  return (
    <Pressable style={({ pressed }) => [wide ? s.tileWide : s.tileSmall, pressed && { opacity: 0.8 }]} onPress={onPress} accessibilityRole="button" accessibilityLabel={label}>
      <View style={wide ? s.tileWideIcon : s.tileIcon}>
        {icon ? <Ionicons name={icon} size={wide ? 40 : 32} color={colors.brand} /> : <Text style={{ fontSize: wide ? 44 : 34 }}>{emoji}</Text>}
      </View>
      <Text style={wide ? s.tileWideLabel : s.tileLabel} numberOfLines={2}>{label}</Text>
    </Pressable>
  );
}

export const s = StyleSheet.create({
  rowBetween: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  h2: { fontSize: 22, fontWeight: '800', color: colors.ink, letterSpacing: -0.4, flex: 1 },
  link: { color: colors.brand, fontWeight: '700', fontSize: 15 },
  muted: { color: colors.muted, fontSize: 14 },
  deal: { backgroundColor: '#FFE14D', paddingHorizontal: 10, paddingVertical: 5, borderRadius: radius.pill, alignSelf: 'flex-start' },
  dealText: { color: colors.ink, fontWeight: '800', fontSize: 13.5 },
  badgeTL: { position: 'absolute', top: 12, left: 12 },
  logo: { alignItems: 'center', justifyContent: 'center', overflow: 'hidden', borderWidth: 1, borderColor: colors.line },
  logoText: { color: '#fff', fontWeight: '800' },
  tileCover: { height: 168, borderRadius: radius.lg },
  closed: { position: 'absolute', bottom: 12, left: 12, backgroundColor: 'rgba(27,18,48,.85)', paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill },
  closedText: { color: '#fff', fontWeight: '700', fontSize: 12.5 },
  tileFoot: { flexDirection: 'row', gap: 12, marginTop: 12, alignItems: 'flex-start' },
  name: { fontSize: 17, fontWeight: '800', color: colors.ink, flex: 1 },
  metaWrap: { gap: 3 },
  metaRow: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  meta: { fontSize: 14.5, color: colors.ink },
  free: { color: colors.brand, fontWeight: '800' },
  rating: { fontSize: 15, fontWeight: '800', color: colors.ink },
  bubble: { width: 150, height: 104, borderRadius: radius.lg, alignItems: 'center', justifyContent: 'center' },
  bubbleLogo: { shadowColor: '#000', shadowOpacity: 0.15, shadowRadius: 8, shadowOffset: { width: 0, height: 3 }, elevation: 3, borderRadius: 18 },
  bubbleName: { fontSize: 14, fontWeight: '700', color: colors.ink },
  row: { flexDirection: 'row', gap: 14, paddingHorizontal: 16, paddingVertical: 14, backgroundColor: '#fff' },
  rowName: { fontSize: 18, fontWeight: '800', color: colors.ink, flex: 1 },
  pillRow: { flexDirection: 'row', gap: 6, flexWrap: 'wrap' },
  pill: { paddingHorizontal: 9, paddingVertical: 3, borderRadius: radius.pill },
  pillText: { color: '#fff', fontWeight: '700', fontSize: 12.5 },
  pimg: { borderRadius: radius.lg, backgroundColor: '#F2F1F5', overflow: 'hidden', alignItems: 'center', justifyContent: 'center' },
  plus: { position: 'absolute', right: 8, bottom: 8, width: 38, height: 38, borderRadius: 19, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center', shadowColor: '#000', shadowOpacity: 0.15, shadowRadius: 6, shadowOffset: { width: 0, height: 2 }, elevation: 3 },
  pname: { fontSize: 15, color: colors.ink, marginTop: 8, lineHeight: 20 },
  pprice: { fontSize: 17, fontWeight: '800', color: colors.ink, marginTop: 2 },
  pdel: { fontSize: 13.5, color: colors.muted, textDecorationLine: 'line-through' },
  header: { backgroundColor: colors.brand, paddingHorizontal: 16, paddingBottom: 18, borderBottomLeftRadius: 24, borderBottomRightRadius: 24, gap: 14 },
  headerTitle: { color: '#fff', fontSize: 22, fontWeight: '800', flex: 1 },
  addr: { flexDirection: 'row', alignItems: 'center', gap: 4, flex: 1 },
  addrText: { color: '#fff', fontWeight: '800', fontSize: 20, flexShrink: 1 },
  cartBadge: { position: 'absolute', top: -2, right: -4, minWidth: 18, height: 18, borderRadius: 9, backgroundColor: '#FFE14D', alignItems: 'center', justifyContent: 'center', paddingHorizontal: 4 },
  cartBadgeText: { color: colors.ink, fontWeight: '800', fontSize: 11 },
  search: { flexDirection: 'row', alignItems: 'center', backgroundColor: '#fff', borderRadius: radius.pill, paddingLeft: 18, paddingRight: 5, height: 52 },
  searchText: { flex: 1, color: colors.muted, fontSize: 16 },
  searchBtn: { width: 42, height: 42, borderRadius: 21, backgroundColor: colors.brand, alignItems: 'center', justifyContent: 'center' },
  tileWide: { flex: 1, backgroundColor: '#F2F1F5', borderRadius: radius.lg, padding: 14, alignItems: 'center', gap: 8, minHeight: 130, justifyContent: 'center' },
  tileWideIcon: { height: 56, alignItems: 'center', justifyContent: 'center' },
  tileWideLabel: { fontSize: 17, fontWeight: '800', color: colors.ink, textAlign: 'center' },
  tileSmall: { width: 104, alignItems: 'center', gap: 8 },
  tileIcon: { width: 104, height: 92, borderRadius: radius.lg, backgroundColor: '#F2F1F5', alignItems: 'center', justifyContent: 'center' },
  tileLabel: { fontSize: 14, fontWeight: '700', color: colors.ink, textAlign: 'center' },
});
