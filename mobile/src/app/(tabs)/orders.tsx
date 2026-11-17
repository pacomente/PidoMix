import Ionicons from '@expo/vector-icons/Ionicons';
import { Image } from 'expo-image';
import { Link, router, useFocusEffect } from 'expo-router';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { initials } from '@/components/market';
import { Button, Empty, ErrorState, Loading, confirmReplace } from '@/components/ui';
import { api } from '@/lib/api';
import { weightLabel } from '@/lib/cart';
import { money } from '@/lib/format';
import { colors, radius } from '@/lib/theme';
import type { CartLine, Order } from '@/lib/types';
import { useFetch } from '@/lib/useFetch';
import { useApp } from '@/state/app-state';

const MONTHS = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'];
const DAYS = ['dom', 'lun', 'mar', 'mié', 'jue', 'vie', 'sáb'];
const FILTERS = [{ key: 'all', label: 'Todos' }, { key: 'live', label: 'En curso' }, { key: 'done', label: 'Entregados' }, { key: 'cancel', label: 'Cancelados' }] as const;
type FilterKey = typeof FILTERS[number]['key'];

const statusColor = (o: Order) => (o.status === 'ENTREGADO' ? colors.good : o.status === 'CANCELADO' ? colors.bad : colors.brand);
const dayLabel = (iso: string) => { const d = new Date(iso); return `${DAYS[d.getDay()]} ${String(d.getDate()).padStart(2, '0')} de ${MONTHS[d.getMonth()].slice(0, 3).toLowerCase()}`; };

