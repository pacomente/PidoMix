import Ionicons from '@expo/vector-icons/Ionicons';
import * as Haptics from 'expo-haptics';
import { Image } from 'expo-image';
import { router, Stack, useLocalSearchParams } from 'expo-router';
import { setStatusBarStyle } from 'expo-status-bar';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Linking, Pressable, RefreshControl, ScrollView, SectionList, StyleSheet, Text, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Grad, Ill, lookOf, RubroCover } from '@/components/kit';
import { StoreBadge, shipText } from '@/components/store-card';
import { confirmReplace, ErrorState, Loading } from '@/components/ui';
import { api } from '@/lib/api';
import { openWebPage } from '@/lib/auth';
import { km, money } from '@/lib/format';
import { colors } from '@/lib/theme';
import type { CartLine, Product, StampCard, Store } from '@/lib/types';
import { useFetch } from '@/lib/useFetch';
import { useApp } from '@/state/app-state';

type Row = Product | Product[];
type Kind = 'menu' | 'grid' | 'night';
const offOf = (p: Product) => (p.previous_price && p.previous_price > p.price ? Math.round((1 - p.price / p.previous_price) * 100) : 0);
const COVER = 220;

/**
 * La tienda según su rubro: restaurante (portada con vida, ficha flotante, los más pedidos y la carta), súper / carnicería
 * (góndola con categorías ilustradas, ofertas y envío gratis a la vista) o kiosco de noche (oscuro, categorías grandes y lista).
 */
