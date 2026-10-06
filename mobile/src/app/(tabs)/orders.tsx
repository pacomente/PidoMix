import Ionicons from '@expo/vector-icons/Ionicons';
import { Image } from 'expo-image';
import { Link, router, useFocusEffect } from 'expo-router';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { initials } from '@/components/market';
import { Button, Empty, ErrorState, Loading, confirmReplace } from '@/components/ui';
import { api } from '@/lib/api';
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
  const { orders, ready, account, rememberOrder, cart, replaceCart } = useApp();
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

  const groups = useMemo(() => {
    const list = (res.data?.orders ?? []).filter(o => filter === 'all' || (filter === 'live' ? !o.final : filter === 'done' ? o.status === 'ENTREGADO' : o.status === 'CANCELADO'));
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

  // repetir: se arma el carrito con lo que sigue a la venta (los precios se actualizan en "Mi pedido")
  const repeat = (o: Order) => {
    const lines: CartLine[] = o.items.filter(i => i.available && i.product_id).map(i => ({
      product_id: i.product_id!, quantity: i.quantity, modifiers: [], name: i.name, unit_price: i.unit_price ?? i.line_total / i.quantity,
      modifiers_text: null, store_slug: o.store.slug, store_name: o.store.name,
    }));
    if (!lines.length) { router.push({ pathname: '/store/[slug]', params: { slug: o.store.slug } }); return; }
    const go = () => { replaceCart(lines); router.push('/cart'); };
    if (cart.length && cart[0].store_slug !== o.store.slug) confirmReplace(cart[0].store_name, go); else go();
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
        {!empty && !groups.length && <Empty emoji="🧾" title="No hay pedidos con ese filtro" />}
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
                      <Text style={st.when}><Text style={{ color: statusColor(o), fontWeight: '800' }}>{o.status_label}</Text> {dayLabel(o.created_at)}</Text>
                      <View style={st.rowBetween}>
                        <Text style={st.store} numberOfLines={2}>{o.store.name}</Text>
                        <Text style={st.total}>{money(o.total)}</Text>
                      </View>
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
                    <Pressable style={[st.repeat, !canRepeat && { opacity: 0.45 }]} onPress={() => repeat(o)} disabled={!canRepeat} accessibilityRole="button" accessibilityLabel="Repetir pedido">
                      <Ionicons name="refresh" size={20} color={colors.ink} /><Text style={st.repeatText}>Repetir</Text>
                    </Pressable>
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
  title: { fontSize: 20, fontWeight: '800', color: colors.ink },
  cartIcon: { position: 'absolute', right: 16, bottom: 6 },
  pills: { paddingHorizontal: 16, gap: 10, paddingVertical: 12 },
  pill: { paddingHorizontal: 18, height: 42, justifyContent: 'center', borderRadius: radius.pill, backgroundColor: '#F2F1F5' },
  pillOn: { backgroundColor: colors.ink },
  pillText: { fontWeight: '700', color: colors.ink, fontSize: 15 },
  month: { fontSize: 20, fontWeight: '800', color: colors.ink, paddingHorizontal: 16, marginTop: 14, marginBottom: 4 },
  card: { paddingVertical: 12, gap: 12, borderBottomWidth: 1, borderBottomColor: '#F2F1F5' },
  top: { flexDirection: 'row', gap: 14, paddingHorizontal: 16 },
  logo: { width: 52, height: 52, borderRadius: 14, backgroundColor: colors.brandSoft, alignItems: 'center', justifyContent: 'center' },
  logoText: { color: colors.brand, fontWeight: '800', fontSize: 17 },
  rowBetween: { flexDirection: 'row', justifyContent: 'space-between', gap: 10, alignItems: 'flex-start' },
  when: { fontSize: 14.5, color: colors.ink },
  store: { fontSize: 18, fontWeight: '800', color: colors.ink, flex: 1 },
  total: { fontSize: 18, fontWeight: '800', color: colors.ink },
  items: { fontSize: 14, color: colors.muted },
  review: { color: colors.warn, fontWeight: '800', marginTop: 2 },
  thumb: { width: 64, height: 64, borderRadius: 14, backgroundColor: '#F2F1F5', overflow: 'hidden' },
  repeat: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, marginHorizontal: 16, height: 50, borderRadius: radius.pill, backgroundColor: '#F2F1F5' },
  repeatText: { fontSize: 16.5, fontWeight: '700', color: colors.ink },
});