export default function OrdersScreen() {
  const insets = useSafeAreaInsets();
  const { orders, ready, account, rememberOrder, cart, replaceCart, customer, setCustomer } = useApp();
  const [filter, setFilter] = useState<FilterKey>('all');
  const refs = orders.map(o => ({ id: o.id, token: o.token }));
  const key = refs.map(r => r.id).join(',') + (account ? `|${account.id}` : '');
  // los pedidos guardados en el teléfono y, con cuenta, también los hechos desde otros dispositivos
  const res = useFetch(async () => {
    const [local, mine] = await Promise.all([
      refs.length ? api.orders(refs) : Promise.resolve({ orders: [] as Order[] }),
      account ? api.myOrders().catch(() => ({ orders: [] as Order[] })) : Promise.resolve({ orders: [] as Order[] }),
    ]);
    const byId = new Map<number, Order>();
    [...mine.orders, ...local.orders].forEach(o => byId.set(o.id, o));
    return { orders: [...byId.values()].sort((a, b) => b.created_at.localeCompare(a.created_at)) };
  }, [key]);
  // los de la cuenta que no estaban en el teléfono se guardan, así se puede abrir su seguimiento
  useEffect(() => {
    (res.data?.orders ?? []).forEach(o => {
      const token = (o as Order & { token?: string }).token;
      if (token && !orders.some(x => x.id === o.id)) rememberOrder({ id: o.id, token, store_name: o.store.name, created_at: o.created_at, fromAccount: true });
    });
  }, [res.data]); // eslint-disable-line react-hooks/exhaustive-deps
  // al volver a la pestaña se actualizan los estados
  useFocusEffect(useCallback(() => { if (key) res.refresh(); }, [key])); // eslint-disable-line react-hooks/exhaustive-deps

  // los que están en curso van arriba, en grande; abajo el historial por mes
  const live = useMemo(() => (res.data?.orders ?? []).filter(o => !o.final && (filter === 'all' || filter === 'live')), [res.data, filter]);
  const groups = useMemo(() => {
    const list = (res.data?.orders ?? []).filter(o => o.final && (filter === 'all' || (filter === 'done' ? o.status === 'ENTREGADO' : filter === 'cancel' && o.status === 'CANCELADO')));
    const out: { title: string; orders: Order[] }[] = [];
    const year = new Date().getFullYear();
    list.forEach(o => {
      const d = new Date(o.created_at);
      const title = MONTHS[d.getMonth()] + (d.getFullYear() !== year ? ` ${d.getFullYear()}` : '');
      if (out[out.length - 1]?.title !== title) out.push({ title, orders: [] });
      out[out.length - 1].orders.push(o);
    });
    return out;
  }, [res.data, filter]);

  // repetir: se arma el carrito con los precios de hoy y la misma dirección; avisa qué ya no está o cambió de precio
  const repeat = (o: Order) => {
    const ok = o.items.filter(i => i.available && i.product_id);
    const lines: CartLine[] = ok.map(i => ({
      product_id: i.product_id!, quantity: i.quantity, modifiers: [], name: i.name,
      unit_price: i.current_price ?? i.unit_price ?? i.line_total / i.quantity,
      modifiers_text: i.grams ? weightLabel(i.grams) : null, store_slug: o.store.slug, store_name: o.store.name, grams: i.grams ?? null,
    }));
    if (!lines.length) { router.push({ pathname: '/store/[slug]', params: { slug: o.store.slug } }); return; }
    const missing = o.items.filter(i => !(i.available && i.product_id)).map(i => i.name);
    const changed = ok.filter(i => i.current_price != null && i.unit_price != null && i.current_price !== i.unit_price)
      .map(i => `${i.name}: ${money(i.unit_price)} → ${money(i.current_price)}`);
    const withOptions = ok.filter(i => i.modifiers_text && !(i.grams && i.modifiers_text === weightLabel(i.grams))).map(i => i.name);
    const go = () => {
      replaceCart(lines);
      if (o.delivery_method === 'delivery' && o.address) setCustomer({ ...customer, address: o.address });
      router.push('/cart');
    };
    const notes = [
      missing.length ? `Ya no están: ${missing.join(', ')}.` : '',
      changed.length ? `Cambiaron de precio:\n${changed.join('\n')}` : '',
      withOptions.length ? `Volvé a elegir las opciones de: ${withOptions.join(', ')}.` : '',
    ].filter(Boolean).join('\n\n');
    const start = () => (notes ? Alert.alert('Repetir pedido', notes, [{ text: 'Cancelar', style: 'cancel' }, { text: 'Seguir', onPress: go }]) : go());
    if (cart.length && cart[0].store_slug !== o.store.slug) confirmReplace(cart[0].store_name, start); else start();
  };

  if (!ready || (res.loading && !res.data)) return <Loading />;
  if (res.error && !res.data) return <ErrorState message={res.error} onRetry={res.reload} />;
  const empty = !(res.data?.orders ?? []).length;

  return (
    <View style={{ flex: 1, backgroundColor: '#fff' }}>
      <View style={[st.head, { paddingTop: insets.top + 10 }]}>
        <Text style={st.title}>Mis pedidos</Text>
        <Pressable onPress={() => router.push('/cart')} hitSlop={10} accessibilityLabel="Mi pedido" style={st.cartIcon}><Ionicons name="cart-outline" size={28} color={colors.ink} /></Pressable>
      </View>
      <ScrollView contentContainerStyle={{ paddingBottom: 32, flexGrow: 1 }}
        refreshControl={<RefreshControl refreshing={res.refreshing} onRefresh={res.refresh} tintColor={colors.brand} />}>
        {!empty && (
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={st.pills}>
            {FILTERS.map(f => (
              <Pressable key={f.key} onPress={() => setFilter(f.key)} style={[st.pill, filter === f.key && st.pillOn]}>
                <Text style={[st.pillText, filter === f.key && { color: '#fff' }]}>{f.label}</Text>
              </Pressable>
            ))}
          </ScrollView>
        )}
        {empty && <Empty emoji="🧾" title="Todavía no hiciste pedidos" text="Cuando pidas algo vas a poder seguirlo desde acá."
          action={<Link href="/" asChild><Button title="Explorar comercios" style={{ marginTop: 12 }} /></Link>} />}
        {!empty && !groups.length && !live.length && <Empty emoji="🧾" title="No hay pedidos con ese filtro" />}
        {live.map(o => (
          <Pressable key={o.id} style={st.live} onPress={() => router.push({ pathname: '/order/[id]', params: { id: String(o.id) } })} accessibilityRole="button" accessibilityLabel={`Seguir el pedido de ${o.store.name}`}>
            <View style={st.liveGlow} />
            <View style={[st.liveAv, { backgroundColor: o.tracking?.color || 'rgba(255,255,255,.2)' }]}><Text style={{ fontSize: 26 }}>{o.tracking?.avatar || '🛍️'}</Text></View>
            <View style={{ flex: 1 }}>
              <Text style={st.liveStore} numberOfLines={1}>{o.store.name}</Text>
              <Text style={st.liveSub} numberOfLines={2}>{o.tracking ? `${o.tracking.name} va en camino` : o.status_label}{o.delivery_pin ? ` · PIN ${o.delivery_pin}` : ''}</Text>
            </View>
            {o.tracking?.eta_min ? (
              <View style={st.liveMin}><Text style={st.liveMinN}>{o.tracking.eta_min}</Text><Text style={st.liveMinT}>min</Text></View>
            ) : <Ionicons name="chevron-forward" size={22} color="#fff" />}
          </Pressable>
        ))}
        {groups.map(g => (
          <View key={g.title}>
            <Text style={st.month}>{g.title}</Text>
            {g.orders.map(o => {
              const canRepeat = o.final && o.items.some(i => i.available);
              const thumbs = o.items.filter(i => i.image_url).slice(0, 6);
              return (
                <View key={o.id} style={st.card}>
                  <Pressable style={st.top} onPress={() => router.push({ pathname: '/order/[id]', params: { id: String(o.id) } })} accessibilityLabel={`Pedido ${o.id} de ${o.store.name}`}>
                    <View style={st.logo}><Text style={st.logoText}>{initials(o.store.name)}</Text></View>
                    <View style={{ flex: 1, gap: 2 }}>
                      <View style={st.rowBetween}>
                        <Text style={st.store} numberOfLines={2}>{o.store.name}</Text>
                        <View style={[st.status, { backgroundColor: o.status === 'CANCELADO' ? colors.badSoft : colors.goodSoft }]}><Text style={[st.statusText, { color: statusColor(o) }]}>{o.status_label}</Text></View>
                      </View>
                      <Text style={st.when}>{dayLabel(o.created_at)} · <Text style={{ fontWeight: '800', color: colors.ink }}>{money(o.total)}</Text></Text>
                      <Text style={st.items} numberOfLines={1}>{o.items.map(i => `${i.quantity}× ${i.name}`).join(', ')}</Text>
                      {o.can_review && <Text style={st.review}>★ Calificá tu pedido</Text>}
                    </View>
                  </Pressable>
                  {thumbs.length > 0 && (
                    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 10, paddingLeft: 78, paddingRight: 16 }}>
                      {thumbs.map((i, n) => <View key={n} style={st.thumb}><Image source={{ uri: i.image_url! }} style={StyleSheet.absoluteFill} contentFit="cover" /></View>)}
                    </ScrollView>
                  )}
                  {o.final ? (
                    <View style={st.btns}>
                      <Pressable style={[st.repeat, st.repeatMain, !canRepeat && { opacity: 0.45 }]} onPress={() => repeat(o)} disabled={!canRepeat} accessibilityRole="button" accessibilityLabel="Repetir pedido">
                        <Ionicons name="refresh" size={19} color="#fff" /><Text style={[st.repeatText, { color: '#fff' }]}>Repetir</Text>
                      </Pressable>
                      <Pressable style={[st.repeat, { flex: 1 }]} onPress={() => router.push({ pathname: '/order/[id]', params: { id: String(o.id) } })} accessibilityRole="button">
                        <Text style={st.repeatText}>Ver detalle</Text>
                      </Pressable>
                    </View>
                  ) : (
                    <Pressable style={[st.repeat, { backgroundColor: colors.brand }]} onPress={() => router.push({ pathname: '/order/[id]', params: { id: String(o.id) } })} accessibilityRole="button">
                      <Ionicons name="navigate-outline" size={20} color="#fff" /><Text style={[st.repeatText, { color: '#fff' }]}>Seguir mi pedido</Text>
                    </Pressable>
                  )}
                </View>
              );
            })}
          </View>
        ))}
      </ScrollView>
    </View>
  );
}

