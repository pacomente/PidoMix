import Ionicons from '@expo/vector-icons/Ionicons';
import { router, useFocusEffect } from 'expo-router';
import { setStatusBarStyle } from 'expo-status-bar';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Linking, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Grad, Ill, lookOf } from '@/components/kit';
import { Carousel, openRubro, ProductTile, Section } from '@/components/market';
import { BigStoreCard, MiniStoreCard } from '@/components/store-card';
import { Empty, ErrorState, Loading } from '@/components/ui';
import { api } from '@/lib/api';
import { weightLabel } from '@/lib/cart';
import { money } from '@/lib/format';
import { useRepeat } from '@/lib/repeat';
import { load } from '@/lib/storage';
import { colors } from '@/lib/theme';
import type { Home, Order, Store } from '@/lib/types';
import { useFetch } from '@/lib/useFetch';
import { useApp } from '@/state/app-state';

type Quick = 'fast' | 'promos' | 'free';
const NIGHT_RUBROS = ['kiosco', 'farmacia', 'bebidas', 'heladeria'];

export default function HomeScreen() {
  const insets = useSafeAreaInsets();
  const { location, ready, city, setCity, account, orders, cartCount } = useApp();
  const [pickCity, setPickCity] = useState(false);
  const [quick, setQuick] = useState<Quick | null>(null);
  const [slide, setSlide] = useState(0);
  const home = useFetch(() => api.home(location), [location?.lat, location?.lng, city]);
  const config = useFetch(() => api.config(), []);
  // retención: "Hace 7 días pediste... ¿Querés pedir de nuevo?" y su descuento de Trappi (lo decide el servidor)
  const comeback = useFetch(() => (account ? api.myOffer().catch(() => null) : Promise.resolve(null)), [account?.id]);
  // Trappi Viajes: el módulo aparece si está prendido y hay empresas en la ciudad; con un viaje activo, el acceso directo
  const rides = useFetch(() => (config.data?.rides?.enabled ? api.ridesAvailable(location).catch(() => null) : Promise.resolve(null)),
    [config.data?.rides?.enabled, location?.lat, location?.lng, city]);
  const errands = useFetch(() => (config.data?.errands?.enabled ? api.errandsConfig(location).catch(() => null) : Promise.resolve(null)),
    [config.data?.errands?.enabled, location?.lat, location?.lng, city]);
  const activeRide = useFetch(() => (account && rides.data?.enabled ? api.rideCurrent().then(r => r.ride).catch(() => null) : Promise.resolve(null)),
    [account?.id, rides.data?.enabled]);
  const forYou = useFetch(() => (account && account.personalize !== false ? api.recommendations(location).catch(() => null) : Promise.resolve(null)),
    [account?.id, account?.personalize, location?.lat, location?.lng, city]);
  // «Pedí de nuevo»: su último pedido entregado (de los últimos 90 días) con lo que sigue a la venta
  const refs = orders.slice(0, 10).map(o => ({ id: o.id, token: o.token }));
  const again = useFetch(() => (refs.length ? api.orders(refs).then(r => r.orders.find(o => o.status === 'ENTREGADO'
    && Date.now() - new Date(o.created_at).getTime() < 90 * 864e5 && o.items.some(i => i.available)) ?? null).catch(() => null) : Promise.resolve(null)),
    [refs.map(r => r.id).join(',')]);
  const repeat = useRepeat();
  useFocusEffect(useCallback(() => { setStatusBarStyle('light'); return () => setStatusBarStyle('dark'); }, []));

  // la primera vez que se abre la app: la bienvenida (solo clientes nuevos, una vez)
  useEffect(() => {
    if (!ready) return;
    load<boolean>('welcomed', false).then(w => { if (!w && !account && !orders.length) router.push('/welcome'); });
  }, [ready]); // eslint-disable-line react-hooks/exhaustive-deps

  const d = home.data;
  const stores = useMemo(() => d?.stores ?? [], [d]);
  const near = useMemo(() => {
    let list = [...stores];
    if (quick === 'fast') list = list.filter(s => s.is_open).sort((a, b) => a.eta_min - b.eta_min);
    if (quick === 'promos') list = list.filter(s => s.max_discount || s.coupon);
    if (quick === 'free') list = list.filter(s => s.delivery_enabled && (s.coverage.cost === 0 || s.free_shipping_from));
    return list;
  }, [stores, quick]);
  const night = useMemo(() => stores.filter(s => NIGHT_RUBROS.includes(s.rubro || '') && s.is_open), [stores]);
  const storeOf = useMemo(() => new Map(stores.map(s => [s.slug, s])), [stores]);

  if (!ready || (home.loading && !d)) return <Loading />;
  if (home.error && !d) return <ErrorState message={home.error} onRetry={home.reload} />;
  const data = d!;
  const cats = data.store_categories;
  const big = ['restaurante', 'super'].map(k => cats.find(c => c.key === k)).filter(Boolean) as Home['store_categories'];
  const small = cats.filter(c => !big.includes(c)).slice(0, 8);
  const sub = (c: Home['store_categories'][number]) => {
    const here = stores.filter(s => s.category === c.name);
    if (c.key === 'super' && here.some(s => s.coverage.cost === 0 || s.free_shipping_from)) return 'Envío gratis';
    const openN = here.filter(s => s.is_open).length;
    return here.length ? `${openN} ${openN === 1 ? 'abierto' : 'abiertos'}` : 'Muy pronto';
  };
  const promos = promoSlides(data, stores);

  return (
    <ScrollView style={{ backgroundColor: colors.bg }} contentContainerStyle={{ paddingBottom: 28 }}
      refreshControl={<RefreshControl refreshing={home.refreshing} onRefresh={home.refresh} tintColor={colors.brand} />}>
      <Grad colors={['#7C3AED', '#6C2BD9']} style={[st.head, { paddingTop: insets.top + 10 }]}>
        <View style={st.headGlow} />
        <View style={st.headRow}>
          <Pressable onPress={() => router.push('/location')} style={{ flex: 1 }} accessibilityLabel="Cambiar dirección de entrega" hitSlop={8}>
            <Text style={st.deliver}>Entregar en</Text>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
              <Text style={st.addr} numberOfLines={1}>{location ? location.label : 'Elegí tu dirección'}</Text>
              <Ionicons name="caret-down" size={14} color="#fff" />
            </View>
          </Pressable>
          <Pressable onPress={() => router.navigate('/orders')} style={[st.hbtn, { backgroundColor: '#FFD43B' }]} accessibilityLabel="Mis pedidos y avisos"><Ill e="🔔" size={24} /></Pressable>
          <Pressable onPress={() => router.push('/cart')} style={st.hbtn} accessibilityLabel={`Mi pedido, ${cartCount} productos`}>
            <Ill e="🛒" size={24} />
            {cartCount > 0 && <View style={st.badge}><Text style={st.badgeText}>{cartCount}</Text></View>}
          </Pressable>
        </View>
        <Pressable style={st.search} onPress={() => router.navigate('/search')} accessibilityRole="search" accessibilityLabel="Buscar">
          <Ill e="🔍" size={22} /><Text style={st.searchText}>¿Qué querés pedir hoy?</Text>
        </Pressable>
        {!!data.cities?.length && data.city && (
          <View style={{ marginTop: 10, gap: 8 }}>
            <Pressable style={st.cityBtn} onPress={() => setPickCity(v => !v)} accessibilityLabel="Cambiar de ciudad">
              <Ionicons name="business-outline" size={14} color="#fff" /><Text style={st.cityText}>{data.city.name}</Text>
              <Ionicons name={pickCity ? 'chevron-up' : 'chevron-down'} size={13} color="#fff" />
            </Pressable>
            {pickCity && (
              <View style={st.cityList}>
                {data.cities!.map(c => (
                  <Pressable key={c.id} onPress={() => { setCity(c.slug); setPickCity(false); }} style={[st.cityChip, data.city?.id === c.id && { backgroundColor: '#fff' }]}>
                    <Text style={[st.cityText, data.city?.id === c.id && { color: colors.brand }]}>{c.name}</Text>
                  </Pressable>
                ))}
              </View>
            )}
          </View>
        )}
      </Grad>

      {/* rubros con ilustración: los más usados en grande */}
      <View style={st.rubros}>
        {big.length > 0 && (
          <View style={st.bigRow}>
            {big.map(c => (
              <Pressable key={c.id} style={st.bigCat} onPress={() => openRubro(c)} accessibilityRole="button" accessibilityLabel={c.name}>
                <Ill e={c.key === 'restaurante' ? '🍔' : '🛒'} size={44} />
                <View style={{ flex: 1 }}><Text style={st.bigName} numberOfLines={1}>{c.name}</Text><Text style={st.bigSub} numberOfLines={1}>{sub(c)}</Text></View>
              </Pressable>
            ))}
          </View>
        )}
        <View style={st.grid}>
          {small.map(c => (
            <Pressable key={c.id} style={st.cell} onPress={() => openRubro(c)} accessibilityRole="button" accessibilityLabel={c.name}>
              <View style={st.cellBox}><Ill e={c.emoji} size={46} /></View>
              <Text style={st.cellText} numberOfLines={1}>{c.name}</Text>
            </Pressable>
          ))}
        </View>
      </View>

      {promos.length > 0 && (
        <View style={{ marginTop: 18 }}>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} snapToInterval={PROMO_W + 12} decelerationRate="fast" contentContainerStyle={{ paddingHorizontal: 16, gap: 12 }}
            onScroll={e => setSlide(Math.round(e.nativeEvent.contentOffset.x / (PROMO_W + 12)))} scrollEventThrottle={64}>
            {promos.map((p, i) => <PromoCard key={i} p={p} />)}
          </ScrollView>
          {promos.length > 1 && <View style={st.dots}>{promos.map((_, i) => <View key={i} style={[st.dot, i === slide && st.dotOn]} />)}</View>}
        </View>
      )}

      {!location && (
        <Pressable style={st.loc} onPress={() => router.push('/location')}>
          <Ill e="📍" size={30} />
          <Text style={{ flex: 1, color: colors.ink }}><Text style={{ fontWeight: '800' }}>¿Dónde recibís el pedido?</Text> Elegí tu dirección para ver qué locales llegan y cuánto sale el envío.</Text>
          <Ionicons name="chevron-forward" size={18} color={colors.brand} />
        </Pressable>
      )}

      {!!errands.data?.enabled && (
        <Pressable style={st.errand} onPress={() => router.push('/mandado')} accessibilityRole="button" accessibilityLabel="Mandados: mandá algo de un lugar a otro">
          <View style={{ flex: 1 }}>
            <Text style={st.errandTag}>NUEVO</Text>
            <Text style={st.errandTitle}>¿Tenés que mandar algo?</Text>
            <Text style={st.errandSub}>Llaves, documentos, un paquete o algo que te olvidaste. Lo retiramos y lo llevamos.</Text>
            <Text style={st.errandGo}>Mandar ahora →</Text>
          </View>
          <Ill e="📦" size={64} />
        </Pressable>
      )}

      {!!rides.data?.enabled && (
        <Pressable style={st.ride} onPress={() => (activeRide.data ? router.push({ pathname: '/ride/[id]', params: { id: String(activeRide.data.id) } }) : router.push('/ride'))} accessibilityRole="button">
          <Ill e="🚗" size={40} />
          <View style={{ flex: 1 }}>
            <Text style={st.rideTitle}>{activeRide.data ? 'Tenés un viaje en curso' : 'Trappi Viajes'}</Text>
            <Text style={st.rideSub}>{activeRide.data ? `${activeRide.data.label} · ${activeRide.data.company.name}` : 'Autos y motos de tu ciudad'}</Text>
          </View>
          <Ionicons name="chevron-forward" size={20} color="#fff" />
        </Pressable>
      )}

      {!!again.data && (
        <View style={{ marginTop: 22 }}>
          <Text style={st.h2}>Pedí de nuevo</Text>
          <AgainCard o={again.data} store={storeOf.get(again.data.store.slug)} onRepeat={() => repeat(again.data!)} />
        </View>
      )}
      {!!comeback.data?.voucher && (
        <View style={st.voucher}>
          <Ill e="🎟️" size={34} />
          <Text style={{ flex: 1, color: colors.ink }}><Text style={{ fontWeight: '800' }}>{comeback.data.voucher.text}</Text> Vence el {comeback.data.voucher.expires_text}. Se aplica solo al confirmar.</Text>
        </View>
      )}

      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={st.quick}>
        {([['fast', '⚡', 'Más rápidos'], ['promos', '🎫', 'Promos'], ['free', '🛵', 'Envío gratis']] as [Quick, string, string][]).map(([k, e, label]) => (
          <Pressable key={k} onPress={() => setQuick(q => (q === k ? null : k))} style={[st.qchip, quick === k && st.qchipOn]} accessibilityRole="checkbox" accessibilityState={{ checked: quick === k }}>
            <Ill e={e} size={18} /><Text style={[st.qtext, quick === k && { color: '#fff' }]}>{label}</Text>
          </Pressable>
        ))}
      </ScrollView>

      <View style={st.secHead}>
        <Text style={[st.h2, { paddingHorizontal: 0, marginBottom: 0 }]}>{location ? 'Cerca tuyo' : `En ${data.city?.name ?? 'tu zona'}`}</Text>
        <Pressable onPress={() => router.navigate('/search')} hitSlop={10}><Text style={st.link}>Ver todos</Text></Pressable>
      </View>
      {near.length ? near.slice(0, 6).map(s => <BigStoreCard key={s.id} store={s} />)
        : <Empty emoji="🏪" title={stores.length ? 'Ningún local con ese filtro' : 'Todavía no hay locales acá'} text={stores.length ? 'Probá con otro.' : 'Muy pronto vas a encontrar los locales de tu zona.'} />}

      {night.length > 0 && (
        <Section title="De noche, en minutos">
          <Carousel gap={12}>{night.map(s => <MiniStoreCard key={s.id} store={s} />)}</Carousel>
        </Section>
      )}
      {!!forYou.data?.items.length && (
        <Section title="Recomendado para vos">
          <Carousel>{forYou.data.items.map(p => <ProductTile key={p.id} product={p} caption={p.reason} />)}</Carousel>
        </Section>
      )}
      {data.promos.length > 0 && (
        <Section title="Ofertas de hoy" action="Ver todo" onAction={() => router.navigate('/promos')}>
          <Carousel>{data.promos.map(p => <ProductTile key={p.id} product={p} />)}</Carousel>
        </Section>
      )}
      {near.length > 6 && <View style={{ marginTop: 10 }}>{near.slice(6).map(s => <BigStoreCard key={s.id} store={s} />)}</View>}

      <Pressable style={st.scan} onPress={() => router.push('/scan')} accessibilityRole="button">
        <Ill e="📱" size={36} />
        <View style={{ flex: 1 }}>
          <Text style={{ fontWeight: '800', color: colors.ink }}>Escaneá el QR en el local</Text>
          <Text style={{ color: colors.muted, fontSize: 13 }}>Pedí desde la mesa, sumá Puntos Trappi con tu ticket o pagá con ellos</Text>
        </View>
        <Ionicons name="chevron-forward" size={20} color={colors.muted} />
      </Pressable>
    </ScrollView>
  );
}