export default function StoreScreen() {
  const { slug } = useLocalSearchParams<{ slug: string }>();
  const insets = useSafeAreaInsets();
  const { location, cart, cartCount, addToCart, setQuantity, favorites, toggleFavorite } = useApp();
  const res = useFetch(() => api.store(slug, location), [slug, location?.lat, location?.lng]);
  const list = useRef<SectionList<Row>>(null);
  const [q, setQ] = useState('');
  const [solid, setSolid] = useState(false);
  const [active, setActive] = useState(0);
  const input = useRef<TextInput>(null);
  const store = res.data?.store;
  const kind: Kind = store?.rubro === 'kiosco' ? 'night' : store?.catalog_style === 'grid' ? 'grid' : 'menu';
  useEffect(() => {
    if (kind === 'night' || !solid) { setStatusBarStyle('light'); return () => setStatusBarStyle('dark'); }
    setStatusBarStyle('dark');
  }, [kind, solid]);

  const menu = res.data?.menu;
  const sections = useMemo(() => {
    const term = q.trim().toLowerCase();
    return (menu ?? []).map(m => {
      const items = term ? m.products.filter(p => `${p.name} ${p.description ?? ''}`.toLowerCase().includes(term)) : m.products;
      // góndola: de a dos por fila; restaurante y kiosco: lista
      const data: Row[] = kind === 'grid' ? Array.from({ length: Math.ceil(items.length / 2) }, (_, i) => items.slice(i * 2, i * 2 + 2)) : items;
      return { key: m.key, title: m.title, emoji: m.emoji, data };
    }).filter(m => m.data.length);
  }, [menu, q, kind]);

  if (res.loading && !res.data) return <Loading />;
  if (res.error && !res.data) return <ErrorState message={res.error} onRetry={res.reload} />;
  const { reviews, rating_summary, stamp_card } = res.data!;
  const s = store!;
  const all = (menu ?? []).flatMap(m => m.products);
  const popular = (all.filter(p => p.featured && !p.sold_out).length >= 2 ? all.filter(p => p.featured && !p.sold_out) : all.filter(p => !p.sold_out)).slice(0, 8);
  const offers = all.filter(p => offOf(p) > 0 && !p.sold_out);
  const cartHere = cart.length > 0 && cart[0].store_slug === s.slug;
  const cartTotal = cartHere ? cart.reduce((n, x) => n + x.unit_price * x.quantity, 0) : 0;
  const canOrder = s.is_open || !!s.can_schedule;
  const fav = favorites.includes(s.slug);
  const dark = kind === 'night';
  const free = s.free_shipping_from && s.delivery_enabled ? s.free_shipping_from : null;
  const missing = free ? Math.max(0, free - cartTotal) : 0;

  const qtyOf = (p: Product) => (cartHere ? cart.filter(l => l.product_id === p.id && !l.modifiers.length && !l.grams).reduce((n, l) => n + l.quantity, 0) : 0);
  const add = (p: Product) => {
    if (p.customizable || p.weight) { router.push({ pathname: '/product/[id]', params: { id: String(p.id) } }); return; }
    const line: CartLine = { product_id: p.id, quantity: 1, modifiers: [], name: p.name, unit_price: p.price, modifiers_text: null, store_slug: s.slug, store_name: s.name };
    const done = () => Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
    if (addToCart(line) === 'other_store') confirmReplace(cart[0].store_name, () => { addToCart(line, true); done(); });
    else done();
  };
  const less = (p: Product) => {
    const i = cart.findIndex(l => l.product_id === p.id && !l.modifiers.length && !l.grams);
    if (i >= 0) setQuantity(i, cart[i].quantity - 1);
  };
  const jump = (i: number) => { setActive(i); list.current?.scrollToLocation({ sectionIndex: i, itemIndex: 0, viewOffset: insets.top + 70, animated: true }); };
  const back = () => (router.canGoBack() ? router.back() : router.replace('/'));
  const tileProps = { canOrder, qtyOf, add, less };

  const header = (
    <View>
      {/* portada: foto del local o el degradado del rubro con sus ilustraciones */}
      {s.cover_url && !dark ? (
        <View style={{ height: COVER + insets.top }}><Image source={{ uri: s.cover_url }} style={StyleSheet.absoluteFill} contentFit="cover" /></View>
      ) : (
        <RubroCover rubro={s.rubro} emoji={s.emoji} big={dark ? 60 : 74} lift={dark ? 0 : 56} style={{ height: (dark ? 250 : COVER) + insets.top, paddingTop: insets.top + 64, paddingHorizontal: 18 }}>
          {dark && (
            <View>
              <Text style={st.nightName} numberOfLines={2}>{s.name}</Text>
              <Text style={st.nightMeta}>{s.rating !== null ? `★ ${s.rating.toFixed(1).replace('.', ',')} · ` : ''}{s.is_open ? (s.description || 'Abierto ahora') : s.open_text || 'Cerrado'}</Text>
              <View style={st.nightEta}><Text style={st.nightEtaText}>⚡ Llega en {s.eta_min}–{s.eta_max} min</Text></View>
            </View>
          )}
        </RubroCover>
      )}

      {!dark && <InfoCard store={s} kind={kind} rating={rating_summary.count ? rating_summary.avg : null} count={rating_summary.count} free={free} cartTotal={cartTotal} />}
      <Notices store={s} dark={dark} />
      {!!stamp_card && <View style={{ paddingHorizontal: 16 }}><Stamps card={stamp_card} /></View>}

      {/* buscador del local */}
      <View style={[st.search, dark && { backgroundColor: '#231C35' }]}>
        <Ill e="🔍" size={18} />
        <TextInput ref={input} value={q} onChangeText={setQ} placeholder={`Buscar en ${s.name}`} placeholderTextColor={dark ? '#A9A3BC' : colors.muted} style={[st.searchInput, dark && { color: '#fff' }]} returnKeyType="search" accessibilityLabel="Buscar en el local" />
        {!!q && <Pressable onPress={() => setQ('')} hitSlop={10} accessibilityLabel="Borrar"><Ionicons name="close-circle" size={20} color={colors.muted} /></Pressable>}
      </View>

      {!q && kind === 'menu' && popular.length >= 2 && (
        <View>
          <View style={st.secHead}><Text style={st.h2}>Los más pedidos</Text><Text style={st.small}>esta semana</Text></View>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={st.hscroll}>
            {popular.map((p, i) => <PopularTile key={p.id} p={p} rank={i} accent={lookOf(s.rubro, s.emoji).soft} onAdd={() => add(p)} disabled={!canOrder || p.sold_out} />)}
          </ScrollView>
        </View>
      )}

      {!q && kind === 'grid' && (
        <View>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={[st.hscroll, { paddingTop: 16 }]}>
            {offers.length > 0 && <CatBubble e="🔥" label="Ofertas" on onPress={() => undefined} />}
            {sections.map((sec, i) => <CatBubble key={sec.key} e={sec.emoji || '🛒'} label={sec.title} onPress={() => jump(i)} />)}
          </ScrollView>
          {offers.length > 0 && (
            <>
              <View style={st.secHead}><Text style={st.h2}>Ofertas de la semana</Text><Text style={st.link}>{offers.length} productos</Text></View>
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={st.hscroll}>
                {offers.map(p => <View key={p.id} style={{ width: 156 }}><GondolaTile p={p} {...tileProps} /></View>)}
              </ScrollView>
            </>
          )}
        </View>
      )}

      {!q && dark && (
        <View>
          <View style={st.nightGrid}>
            {sections.slice(0, 8).map((sec, i) => (
              <Pressable key={sec.key} style={st.nightCell} onPress={() => jump(i)} accessibilityRole="button" accessibilityLabel={sec.title}>
                <View style={st.nightCellBox}><Ill e={sec.emoji || '🛒'} size={40} /><Text style={st.nightCellText} numberOfLines={1}>{sec.title}</Text></View>
              </Pressable>
            ))}
          </View>
          {!!offers[0] && <NightBanner p={offers[0]} onAdd={() => add(offers[0])} />}
          {popular.length > 0 && <Text style={[st.h2, st.nightH2]}>Lo más pedido de noche</Text>}
          {popular.slice(0, 4).map(p => <NightRow key={`pop-${p.id}`} p={p} section="" onAdd={() => add(p)} disabled={!canOrder || p.sold_out} />)}
        </View>
      )}

      {kind === 'menu' && sections.length > 1 && (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={st.tabs}>
          {sections.map((sec, i) => (
            <Pressable key={sec.key} onPress={() => jump(i)} style={[st.tab, active === i && st.tabOn]} accessibilityRole="tab" accessibilityState={{ selected: active === i }}>
              <Text style={[st.tabText, active === i && { color: colors.ink }]}>{sec.title}</Text>
            </Pressable>
          ))}
        </ScrollView>
      )}
    </View>
  );

  return (
    <View style={{ flex: 1, backgroundColor: dark ? '#14101F' : colors.bg }}>
      <Stack.Screen options={{ headerShown: false }} />
      <SectionList
        ref={list}
        sections={sections}
        keyExtractor={r => (Array.isArray(r) ? r.map(p => p.id).join('-') : String(r.id))}
        stickySectionHeadersEnabled={false}
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={{ paddingBottom: cartHere && cartCount ? 130 : 40 }}
        scrollEventThrottle={32}
        onScroll={e => { const y = e.nativeEvent.contentOffset.y; if (y > COVER - 60 !== solid) setSolid(!solid); }}
        onViewableItemsChanged={({ viewableItems }) => {
          const first = viewableItems.find(v => v.section);
          const i = first ? sections.findIndex(x => x.key === (first.section as { key: string }).key) : -1;
          if (i >= 0) setActive(i);
        }}
        onScrollToIndexFailed={() => {}}
        refreshControl={<RefreshControl refreshing={res.refreshing} onRefresh={res.refresh} tintColor={colors.brand} />}
        renderSectionHeader={({ section }) => <Text style={[st.h2, st.secTitle, dark && st.nightH2]}>{section.title}</Text>}
        renderItem={({ item, section }) => Array.isArray(item) ? (
          <View style={st.gridRow}>
            {item.map(p => <View key={p.id} style={{ flex: 1 }}><GondolaTile p={p} {...tileProps} /></View>)}
            {item.length === 1 && <View style={{ flex: 1 }} />}
          </View>
        ) : dark ? <NightRow p={item} section={section.title} onAdd={() => add(item)} disabled={!canOrder || item.sold_out} />
          : <MenuCard p={item} onAdd={() => add(item)} disabled={!canOrder || item.sold_out} />}
        ListHeaderComponent={header}
        ListEmptyComponent={<Text style={[st.empty, dark && { color: '#A9A3BC' }]}>{q ? `No hay productos con «${q.trim()}».` : 'Este local todavía no cargó sus productos.'}</Text>}
        ListFooterComponent={rating_summary.count > 0 ? <Reviews reviews={reviews} avg={rating_summary.avg} count={rating_summary.count} dark={dark} /> : null}
      />

      {/* arriba: volver, buscar y favorito; al bajar, una barra con el nombre */}
      <View style={[st.top, { paddingTop: insets.top + 6 }, solid && (dark ? st.topDark : st.topSolid)]} pointerEvents="box-none">
        <Pressable onPress={back} style={st.round} hitSlop={8} accessibilityLabel="Volver"><Ionicons name="chevron-back" size={22} color={colors.ink} /></Pressable>
        {solid ? <Text style={[st.topTitle, dark && { color: '#fff' }]} numberOfLines={1}>{s.name}</Text> : <View style={{ flex: 1 }} />}
        <Pressable onPress={() => input.current?.focus()} style={st.round} hitSlop={8} accessibilityLabel="Buscar en el local"><Ill e="🔍" size={18} /></Pressable>
        <Pressable onPress={() => toggleFavorite(s.slug)} style={st.round} hitSlop={8} accessibilityLabel={fav ? 'Sacar de favoritos' : 'Agregar a favoritos'}>
          <Ionicons name={fav ? 'heart' : 'heart-outline'} size={20} color={fav ? '#E11D48' : colors.ink} />
        </Pressable>
      </View>

      {cartHere && cartCount > 0 && (
        <Pressable onPress={() => router.push('/cart')} style={[st.cartBar, { bottom: insets.bottom + 12 }, dark && { backgroundColor: '#DB2777' }]} accessibilityLabel="Ver mi pedido">
          <View style={st.cartCount}><Text style={[st.cartCountText, dark && { color: '#DB2777' }]}>{cartCount}</Text></View>
          <View style={{ flex: 1 }}>
            <Text style={st.cartText}>Ver mi pedido</Text>
            {!!free && missing > 0 && <Text style={st.cartSub}>Te faltan {money(missing)} para el envío gratis</Text>}
            {!!free && missing === 0 && <Text style={st.cartSub}>¡Tenés envío gratis!</Text>}
          </View>
          <Text style={st.cartText}>{money(cartTotal)}</Text>
        </Pressable>
      )}
    </View>
  );
}

