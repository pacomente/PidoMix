import { Image } from 'expo-image';
import { Link } from 'expo-router';
import type { ReactNode } from 'react';
import { ActivityIndicator, Alert, Pressable, StyleSheet, Text, View, type StyleProp, type ViewStyle } from 'react-native';

import { km, money, placeholderColor } from '@/lib/format';
import { colors, radius } from '@/lib/theme';
import type { Product, Store } from '@/lib/types';

export function Button({ title, onPress, variant = 'primary', disabled, loading, style }: {
  title: string; onPress?: () => void; variant?: 'primary' | 'secondary' | 'ghost' | 'danger'; disabled?: boolean; loading?: boolean; style?: StyleProp<ViewStyle>;
}) {
  const v = buttonVariants[variant];
  return (
    <Pressable accessibilityRole="button" accessibilityState={{ disabled: !!disabled || !!loading }} onPress={onPress} disabled={disabled || loading}
      style={({ pressed }) => [s.button, { backgroundColor: v.bg, borderColor: v.border }, (disabled || loading) && { opacity: 0.5 }, pressed && { opacity: 0.85 }, style]}>
      {loading ? <ActivityIndicator color={v.fg} /> : <Text style={[s.buttonText, { color: v.fg }]}>{title}</Text>}
    </Pressable>
  );
}
const buttonVariants = {
  primary: { bg: colors.brand, fg: '#fff', border: colors.brand },
  secondary: { bg: colors.brandSoft, fg: colors.brand, border: colors.brandSoft },
  ghost: { bg: 'transparent', fg: colors.ink, border: colors.line },
  danger: { bg: 'transparent', fg: colors.bad, border: colors.bad },
};

export function Chip({ label, tone = 'neutral' }: { label: string; tone?: 'neutral' | 'good' | 'bad' | 'brand' | 'warn' }) {
  const t = { neutral: [colors.bg, colors.ink], good: [colors.goodSoft, colors.good], bad: [colors.badSoft, colors.bad], brand: [colors.brandSoft, colors.brand], warn: [colors.warnSoft, colors.warn] }[tone];
  return <View style={[s.chip, { backgroundColor: t[0] }]}><Text style={[s.chipText, { color: t[1] }]}>{label}</Text></View>;
}

/** Foto si hay, si no un fondo pastel con el emoji del rubro (igual que la web). */
export function Thumb({ uri, emoji, hue, size, style, emojiSize }: { uri: string | null; emoji: string; hue: number; size?: number; style?: StyleProp<ViewStyle>; emojiSize?: number }) {
  const box = [size ? { width: size, height: size } : null, { backgroundColor: placeholderColor(hue), alignItems: 'center' as const, justifyContent: 'center' as const, overflow: 'hidden' as const }, style];
  return (
    <View style={box}>
      {uri ? <Image source={{ uri }} style={StyleSheet.absoluteFill} contentFit="cover" transition={150} /> : <Text style={{ fontSize: emojiSize ?? (size ? size * 0.5 : 44) }}>{emoji}</Text>}
    </View>
  );
}

export function deliveryText(st: Store): { text: string; tone: 'good' | 'bad' | 'neutral' } {
  const c = st.coverage;
  if (!st.delivery_enabled) return { text: 'Solo retiro', tone: 'neutral' };
  if (c.covered === false) return { text: 'No llega a tu ubicación', tone: 'bad' };
  if (c.cost !== null) return c.cost === 0 ? { text: 'Envío gratis', tone: 'good' } : { text: `Envío ${money(c.cost)}`, tone: 'neutral' };
  return { text: `Envío desde ${money(c.from_cost)}`, tone: 'neutral' };
}