const PROMO_W = 330;
type Promo = { title: string; sub: string; cta: string; e: string; grad: [string, string]; go: () => void };

/** Banners de promos: los que carga Trappi y, si no hay, los descuentos de los locales. */
function promoSlides(d: Home, stores: Store[]): Promo[] {
  const grads: [string, string][] = [['#F43F5E', '#BE123C'], ['#8B5CF6', '#5B21B6'], ['#F59E0B', '#C2410C']];
  const out: Promo[] = d.banners.map((b, i) => ({
    title: b.title || 'Descubrí Trappi', sub: b.subtitle || '', cta: b.button_text || 'Ver más', e: '🎁', grad: grads[i % grads.length],
    go: () => { if (b.link?.startsWith('/tienda/')) router.push({ pathname: '/store/[slug]', params: { slug: b.link.split('/')[2] } }); else if (b.link && /^https?:/.test(b.link)) Linking.openURL(b.link); },
  }));
  if (!out.length) {
    stores.filter(s => s.max_discount).sort((a, b) => (b.max_discount ?? 0) - (a.max_discount ?? 0)).slice(0, 3).forEach((s, i) => out.push({
      title: `Hasta ${s.max_discount}% OFF en ${s.name}`, sub: 'Pedilo con envío o para retirar', cta: 'Ver promos', e: lookOf(s.rubro, s.emoji).ills.slice(-1)[0],
      grad: grads[i % grads.length], go: () => router.push({ pathname: '/store/[slug]', params: { slug: s.slug } }),
    }));
  }
  return out;
}