/** Ficha flotante: logo, nombre, nota y datos; restaurante con tres cajitas, góndola con la barra del envío gratis. */
function InfoCard({ store: s, kind, rating, count, free, cartTotal }: { store: Store; kind: Kind; rating: number | null; count: number; free: number | null; cartTotal: number }) {
  const boxes: [string, string, string?][] = [[`${s.eta_min}–${s.eta_max}'`, 'demora'], [shipText(s), s.delivery_enabled ? 'envío' : 'en el local'],
    s.coupon ? [s.coupon.replace(' OFF', ''), 'con el cupón', 'good'] : s.max_discount ? [`-${s.max_discount} %`, 'en productos', 'good'] : [s.minimum_order ? money(s.minimum_order) : 'Sin', 'pedido mínimo']];
  return (
    <View style={st.info}>
      <View style={st.infoHead}>
        <StoreBadge store={s} size={56} />
        <View style={{ flex: 1 }}>
          <Text style={st.infoName} numberOfLines={2}>{s.name}</Text>
          <Text style={st.infoMeta} numberOfLines={1}>
            {rating !== null ? <Text style={{ color: colors.ink, fontWeight: '800' }}><Text style={{ color: '#F59E0B' }}>★</Text> {rating.toFixed(1).replace('.', ',')} </Text> : null}
            {rating !== null ? `(${count})  ·  ` : ''}{kind === 'menu' ? (s.category || s.description || '') : `${s.eta_min}–${s.eta_max} min  ·  Envío ${shipText(s)}`}
          </Text>
        </View>
      </View>
      {kind === 'menu' ? (
        <View style={st.boxes}>
          {boxes.map(([big, small, tone]) => (
            <View key={small} style={[st.box, tone === 'good' && { backgroundColor: '#E6F8EE' }]}>
              <Text style={[st.boxBig, tone === 'good' && { color: colors.good }]} numberOfLines={1}>{big}</Text>
              <Text style={[st.boxSmall, tone === 'good' && { color: colors.good }]} numberOfLines={1}>{small}</Text>
            </View>
          ))}
        </View>
      ) : free ? (
        <View style={st.freeBox}>
          <Text style={st.freeText}>🛵 Gratis desde <Text style={{ fontWeight: '900' }}>{money(free)}</Text></Text>
          <View style={st.freeBar}><View style={[st.freeFill, { width: `${Math.max(6, Math.min(100, (cartTotal / free) * 100))}%` }]} /></View>
        </View>
      ) : null}
    </View>
  );
}

