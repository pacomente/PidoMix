import { Link, useFocusEffect } from 'expo-router';
import { useCallback, useEffect } from 'react';
import { FlatList, Pressable, RefreshControl, StyleSheet, Text, View } from 'react-native';

import { Button, Chip, Empty, ErrorState, Loading, statusTone, s as ui } from '@/components/ui';
import { api } from '@/lib/api';
import { money } from '@/lib/format';
import { colors, radius } from '@/lib/theme';
import type { Order } from '@/lib/types';
import { useFetch } from '@/lib/useFetch';
import { useApp } from '@/state/app-state';

export default function OrdersScreen() {
  const { orders, ready, account, rememberOrder } = useApp();
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

  if (!ready || (res.loading && !res.data)) return <Loading />;
  if (res.error && !res.data) return <ErrorState message={res.error} onRetry={res.reload} />;
  const list = res.data?.orders ?? [];

  return (
    <FlatList
      style={{ backgroundColor: colors.bg }}
      data={list}
      keyExtractor={o => String(o.id)}
      contentContainerStyle={{ padding: 16, flexGrow: 1 }}
      refreshControl={<RefreshControl refreshing={res.refreshing} onRefresh={res.refresh} tintColor={colors.brand} />}
      ListEmptyComponent={<Empty emoji="🧾" title="Todavía no hiciste pedidos" text="Cuando pidas algo vas a poder seguirlo desde acá."
        action={<Link href="/" asChild><Button title="Explorar comercios" style={{ marginTop: 12 }} /></Link>} />}
      renderItem={({ item: o }) => (
        <Link href={{ pathname: '/order/[id]', params: { id: String(o.id) } }} asChild>
          <Pressable style={({ pressed }) => [st.card, pressed && { opacity: 0.85 }]}>
            <View style={ui.row}>
              <Text style={st.title} numberOfLines={1}>{o.store.name}</Text>
              <Chip label={o.status_label} tone={statusTone(o.status)} />
            </View>
            <Text style={ui.muted} numberOfLines={1}>#{o.id} · {new Date(o.created_at).toLocaleDateString('es-AR')} · {o.items.map(i => `${i.quantity}× ${i.name}`).join(', ')}</Text>
            <View style={[ui.row, { marginTop: 6 }]}>
              <Text style={ui.muted}>{o.delivery_method === 'delivery' ? '🛵 Delivery' : '🛍 Retiro'}</Text>
              <Text style={st.total}>{money(o.total)}</Text>
            </View>
            {o.can_review && <Text style={st.review}>★ Calificá tu pedido</Text>}
          </Pressable>
        </Link>
      )}
    />
  );
}

const st = StyleSheet.create({
  card: { backgroundColor: '#fff', borderRadius: radius.md, padding: 14, borderWidth: 1, borderColor: colors.line, marginBottom: 12, gap: 4 },
  title: { fontSize: 16, fontWeight: '800', color: colors.ink, flex: 1, marginRight: 8 },
  total: { fontWeight: '800', color: colors.ink, fontSize: 16 },
  review: { marginTop: 4, color: colors.warn, fontWeight: '800' },
});