function PromoCard({ p }: { p: Promo }) {
  return (
    <Pressable onPress={p.go} accessibilityRole="button" accessibilityLabel={p.title}>
      <Grad colors={p.grad} style={st.promo}>
        <View style={{ flex: 1, zIndex: 1 }}>
          <Text style={st.promoTitle} numberOfLines={3}>{p.title}</Text>
          {!!p.sub && <Text style={st.promoSub} numberOfLines={2}>{p.sub}</Text>}
          <View style={st.promoBtn}><Text style={st.promoBtnText}>{p.cta} ›</Text></View>
        </View>
        <Ill e={p.e} size={104} style={{ marginRight: -8 }} />
      </Grad>
    </Pressable>
  );
}

/** Su último pedido, para repetirlo en un toque. */
function AgainCard({ o, store, onRepeat }: { o: Order; store?: Store; onRepeat: () => void }) {
  const items = o.items.map(i => `${i.quantity}× ${i.name}${i.grams ? ` (${weightLabel(i.grams)})` : ''}`).join(', ');
  const l = lookOf(store?.rubro, store?.emoji);
  return (
    <View style={st.again}>
      <View style={[st.againIll, { backgroundColor: l.soft }]}><Ill e={l.ills[l.ills.length - 1]} size={38} /></View>
      <View style={{ flex: 1 }}>
        <Text style={st.againStore} numberOfLines={1}>{o.store.name}</Text>
        <Text style={st.againItems} numberOfLines={1}>{items} · {money(o.total)}</Text>
      </View>
      <Pressable style={st.againBtn} onPress={onRepeat} accessibilityRole="button" accessibilityLabel={`Repetir el pedido de ${o.store.name}`}>
        <Text style={st.againBtnText}>Repetir</Text>
      </Pressable>
    </View>
  );
}