/** Avisos del local: cerrado (con programar), mucha demanda, no llega a tu dirección. */
function Notices({ store: s, dark }: { store: Store; dark: boolean }) {
  const c = s.coverage;
  const items: [string, string, string][] = [];
  if (!s.is_open) items.push(['🕒', s.can_schedule ? `${s.open_text || 'Cerrado ahora'}. Podés programar tu pedido.` : `${s.open_text || 'Cerrado'}. Por ahora no toma pedidos.`, '#EEF4FF']);
  if (s.is_open && s.busy) items.push(['⏱', `Mucha demanda: está tardando un poco más (${s.eta_min}–${s.eta_max} min).`, '#FFF7E6']);
  if (c.covered === false) items.push(['📍', `No llega a tu dirección${c.max_km ? ` (reparte hasta ${km(c.max_km)})` : ''}. Podés pedir para retirar.`, '#FDEDEA']);
  if (!items.length) return null;
  return (
    <View style={{ paddingHorizontal: 16, gap: 8, marginTop: dark ? 14 : 4 }}>
      {items.map(([e, t, bg]) => <View key={t} style={[st.notice, { backgroundColor: dark ? '#231C35' : bg }]}><Ill e={e} size={22} /><Text style={[st.noticeText, dark && { color: '#fff' }]}>{t}</Text></View>)}
      {!!s.whatsapp && <Pressable onPress={() => Linking.openURL(`https://wa.me/${s.whatsapp!.replace(/\D/g, '')}`)}><Text style={[st.link, { paddingLeft: 4 }]}>Consultar por WhatsApp</Text></Pressable>}
    </View>
  );
}

function CatBubble({ e, label, on, onPress }: { e: string; label: string; on?: boolean; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} style={{ width: 74, alignItems: 'center', gap: 6 }} accessibilityRole="button" accessibilityLabel={label}>
      <View style={[st.bubble, on && { backgroundColor: '#16A34A' }]}><Ill e={e} size={40} /></View>
      <Text style={st.bubbleText} numberOfLines={1}>{label}</Text>
    </Pressable>
  );
}

/** Tile de góndola: ilustración, descuento, «+» o la cantidad (−2+), precio (por kg o L), nombre y precio por unidad. */
function GondolaTile({ p, canOrder, qtyOf, add, less }: { p: Product; canOrder: boolean; qtyOf: (p: Product) => number; add: (p: Product) => void; less: (p: Product) => void }) {
  const off = offOf(p);
  const n = qtyOf(p);
  const disabled = !canOrder || p.sold_out;
  return (
    <Pressable onPress={disabled ? undefined : () => (p.customizable || p.weight ? add(p) : n ? undefined : add(p))} style={[st.gtile, p.sold_out && { opacity: 0.5 }]}
      accessibilityRole="button" accessibilityLabel={`${p.name}, ${money(p.price)}${p.weight ? ' el kilo' : ''}`}>
      <View style={[st.gimg, { backgroundColor: off ? '#FFF6E5' : '#F4F6FB' }]}>
        {p.image_url ? <Image source={{ uri: p.image_url }} style={StyleSheet.absoluteFill} contentFit="contain" /> : <Ill e={p.emoji === '🍽️' ? '🛒' : p.emoji} size={66} />}
        {off > 0 && <View style={st.off}><Text style={st.offText}>-{off}%</Text></View>}
        {n > 0 ? (
          <View style={st.stepper}>
            <Pressable onPress={() => less(p)} hitSlop={6} accessibilityLabel="Uno menos"><Text style={st.stepTxt}>−</Text></Pressable>
            <Text style={st.stepTxt}>{n}</Text>
            <Pressable onPress={() => add(p)} hitSlop={6} accessibilityLabel="Uno más"><Text style={st.stepTxt}>+</Text></Pressable>
          </View>
        ) : (
          <Pressable onPress={disabled ? undefined : () => add(p)} style={[st.gplus, disabled && { opacity: 0.5 }]} accessibilityLabel={`Agregar ${p.name}`}><Ionicons name="add" size={22} color={colors.brand} /></Pressable>
        )}
      </View>
      <View style={{ flexDirection: 'row', alignItems: 'baseline', gap: 5, flexWrap: 'wrap' }}>
        <Text style={st.gprice}>{money(p.price)}{!!p.weight && <Text style={st.gkg}> /kg</Text>}</Text>
        {off > 0 && <Text style={st.prev}>{money(p.previous_price)}</Text>}
      </View>
      <Text style={st.gname} numberOfLines={2}>{p.name}</Text>
      {p.sold_out ? <Text style={st.soldout}>Sin stock</Text>
        : p.weight ? <View style={st.kgTag}><Text style={st.kgTagText}>⚖ elegís cuánto</Text></View>
        : !!p.unit_price_text && <Text style={st.unit}>{p.unit_price_text}</Text>}
    </Pressable>
  );
}

