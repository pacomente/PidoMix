import Ionicons from '@expo/vector-icons/Ionicons';
import { Image } from 'expo-image';
import { router } from 'expo-router';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Ill, lookOf, RubroCover } from '@/components/kit';
import { money } from '@/lib/format';
import { colors } from '@/lib/theme';
import type { Store } from '@/lib/types';
import { useApp } from '@/state/app-state';

const open = (slug: string) => router.push({ pathname: '/store/[slug]', params: { slug } });

/** Envío: "Gratis", "$1.200" o "Retiro". */
export const shipText = (s: Store) => (!s.delivery_enabled ? 'Retiro' : s.coverage.cost === 0 ? 'Gratis' : money(s.coverage.cost ?? s.coverage.from_cost ?? s.delivery_cost));

/** Logo del local: su foto o la ilustración de su rubro sobre un fondo suave. */
export function StoreBadge({ store, size = 46 }: { store: Store; size?: number }) {
  const l = lookOf(store.rubro, store.emoji);
  return (
    <View style={[st.badge, { width: size, height: size, borderRadius: size * 0.3, backgroundColor: store.logo_url ? '#fff' : l.soft }]}>
      {store.logo_url ? <Image source={{ uri: store.logo_url }} style={StyleSheet.absoluteFill} contentFit="cover" /> : <Ill e={l.ills[l.ills.length - 1]} size={size * 0.72} />}
    </View>
  );
}

/** Tarjeta grande: portada del rubro con etiquetas (descuento, demora, corazón) y abajo logo, nombre y datos. */
export function BigStoreCard({ store, tags = true }: { store: Store; tags?: boolean }) {
  const { favorites, toggleFavorite } = useApp();
  const fav = favorites.includes(store.slug);
  const free = store.free_shipping_from;
  return (
    <Pressable onPress={() => open(store.slug)} style={({ pressed }) => [st.card, pressed && { transform: [{ scale: 0.98 }] }, !store.is_open && { opacity: 0.75 }]} accessibilityRole="button" accessibilityLabel={`Abrir ${store.name}`}>
      {store.cover_url ? (
        <View style={st.cover}><Image source={{ uri: store.cover_url }} style={StyleSheet.absoluteFill} contentFit="cover" /></View>
      ) : <RubroCover rubro={store.rubro} emoji={store.emoji} style={st.cover} big={62} />}
      {tags && (
        <View style={st.tags} pointerEvents="box-none">
          {!!store.max_discount && <View style={[st.tag, { backgroundColor: '#fff' }]}><Text style={[st.tagText, { color: '#E11D48' }]}>-{store.max_discount}%</Text></View>}
          {!!free && store.delivery_enabled && <View style={[st.tag, { backgroundColor: '#fff' }]}><Text style={[st.tagText, { color: '#15803D' }]}>🛵 Gratis +{money(free)}</Text></View>}
          {store.is_open ? <View style={[st.tag, { backgroundColor: '#fff' }]}><Text style={st.tagText}>⚡ {store.eta_min} min</Text></View>
            : <View style={[st.tag, { backgroundColor: 'rgba(26,21,35,.85)' }]}><Text style={[st.tagText, { color: '#fff' }]}>{store.schedule_hint || store.open_text || 'Cerrado'}</Text></View>}
        </View>
      )}
      <Pressable onPress={() => toggleFavorite(store.slug)} hitSlop={8} style={st.heart} accessibilityLabel={fav ? 'Sacar de favoritos' : 'Agregar a favoritos'}>
        <Ionicons name={fav ? 'heart' : 'heart-outline'} size={19} color={fav ? '#E11D48' : colors.ink} />
      </Pressable>
      <View style={st.foot}>
        <View style={st.logoWrap}><StoreBadge store={store} size={44} /></View>
        <View style={{ flex: 1 }}>
          <Text style={st.name} numberOfLines={1}>{store.name}</Text>
          <Text style={st.meta} numberOfLines={1}>
            {store.rating !== null ? <Text style={{ color: colors.ink, fontWeight: '800' }}><Text style={{ color: '#F59E0B' }}>★</Text> {store.rating.toFixed(1).replace('.', ',')}</Text> : 'Nuevo'}
            {'  ·  '}{store.eta_min}–{store.eta_max} min{'  ·  '}{shipText(store)}
          </Text>
        </View>
      </View>
    </Pressable>
  );
}

/** Tarjeta chica de color (carrusel «De noche, en minutos»). */
export function MiniStoreCard({ store }: { store: Store }) {
  return (
    <Pressable onPress={() => open(store.slug)} style={{ width: 140 }} accessibilityRole="button" accessibilityLabel={`Abrir ${store.name}`}>
      <RubroCover rubro={store.rubro} emoji={store.emoji} style={st.mini} big={40} />
      <Text style={st.miniName} numberOfLines={1}>{store.name}</Text>
      <Text style={st.miniMeta}>{store.eta_min}–{store.eta_max} min · {shipText(store)}</Text>
    </Pressable>
  );
}

const st = StyleSheet.create({
  card: { marginHorizontal: 16, marginBottom: 14, borderRadius: 22, backgroundColor: '#fff', overflow: 'hidden',
    shadowColor: '#1E143C', shadowOpacity: 0.1, shadowRadius: 14, shadowOffset: { width: 0, height: 5 }, elevation: 3 },
  cover: { height: 122 },
  tags: { position: 'absolute', top: 10, left: 10, right: 54, flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  tag: { borderRadius: 99, paddingHorizontal: 9, paddingVertical: 4 },
  tagText: { fontWeight: '900', fontSize: 12, color: colors.ink },
  heart: { position: 'absolute', top: 10, right: 10, width: 34, height: 34, borderRadius: 17, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center' },
  foot: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 14, paddingBottom: 12, paddingTop: 10 },
  logoWrap: { marginTop: -30, borderRadius: 16, borderWidth: 3, borderColor: '#fff', backgroundColor: '#fff' },
  badge: { alignItems: 'center', justifyContent: 'center', overflow: 'hidden' },
  name: { fontSize: 17, fontWeight: '900', color: colors.ink, letterSpacing: -0.3 },
  meta: { fontSize: 13, color: colors.muted, marginTop: 1 },
  mini: { height: 96, borderRadius: 18 },
  miniName: { fontWeight: '800', color: colors.ink, marginTop: 6, fontSize: 14 },
  miniMeta: { color: colors.muted, fontSize: 12 },
});