export function StoreCard({ store }: { store: Store }) {
  const d = deliveryText(store);
  return (
    <Link href={{ pathname: '/store/[slug]', params: { slug: store.slug } }} asChild>
      <Pressable style={({ pressed }) => [s.card, pressed && { opacity: 0.9 }, store.coverage.covered === false && { opacity: 0.75 }]} accessibilityLabel={`Abrir ${store.name}`}>
        <Thumb uri={store.cover_url} emoji={store.emoji} hue={store.hue} style={s.cover} emojiSize={52} />
        {store.featured && <View style={s.tagFeat}><Text style={s.tagFeatText}>★ Destacado</Text></View>}
        {!store.is_open && <View style={s.tagClosed}><Text style={s.tagClosedText}>{store.open_text || 'Cerrado'}</Text></View>}
        <View style={s.cardBody}>
          <View style={s.row}>
            <Text style={s.cardTitle} numberOfLines={1}>{store.name}</Text>
            {store.rating !== null && <Text style={s.rating}>★ {store.rating.toFixed(1)}</Text>}
          </View>
          <Text style={s.muted} numberOfLines={1}>{[store.category, store.description].filter(Boolean).join(' · ') || 'Comercio'}</Text>
          <View style={[s.row, { marginTop: 8, flexWrap: 'wrap', gap: 10, justifyContent: 'flex-start' }]}>
            <Text style={s.meta}>🕒 {store.eta_min}–{store.eta_max} min</Text>
            {store.coverage.distance_km !== null && <Text style={s.meta}>📍 {km(store.coverage.distance_km)}</Text>}
            <Text style={[s.meta, d.tone === 'good' && { color: colors.good }, d.tone === 'bad' && { color: colors.bad }]}>{d.text}</Text>
            {store.minimum_order > 0 && <Text style={s.meta}>Mín. {money(store.minimum_order)}</Text>}
          </View>
        </View>
      </Pressable>
    </Link>
  );
}

export function Price({ price, previous }: { price: number; previous: number | null }) {
  return (
    <View style={[s.row, { justifyContent: 'flex-start', gap: 6 }]}>
      {previous !== null && <Text style={s.del}>{money(previous)}</Text>}
      <Text style={s.price}>{money(price)}</Text>
      {previous !== null && <Chip label={`-${Math.round((1 - price / previous) * 100)}%`} tone="bad" />}
    </View>
  );
}

export function ProductRow({ product, onAdd, disabled }: { product: Product; onAdd: () => void; disabled?: boolean }) {
  return (
    <Pressable onPress={disabled ? undefined : onAdd} style={({ pressed }) => [s.prow, pressed && !disabled && { opacity: 0.85 }, product.sold_out && { opacity: 0.55 }]} accessibilityRole="button" accessibilityLabel={`Agregar ${product.name}`}>
      <View style={{ flex: 1, gap: 3 }}>
        <Text style={s.prowTitle}>{product.name}</Text>
        {!!product.description && <Text style={s.muted} numberOfLines={2}>{product.description}</Text>}
        <View style={[s.row, { justifyContent: 'flex-start', gap: 8, marginTop: 4, flexWrap: 'wrap' }]}>
          <Price price={product.price} previous={product.previous_price} />
          {product.customizable && <Chip label="Personalizable" tone="brand" />}
          {product.sold_out && <Chip label="Sin stock" tone="bad" />}
        </View>
      </View>
      {product.image_url && <Thumb uri={product.image_url} emoji={product.emoji} hue={product.hue} size={88} style={{ borderRadius: 12 }} />}
      <View style={[s.add, disabled && { backgroundColor: '#CFC7DE' }]}><Text style={s.addText}>+</Text></View>
    </Pressable>
  );
}

export const statusTone = (status: string) =>
  status === 'CANCELADO' ? 'bad' : status === 'ENTREGADO' ? 'good' : status === 'PENDIENTE' ? 'warn' : 'brand';

/** Confirma antes de vaciar un pedido de otro comercio (sólo se pide en un local a la vez). */
export function confirmReplace(currentStore: string, onConfirm: () => void) {
  Alert.alert('¿Empezar un pedido nuevo?', `Ya tenés productos de ${currentStore}. Si seguís, se vacía ese pedido.`, [
    { text: 'Cancelar', style: 'cancel' },
    { text: 'Vaciar y agregar', style: 'destructive', onPress: onConfirm },
  ]);
}