/** «Los más pedidos»: tarjeta con el puesto (#1), descuento y «+». */
function PopularTile({ p, rank, accent, onAdd, disabled }: { p: Product; rank: number; accent: string; onAdd: () => void; disabled: boolean }) {
  const off = offOf(p);
  return (
    <Pressable onPress={disabled ? undefined : onAdd} style={st.ptile} accessibilityRole="button" accessibilityLabel={`Agregar ${p.name}`}>
      <View style={[st.pimg, { backgroundColor: accent }]}>
        {p.image_url ? <Image source={{ uri: p.image_url }} style={StyleSheet.absoluteFill} contentFit="cover" /> : <Ill e={p.emoji} size={80} />}
        {rank === 0 ? <View style={st.rank}><Text style={st.rankText}>🔥 #1</Text></View> : off > 0 ? <View style={st.rank}><Text style={[st.rankText, { color: '#E11D48' }]}>-{off}%</Text></View> : null}
        <View style={[st.pplus, disabled && { opacity: 0.5 }]}><Ionicons name="add" size={22} color="#fff" /></View>
      </View>
      <Text style={st.pname} numberOfLines={1}>{p.name}</Text>
      <Text style={st.pprice}>{money(p.price)}</Text>
    </Pressable>
  );
}

/** Restaurante: tarjeta del plato con la foto o ilustración y «+». */
function MenuCard({ p, onAdd, disabled }: { p: Product; onAdd: () => void; disabled: boolean }) {
  const off = offOf(p);
  return (
    <Pressable onPress={disabled ? undefined : onAdd} style={({ pressed }) => [st.mcard, pressed && !disabled && { opacity: 0.9 }, p.sold_out && { opacity: 0.5 }]}
      accessibilityRole="button" accessibilityLabel={`Agregar ${p.name}, ${money(p.price)}`}>
      <View style={{ flex: 1, gap: 3 }}>
        <Text style={st.mname}>{p.name}</Text>
        {!!p.description && <Text style={st.mdesc} numberOfLines={2}>{p.description}</Text>}
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 4 }}>
          <Text style={st.mprice}>{money(p.price)}{!!p.weight && <Text style={st.gkg}> /kg</Text>}</Text>
          {off > 0 && <Text style={st.prev}>{money(p.previous_price)}</Text>}
        </View>
        {p.sold_out ? <Text style={st.soldout}>Sin stock</Text> : !!p.hours_text && <Text style={[st.small, { color: '#1F4FB8' }]}>{p.hours_text}</Text>}
        {!!p.model_3d_path && (
          <Pressable onPress={() => openWebPage(p.model_3d_path!)} style={st.view3d} hitSlop={6} accessibilityRole="button" accessibilityLabel={`Ver ${p.name} en 3D sobre tu mesa`}>
            <Ionicons name="cube-outline" size={15} color={colors.brand} /><Text style={st.view3dText}>Ver en 3D · en tu mesa</Text>
          </Pressable>
        )}
      </View>
      <View style={st.mimg}>
        {p.image_url ? <Image source={{ uri: p.image_url }} style={StyleSheet.absoluteFill} contentFit="cover" /> : <Ill e={p.emoji} size={62} />}
        <View style={[st.mplus, disabled && { opacity: 0.5 }]}><Ionicons name="add" size={20} color={colors.brand} /></View>
      </View>
    </Pressable>
  );
}

/** Kiosco de noche: el destacado en un banner violeta-fucsia. */
function NightBanner({ p, onAdd }: { p: Product; onAdd: () => void }) {
  return (
    <Pressable onPress={onAdd} style={{ marginHorizontal: 16, marginTop: 16 }} accessibilityRole="button" accessibilityLabel={`Agregar ${p.name}`}>
      <Grad colors={['#7C3AED', '#DB2777']} style={st.nbanner}>
        <Ill e={p.emoji} size={58} />
        <View style={{ flex: 1 }}>
          <Text style={st.nbTitle} numberOfLines={1}>{p.name}</Text>
          <Text style={st.nbSub} numberOfLines={1}>{p.description || 'Destacado de la noche'}</Text>
        </View>
        <View style={st.nbPrice}><Text style={st.nbPriceText}>{money(p.price)}</Text></View>
      </Grad>
    </Pressable>
  );
}