const st = StyleSheet.create({
  head: { alignItems: 'center', paddingBottom: 8, backgroundColor: '#fff' },
  title: { fontSize: 26, fontWeight: '900', color: colors.ink, letterSpacing: -0.6, alignSelf: 'flex-start', paddingHorizontal: 18 },
  cartIcon: { position: 'absolute', right: 16, bottom: 6 },
  pills: { paddingHorizontal: 16, gap: 10, paddingVertical: 12 },
  pill: { paddingHorizontal: 18, height: 42, justifyContent: 'center', borderRadius: radius.pill, backgroundColor: '#F2F1F5' },
  pillOn: { backgroundColor: colors.ink },
  pillText: { fontWeight: '700', color: colors.ink, fontSize: 15 },
  live: { flexDirection: 'row', alignItems: 'center', gap: 12, marginHorizontal: 16, marginBottom: 12, padding: 14, borderRadius: 22, backgroundColor: colors.brand, overflow: 'hidden',
    shadowColor: colors.brand, shadowOpacity: 0.45, shadowRadius: 14, shadowOffset: { width: 0, height: 8 }, elevation: 6 },
  liveGlow: { position: 'absolute', right: -40, top: -60, width: 170, height: 170, borderRadius: 85, backgroundColor: '#9333EA', opacity: 0.6 },
  liveAv: { width: 52, height: 52, borderRadius: 26, borderWidth: 3, borderColor: '#fff', alignItems: 'center', justifyContent: 'center' },
  liveStore: { color: '#fff', fontWeight: '900', fontSize: 17 },
  liveSub: { color: '#E9DDFF', fontSize: 13.5, marginTop: 2 },
  liveMin: { alignItems: 'center', backgroundColor: 'rgba(255,255,255,.18)', borderRadius: 14, paddingHorizontal: 10, paddingVertical: 6 },
  liveMinN: { color: '#fff', fontWeight: '900', fontSize: 21 },
  liveMinT: { color: '#E9DDFF', fontSize: 11, fontWeight: '700' },
  status: { borderRadius: radius.pill, paddingHorizontal: 9, paddingVertical: 3 },
  statusText: { fontSize: 12, fontWeight: '900' },
  btns: { flexDirection: 'row', gap: 10, marginHorizontal: 16 },
  repeatMain: { flex: 1, backgroundColor: colors.brand, marginHorizontal: 0 },
  month: { fontSize: 20, fontWeight: '800', color: colors.ink, paddingHorizontal: 16, marginTop: 14, marginBottom: 4 },
  card: { paddingVertical: 14, gap: 12, marginHorizontal: 16, marginBottom: 12, borderRadius: 22, backgroundColor: '#fff', borderWidth: 1, borderColor: colors.line,
    shadowColor: '#1E143C', shadowOpacity: 0.05, shadowRadius: 10, shadowOffset: { width: 0, height: 2 }, elevation: 1 },
  top: { flexDirection: 'row', gap: 12, paddingHorizontal: 14 },
  logo: { width: 52, height: 52, borderRadius: 14, backgroundColor: colors.brandSoft, alignItems: 'center', justifyContent: 'center' },
  logoText: { color: colors.brand, fontWeight: '800', fontSize: 17 },
  rowBetween: { flexDirection: 'row', justifyContent: 'space-between', gap: 10, alignItems: 'flex-start' },
  when: { fontSize: 14.5, color: colors.ink },
  store: { fontSize: 17, fontWeight: '800', color: colors.ink, flex: 1 },
  total: { fontSize: 18, fontWeight: '800', color: colors.ink },
  items: { fontSize: 14, color: colors.muted },
  review: { color: colors.warn, fontWeight: '800', marginTop: 2 },
  thumb: { width: 64, height: 64, borderRadius: 14, backgroundColor: '#F2F1F5', overflow: 'hidden' },
  repeat: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, marginHorizontal: 14, height: 46, borderRadius: 14, backgroundColor: '#F2F1F5' },
  repeatText: { fontSize: 16.5, fontWeight: '700', color: colors.ink },
});