const st = StyleSheet.create({
  head: { paddingHorizontal: 16, paddingBottom: 22, borderBottomLeftRadius: 30, borderBottomRightRadius: 30, overflow: 'hidden' },
  headGlow: { position: 'absolute', right: -80, top: -70, width: 250, height: 250, borderRadius: 125, backgroundColor: '#A855F7', opacity: 0.45 },
  headRow: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  deliver: { color: '#E9DDFF', fontSize: 13, fontWeight: '600' },
  addr: { color: '#fff', fontSize: 19, fontWeight: '900', flexShrink: 1, letterSpacing: -0.3 },
  hbtn: { width: 44, height: 44, borderRadius: 14, backgroundColor: 'rgba(255,255,255,.18)', alignItems: 'center', justifyContent: 'center' },
  badge: { position: 'absolute', top: -4, right: -4, minWidth: 18, height: 18, borderRadius: 9, backgroundColor: '#FFD43B', alignItems: 'center', justifyContent: 'center', paddingHorizontal: 4 },
  badgeText: { color: colors.ink, fontWeight: '900', fontSize: 11 },
  search: { marginTop: 14, flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: '#fff', borderRadius: 18, height: 54, paddingHorizontal: 16 },
  searchText: { color: colors.muted, fontSize: 16 },
  cityBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, alignSelf: 'flex-start', paddingHorizontal: 10, paddingVertical: 5, borderRadius: 99, backgroundColor: 'rgba(255,255,255,.18)' },
  cityText: { color: '#fff', fontWeight: '700', fontSize: 13 },
  cityList: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  cityChip: { paddingHorizontal: 12, paddingVertical: 7, borderRadius: 99, backgroundColor: 'rgba(255,255,255,.18)' },
  rubros: { paddingHorizontal: 16, marginTop: 16, gap: 10 },
  bigRow: { flexDirection: 'row', gap: 10 },
  bigCat: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: '#fff', borderRadius: 20, padding: 12,
    shadowColor: '#1E143C', shadowOpacity: 0.06, shadowRadius: 10, shadowOffset: { width: 0, height: 3 }, elevation: 1 },
  bigName: { fontWeight: '900', color: colors.ink, fontSize: 15.5 },
  bigSub: { color: colors.muted, fontSize: 12.5, marginTop: 1 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', marginHorizontal: -5, rowGap: 10 },
  cell: { width: '25%', paddingHorizontal: 5 },
  cellBox: { backgroundColor: '#fff', borderRadius: 20, aspectRatio: 1, alignItems: 'center', justifyContent: 'center',
    shadowColor: '#1E143C', shadowOpacity: 0.06, shadowRadius: 10, shadowOffset: { width: 0, height: 3 }, elevation: 1 },
  cellText: { fontSize: 12.5, fontWeight: '800', color: colors.ink, textAlign: 'center', marginTop: 6 },
  promo: { width: PROMO_W, height: 156, borderRadius: 24, padding: 18, flexDirection: 'row', alignItems: 'center', overflow: 'hidden' },
  promoTitle: { color: '#fff', fontSize: 21, fontWeight: '900', letterSpacing: -0.5, lineHeight: 24 },
  promoSub: { color: 'rgba(255,255,255,.88)', fontSize: 12.5, marginTop: 6 },
  promoBtn: { alignSelf: 'flex-start', backgroundColor: '#fff', borderRadius: 99, paddingHorizontal: 14, paddingVertical: 7, marginTop: 10 },
  promoBtnText: { color: colors.ink, fontWeight: '900', fontSize: 13 },
  dots: { flexDirection: 'row', justifyContent: 'center', gap: 5, marginTop: 10 },
  dot: { width: 7, height: 7, borderRadius: 4, backgroundColor: '#D9D3E6' },
  dotOn: { width: 20, backgroundColor: colors.brand },
  loc: { flexDirection: 'row', gap: 10, alignItems: 'center', marginHorizontal: 16, marginTop: 16, padding: 14, borderRadius: 20, backgroundColor: colors.brandSoft },
  errand: { flexDirection: 'row', alignItems: 'center', gap: 10, marginHorizontal: 16, marginTop: 16, padding: 16, borderRadius: 22, backgroundColor: colors.brand,
    borderWidth: 3, borderColor: '#FFD43B' },
  errandTag: { alignSelf: 'flex-start', backgroundColor: '#FFD43B', color: colors.ink, fontWeight: '900', fontSize: 10.5, paddingHorizontal: 8, paddingVertical: 2, borderRadius: 99, overflow: 'hidden', marginBottom: 6 },
  errandTitle: { color: '#fff', fontWeight: '900', fontSize: 19, letterSpacing: -0.3 },
  errandSub: { color: 'rgba(255,255,255,.85)', fontSize: 12.5, marginTop: 4 },
  errandGo: { alignSelf: 'flex-start', backgroundColor: '#FFD43B', color: colors.ink, fontWeight: '900', fontSize: 13, paddingHorizontal: 12, paddingVertical: 6, borderRadius: 99, overflow: 'hidden', marginTop: 10 },
  ride: { flexDirection: 'row', alignItems: 'center', gap: 12, marginHorizontal: 16, marginTop: 16, padding: 14, borderRadius: 20, backgroundColor: '#17112B' },
  rideTitle: { color: '#fff', fontWeight: '900', fontSize: 16 },
  rideSub: { color: 'rgba(255,255,255,.75)', fontSize: 13 },
  h2: { fontSize: 21, fontWeight: '900', color: colors.ink, letterSpacing: -0.5, paddingHorizontal: 16, marginBottom: 10 },
  again: { flexDirection: 'row', alignItems: 'center', gap: 12, marginHorizontal: 16, padding: 12, borderRadius: 20, backgroundColor: '#fff',
    shadowColor: '#1E143C', shadowOpacity: 0.07, shadowRadius: 12, shadowOffset: { width: 0, height: 4 }, elevation: 2 },
  againIll: { width: 52, height: 52, borderRadius: 16, alignItems: 'center', justifyContent: 'center' },
  againStore: { color: colors.ink, fontWeight: '900', fontSize: 16 },
  againItems: { color: colors.muted, fontSize: 13, marginTop: 1 },
  againBtn: { backgroundColor: colors.brand, borderRadius: 14, paddingHorizontal: 16, height: 40, alignItems: 'center', justifyContent: 'center' },
  againBtnText: { color: '#fff', fontWeight: '900' },
  voucher: { flexDirection: 'row', alignItems: 'center', gap: 12, marginHorizontal: 16, marginTop: 14, padding: 14, borderRadius: 20, backgroundColor: '#FFF8D6' },
  quick: { paddingHorizontal: 16, gap: 8, paddingTop: 20, paddingBottom: 6 },
  qchip: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 14, height: 40, borderRadius: 99, backgroundColor: '#fff', borderWidth: 1, borderColor: colors.line },
  qchipOn: { backgroundColor: colors.ink, borderColor: colors.ink },
  qtext: { fontWeight: '800', color: colors.ink, fontSize: 14 },
  secHead: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 16, marginTop: 14, marginBottom: 12 },
  link: { color: colors.brand, fontWeight: '800', fontSize: 14.5 },
  scan: { flexDirection: 'row', alignItems: 'center', gap: 12, marginHorizontal: 16, marginTop: 20, padding: 14, borderRadius: 20, backgroundColor: '#fff', borderWidth: 1, borderColor: colors.line },
});