function NightRow({ p, section, onAdd, disabled }: { p: Product; section: string; onAdd: () => void; disabled: boolean }) {
  return (
    <Pressable onPress={disabled ? undefined : onAdd} style={[st.nrow, p.sold_out && { opacity: 0.5 }]} accessibilityRole="button" accessibilityLabel={`Agregar ${p.name}, ${money(p.price)}`}>
      <View style={st.nimg}>{p.image_url ? <Image source={{ uri: p.image_url }} style={StyleSheet.absoluteFill} contentFit="cover" /> : <Ill e={p.emoji === '🍽️' ? '🛒' : p.emoji} size={36} />}</View>
      <View style={{ flex: 1 }}>
        <Text style={st.nname} numberOfLines={1}>{p.name}</Text>
        <Text style={st.nsub} numberOfLines={1}>{p.sold_out ? 'Sin stock' : section || p.description || ''}</Text>
      </View>
      <Text style={st.nprice}>{money(p.price)}</Text>
      <View style={[st.nplus, disabled && { opacity: 0.5 }]}><Ionicons name="add" size={20} color="#fff" /></View>
    </Pressable>
  );
}

/** Tarjeta de sellos del local: cuántos lleva el cliente y el premio (sin cuenta: cómo se juntan). */
function Stamps({ card }: { card: StampCard }) {
  const have = card.mine?.stamps ?? 0;
  return (
    <View style={st.stamps} accessibilityLabel={`Tarjeta de sellos: ${have} de ${card.goal}. Premio: ${card.reward}`}>
      <Text style={st.stampsTitle}>⭐ Juntá {card.goal} sellos: {card.reward}</Text>
      <View style={st.dots}>
        {Array.from({ length: card.goal }, (_, i) => <View key={i} style={[st.dot, i < have && st.dotOn]}>{i < have && <Ionicons name="star" size={13} color="#fff" />}</View>)}
      </View>
      <Text style={st.stampsText}>
        {card.mine
          ? card.mine.rewards ? `¡Tenés ${card.mine.rewards === 1 ? 'un premio' : `${card.mine.rewards} premios`} para usar! Se aplica solo en tu próximo pedido acá.`
            : `Te ${card.mine.missing === 1 ? 'falta 1 sello' : `faltan ${card.mine.missing} sellos`}. Cada pedido entregado${card.min_order ? ` desde ${money(card.min_order)}` : ''} suma uno.`
          : `Cada pedido entregado${card.min_order ? ` desde ${money(card.min_order)}` : ''} suma un sello. Ingresá con tu cuenta para juntarlos.`}
      </Text>
    </View>
  );
}

function Reviews({ reviews, avg, count, dark }: { reviews: { id: number; author: string; rating: number; comment: string | null; reply: string | null }[]; avg: number; count: number; dark: boolean }) {
  return (
    <View style={{ marginTop: 18 }}>
      <View style={st.secHead}><Text style={[st.h2, dark && { color: '#fff' }]}>Opiniones</Text><Text style={[st.h2, { fontSize: 16 }, dark && { color: '#fff' }]}><Text style={{ color: '#F59E0B' }}>★</Text> {avg.toFixed(1).replace('.', ',')} ({count})</Text></View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={st.hscroll}>
        {reviews.map(r => (
          <View key={r.id} style={st.review}>
            <Text style={st.revAuthor} numberOfLines={1}>{r.author} <Text style={{ color: '#F59E0B' }}>{'★'.repeat(r.rating)}</Text></Text>
            {!!r.comment && <Text style={st.revText} numberOfLines={4}>{r.comment}</Text>}
            {!!r.reply && <Text style={st.revReply} numberOfLines={3}>Respuesta del local: {r.reply}</Text>}
          </View>
        ))}
      </ScrollView>
    </View>
  );
}