export function Loading() {
  return <View style={s.center}><ActivityIndicator size="large" color={colors.brand} /></View>;
}

export function Empty({ emoji, title, text, action }: { emoji: string; title: string; text?: string; action?: ReactNode }) {
  return (
    <View style={s.empty}>
      <Text style={{ fontSize: 46 }}>{emoji}</Text>
      <Text style={s.emptyTitle}>{title}</Text>
      {!!text && <Text style={[s.muted, { textAlign: 'center' }]}>{text}</Text>}
      {action}
    </View>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return <Empty emoji="📡" title="No pudimos cargar esto" text={message} action={<Button title="Reintentar" onPress={onRetry} style={{ marginTop: 12 }} />} />;
}

export function SectionTitle({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return <View style={[s.row, { marginTop: 22, marginBottom: 10 }]}><Text style={s.h2}>{children}</Text>{right}</View>;
}

export const s = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  h1: { fontSize: 26, fontWeight: '800', color: colors.ink, letterSpacing: -0.5 },
  h2: { fontSize: 20, fontWeight: '800', color: colors.ink, letterSpacing: -0.3 },
  muted: { color: colors.muted, fontSize: 14 },
  button: { minHeight: 50, borderRadius: radius.pill, paddingHorizontal: 20, alignItems: 'center', justifyContent: 'center', borderWidth: 1.5 },
  buttonText: { fontWeight: '800', fontSize: 16 },
  chip: { paddingHorizontal: 9, paddingVertical: 3, borderRadius: radius.pill, alignSelf: 'flex-start' },
  chipText: { fontSize: 12.5, fontWeight: '700' },
  card: { backgroundColor: colors.card, borderRadius: radius.md, overflow: 'hidden', borderWidth: 1, borderColor: colors.line, marginBottom: 14 },
  cover: { height: 130 },
  cardBody: { padding: 14, gap: 2 },
  cardTitle: { fontSize: 17, fontWeight: '800', color: colors.ink, flex: 1, marginRight: 8 },
  rating: { fontWeight: '800', color: colors.warn, backgroundColor: colors.warnSoft, paddingHorizontal: 8, paddingVertical: 2, borderRadius: radius.pill, overflow: 'hidden', fontSize: 13 },
  meta: { fontSize: 13, fontWeight: '600', color: colors.ink },
  tagFeat: { position: 'absolute', top: 10, left: 10, backgroundColor: '#fff', paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill },
  tagFeatText: { color: colors.brand, fontWeight: '800', fontSize: 12 },
  tagClosed: { position: 'absolute', top: 10, right: 10, backgroundColor: 'rgba(27,18,48,.85)', paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill },
  tagClosedText: { color: '#fff', fontWeight: '700', fontSize: 12 },
  price: { fontSize: 16, fontWeight: '800', color: colors.ink },
  del: { fontSize: 13, color: colors.muted, textDecorationLine: 'line-through' },
  prow: { flexDirection: 'row', gap: 12, backgroundColor: colors.card, borderRadius: radius.md, padding: 14, borderWidth: 1, borderColor: colors.line, marginBottom: 10, alignItems: 'center' },
  prowTitle: { fontSize: 15.5, fontWeight: '700', color: colors.ink },
  add: { width: 38, height: 38, borderRadius: 19, backgroundColor: colors.brand, alignItems: 'center', justifyContent: 'center', alignSelf: 'flex-end' },
  addText: { color: '#fff', fontSize: 24, fontWeight: '700', lineHeight: 26 },
  empty: { alignItems: 'center', padding: 32, gap: 6 },
  emptyTitle: { fontSize: 18, fontWeight: '800', color: colors.ink, textAlign: 'center' },
});