const st = StyleSheet.create({
  top: { position: 'absolute', left: 0, right: 0, top: 0, flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 14, paddingBottom: 8 },
  topSolid: { backgroundColor: '#fff', borderBottomWidth: 1, borderBottomColor: colors.line },
  topDark: { backgroundColor: '#14101F', borderBottomWidth: 1, borderBottomColor: '#2E2645' },
  topTitle: { flex: 1, fontSize: 17, fontWeight: '900', color: colors.ink },
  round: { width: 42, height: 42, borderRadius: 21, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center', shadowColor: '#000', shadowOpacity: 0.12, shadowRadius: 6, shadowOffset: { width: 0, height: 2 }, elevation: 3 },
  info: { marginTop: -54, marginHorizontal: 16, backgroundColor: '#fff', borderRadius: 24, padding: 14, gap: 12,
    shadowColor: '#1E143C', shadowOpacity: 0.12, shadowRadius: 18, shadowOffset: { width: 0, height: 8 }, elevation: 5 },
  infoHead: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  infoName: { fontSize: 22, fontWeight: '900', color: colors.ink, letterSpacing: -0.6 },
  infoMeta: { fontSize: 13, color: colors.muted, marginTop: 2 },
  boxes: { flexDirection: 'row', gap: 8 },
  box: { flex: 1, backgroundColor: '#F4F3F8', borderRadius: 14, paddingVertical: 8, paddingHorizontal: 10 },
  boxBig: { fontSize: 15.5, fontWeight: '900', color: colors.ink },
  boxSmall: { fontSize: 11.5, color: colors.muted, fontWeight: '700' },
  freeBox: { backgroundColor: '#F0FDF4', borderRadius: 14, padding: 10, gap: 6 },
  freeText: { color: '#15803D', fontWeight: '700', fontSize: 13.5 },
  freeBar: { height: 7, borderRadius: 9, backgroundColor: '#DCFCE7', overflow: 'hidden' },
  freeFill: { height: '100%', borderRadius: 9, backgroundColor: '#16A34A' },
  notice: { flexDirection: 'row', alignItems: 'center', gap: 10, padding: 12, borderRadius: 16 },
  noticeText: { flex: 1, color: colors.ink, fontWeight: '600', fontSize: 13.5 },
  search: { flexDirection: 'row', alignItems: 'center', gap: 10, marginHorizontal: 16, marginTop: 16, backgroundColor: '#fff', borderRadius: 16, paddingHorizontal: 14, height: 46, borderWidth: 1, borderColor: colors.line },
  searchInput: { flex: 1, fontSize: 15.5, color: colors.ink },
  secHead: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 16, marginTop: 20, marginBottom: 10 },
  h2: { fontSize: 20, fontWeight: '900', color: colors.ink, letterSpacing: -0.5 },
  secTitle: { paddingHorizontal: 16, marginTop: 20, marginBottom: 10 },
  small: { color: colors.muted, fontSize: 12.5, fontWeight: '700' },
  link: { color: colors.brand, fontWeight: '800', fontSize: 13.5 },
  hscroll: { paddingHorizontal: 16, gap: 10 },
  tabs: { paddingHorizontal: 16, gap: 18, marginTop: 18, borderBottomWidth: 1, borderBottomColor: colors.line },
  tab: { paddingVertical: 10, borderBottomWidth: 3, borderBottomColor: 'transparent' },
  tabOn: { borderBottomColor: colors.brand },
  tabText: { fontWeight: '800', color: '#9A93A8', fontSize: 15 },
  empty: { color: colors.muted, paddingHorizontal: 16, marginTop: 24, textAlign: 'center' },
  bubble: { width: 64, height: 64, borderRadius: 32, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: colors.line },
  bubbleText: { fontSize: 12.5, fontWeight: '800', color: colors.ink },
  gridRow: { flexDirection: 'row', gap: 10, paddingHorizontal: 16, marginBottom: 10 },
  gtile: { backgroundColor: '#fff', borderRadius: 20, padding: 8, gap: 2 },
  gimg: { aspectRatio: 1.15, borderRadius: 14, alignItems: 'center', justifyContent: 'center', overflow: 'hidden', marginBottom: 6 },
  off: { position: 'absolute', top: 6, left: 6, backgroundColor: '#E11D48', borderRadius: 8, paddingHorizontal: 6, paddingVertical: 2 },
  offText: { color: '#fff', fontWeight: '900', fontSize: 11.5 },
  gplus: { position: 'absolute', right: 6, bottom: 6, width: 34, height: 34, borderRadius: 17, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center',
    shadowColor: '#000', shadowOpacity: 0.14, shadowRadius: 5, shadowOffset: { width: 0, height: 2 }, elevation: 2 },
  stepper: { position: 'absolute', right: 6, bottom: 6, flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: colors.brand, borderRadius: 99, paddingHorizontal: 12, height: 34 },
  stepTxt: { color: '#fff', fontWeight: '900', fontSize: 16 },
  gprice: { fontSize: 17, fontWeight: '900', color: colors.ink, letterSpacing: -0.4 },
  gkg: { fontSize: 12, fontWeight: '800', color: colors.muted },
  prev: { fontSize: 12, color: colors.muted, textDecorationLine: 'line-through' },
  gname: { fontSize: 13.5, color: colors.ink, lineHeight: 17 },
  unit: { fontSize: 11.5, color: colors.muted, marginTop: 2 },
  kgTag: { alignSelf: 'flex-start', backgroundColor: '#FFF7E6', borderRadius: 8, paddingHorizontal: 7, paddingVertical: 2, marginTop: 3 },
  kgTagText: { fontSize: 11.5, fontWeight: '800', color: '#92400E' },
  soldout: { color: colors.bad, fontWeight: '800', fontSize: 12.5 },
  ptile: { width: 150, backgroundColor: '#fff', borderRadius: 20, padding: 8 },
  pimg: { height: 112, borderRadius: 16, alignItems: 'center', justifyContent: 'center', overflow: 'hidden' },
  rank: { position: 'absolute', top: 6, left: 6, backgroundColor: '#fff', borderRadius: 99, paddingHorizontal: 8, paddingVertical: 2 },
  rankText: { fontWeight: '900', fontSize: 11.5, color: colors.ink },
  pplus: { position: 'absolute', right: 6, bottom: 6, width: 34, height: 34, borderRadius: 17, backgroundColor: colors.brand, alignItems: 'center', justifyContent: 'center' },
  pname: { fontWeight: '800', color: colors.ink, marginTop: 8, fontSize: 14 },
  pprice: { fontWeight: '900', color: colors.ink, fontSize: 16 },
  mcard: { flexDirection: 'row', gap: 12, marginHorizontal: 16, marginBottom: 10, padding: 12, backgroundColor: '#fff', borderRadius: 20 },
  mname: { fontSize: 16, fontWeight: '900', color: colors.ink },
  mdesc: { color: colors.muted, fontSize: 13, lineHeight: 18 },
  mprice: { fontSize: 16.5, fontWeight: '900', color: colors.ink },
  mimg: { width: 96, height: 96, borderRadius: 16, backgroundColor: '#FFF3E2', alignItems: 'center', justifyContent: 'center', overflow: 'hidden' },
  mplus: { position: 'absolute', right: 5, bottom: 5, width: 30, height: 30, borderRadius: 15, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center',
    shadowColor: '#000', shadowOpacity: 0.14, shadowRadius: 4, shadowOffset: { width: 0, height: 1 }, elevation: 2 },
  view3d: { flexDirection: 'row', alignItems: 'center', gap: 5, alignSelf: 'flex-start', marginTop: 4, paddingHorizontal: 9, paddingVertical: 4, borderRadius: 99, backgroundColor: colors.brandSoft },
  view3dText: { color: colors.brand, fontWeight: '800', fontSize: 12.5 },
  nightName: { color: '#fff', fontSize: 28, fontWeight: '900', letterSpacing: -0.8, marginRight: 120 },
  nightMeta: { color: 'rgba(255,255,255,.85)', fontSize: 13.5, marginTop: 4 },
  nightEta: { alignSelf: 'flex-start', backgroundColor: '#fff', borderRadius: 99, paddingHorizontal: 12, paddingVertical: 6, marginTop: 12 },
  nightEtaText: { color: '#DB2777', fontWeight: '900', fontSize: 13.5 },
  nightGrid: { flexDirection: 'row', flexWrap: 'wrap', paddingHorizontal: 11, marginTop: 18, rowGap: 10 },
  nightCell: { width: '25%', paddingHorizontal: 5 },
  nightCellBox: { backgroundColor: '#231C35', borderRadius: 18, paddingVertical: 12, alignItems: 'center', gap: 6, borderWidth: 1, borderColor: '#2E2645' },
  nightCellText: { color: '#fff', fontWeight: '800', fontSize: 12 },
  nightH2: { color: '#fff', paddingHorizontal: 16, marginTop: 20, marginBottom: 10 },
  nbanner: { flexDirection: 'row', alignItems: 'center', gap: 12, borderRadius: 22, padding: 14 },
  nbTitle: { color: '#fff', fontWeight: '900', fontSize: 18 },
  nbSub: { color: 'rgba(255,255,255,.85)', fontSize: 12.5 },
  nbPrice: { backgroundColor: '#fff', borderRadius: 14, paddingHorizontal: 12, paddingVertical: 8 },
  nbPriceText: { color: colors.ink, fontWeight: '900', fontSize: 15 },
  nrow: { flexDirection: 'row', alignItems: 'center', gap: 12, marginHorizontal: 16, marginBottom: 8, padding: 10, backgroundColor: '#1E1830', borderRadius: 18, borderWidth: 1, borderColor: '#2E2645' },
  nimg: { width: 50, height: 50, borderRadius: 14, backgroundColor: '#2A2340', alignItems: 'center', justifyContent: 'center', overflow: 'hidden' },
  nname: { color: '#fff', fontWeight: '800', fontSize: 15 },
  nsub: { color: '#A9A3BC', fontSize: 12.5 },
  nprice: { color: '#fff', fontWeight: '900', fontSize: 15.5 },
  nplus: { width: 34, height: 34, borderRadius: 17, backgroundColor: '#DB2777', alignItems: 'center', justifyContent: 'center' },
  stamps: { marginTop: 12, padding: 14, borderRadius: 18, backgroundColor: '#FFF6DE', gap: 8 },
  stampsTitle: { fontSize: 15, fontWeight: '900', color: colors.ink },
  stampsText: { color: colors.muted, fontSize: 13 },
  dots: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  dot: { width: 24, height: 24, borderRadius: 12, borderWidth: 2, borderColor: colors.star, alignItems: 'center', justifyContent: 'center', backgroundColor: '#fff' },
  dotOn: { backgroundColor: colors.star },
  review: { width: 250, backgroundColor: '#fff', borderRadius: 18, padding: 12, gap: 6 },
  revAuthor: { fontWeight: '800', color: colors.ink },
  revText: { color: colors.ink, lineHeight: 19, fontSize: 13.5 },
  revReply: { color: colors.brand, fontSize: 12.5 },
  cartBar: { position: 'absolute', left: 16, right: 16, flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: colors.brand, borderRadius: 20, paddingHorizontal: 14, paddingVertical: 12,
    shadowColor: colors.brand, shadowOpacity: 0.45, shadowRadius: 14, shadowOffset: { width: 0, height: 6 }, elevation: 8 },
  cartCount: { backgroundColor: '#fff', width: 32, height: 32, borderRadius: 10, alignItems: 'center', justifyContent: 'center' },
  cartCountText: { color: colors.brand, fontWeight: '900' },
  cartText: { color: '#fff', fontWeight: '900', fontSize: 16 },
  cartSub: { color: 'rgba(255,255,255,.85)', fontSize: 12, fontWeight: '600' },
});
