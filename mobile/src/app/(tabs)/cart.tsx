import { Link, router } from 'expo-router';
import { useEffect } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { Button, Empty, Loading, s as ui } from '@/components/ui';
import { api } from '@/lib/api';
import { quoteBody, syncCart } from '@/lib/cart';
import { money } from '@/lib/format';
import { colors, radius } from '@/lib/theme';
import { useFetch } from '@/lib/useFetch';
import { useApp } from '@/state/app-state';

export default function CartScreen() {
  const { cart, setQuantity, clearCart, replaceCart, location, ready } = useApp();
  const sig = cart.map(l => `${l.product_id}:${l.modifiers.join('-')}x${l.quantity}`).join('|');
  const quote = useFetch(() => (cart.length ? api.quote(quoteBody(cart, location)) : Promise.resolve(null)), [sig, location?.lat, location?.lng]);
  const q = quote.data;

  // precios al día: si el comercio cambió algún precio, el carrito se actualiza solo
  useEffect(() => {
    if (!q || q.dropped) return;
    const synced = syncCart(cart, q);
    if (synced.some((l, i) => l.unit_price !== cart[i].unit_price)) replaceCart(synced);
  }, [q]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!ready) return <Loading />;
  if (!cart.length) {
    return <Empty emoji="🛒" title="Tu pedido está vacío" text="Elegí un comercio y agregá lo que quieras."
      action={<Link href="/" asChild><Button title="Ver comercios" style={{ marginTop: 12 }} /></Link>} />;
  }

  const localSubtotal = cart.reduce((n, l) => n + l.unit_price * l.quantity, 0);
  const subtotal = q?.subtotal ?? localSubtotal;
  const belowMin = !!q && q.minimum_order > 0 && subtotal < q.minimum_order;
  const closed = q?.store && !q.store.is_open;

  return (
    <View style={{ flex: 1, backgroundColor: colors.bg }}>
      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 24 }}>
        <View style={ui.row}>
          <Link href={{ pathname: '/store/[slug]', params: { slug: cart[0].store_slug } }} asChild>
            <Pressable><Text style={ui.h2}>{cart[0].store_name} ›</Text></Pressable>
          </Link>
          <Pressable onPress={clearCart} hitSlop={8}><Text style={{ color: colors.bad, fontWeight: '700' }}>Vaciar</Text></Pressable>
        </View>

        {!!q?.dropped && (
          <View style={st.warn}>
            <Text style={{ color: colors.bad, fontWeight: '700' }}>Algunos productos ya no están disponibles.</Text>
            <Button title="Quitarlos" variant="danger" onPress={() => replaceCart(syncCart(cart, q))} style={{ marginTop: 8, minHeight: 40 }} />
          </View>
        )}
        {closed && <View style={st.warn}><Text style={{ color: colors.bad, fontWeight: '700' }}>{q!.store!.name} está cerrado ahora. {q!.store!.open_text || ''}</Text></View>}

        <View style={st.card}>
          {cart.map((l, i) => (
            <View key={`${l.product_id}-${l.modifiers.join('-')}`} style={[st.line, i > 0 && { borderTopWidth: 1, borderTopColor: colors.line }]}>
              <View style={{ flex: 1 }}>
                <Text style={{ fontWeight: '700', color: colors.ink, fontSize: 15 }}>{l.name}</Text>
                {!!l.modifiers_text && <Text style={ui.muted}>+ {l.modifiers_text}</Text>}
                <Text style={{ fontWeight: '800', color: colors.ink, marginTop: 4 }}>{money(l.unit_price * l.quantity)}</Text>
              </View>
              <View style={st.qty}>
                <Pressable onPress={() => setQuantity(i, l.quantity - 1)} style={st.qtyBtn} accessibilityLabel={l.quantity === 1 ? `Quitar ${l.name}` : 'Uno menos'}>
                  <Text style={st.qtyBtnText}>{l.quantity === 1 ? '🗑' : '−'}</Text>
                </Pressable>
                <Text style={st.qtyText}>{l.quantity}</Text>
                <Pressable onPress={() => setQuantity(i, l.quantity + 1)} style={st.qtyBtn} accessibilityLabel="Uno más"><Text style={st.qtyBtnText}>+</Text></Pressable>
              </View>
            </View>
          ))}
        </View>

        <View style={[st.card, { padding: 14, gap: 6 }]}>
          <View style={ui.row}><Text style={ui.muted}>Subtotal</Text><Text style={st.amount}>{money(subtotal)}</Text></View>
          <View style={ui.row}>
            <Text style={ui.muted}>Envío</Text>
            <Text style={st.amount}>{!q ? '…' : q.store && !q.store.delivery_enabled ? 'Solo retiro' : q.store?.coverage.covered === false ? 'No llega' : q.shipping === 0 ? 'Gratis' : money(q.shipping)}</Text>
          </View>
          <View style={[ui.row, { marginTop: 4 }]}><Text style={st.totalLabel}>Total</Text><Text style={st.totalLabel}>{money(q ? q.total : localSubtotal)}</Text></View>
          {belowMin && <Text style={{ color: colors.warn, fontWeight: '700' }}>El pedido mínimo es {money(q!.minimum_order)}. Te faltan {money(q!.minimum_order - subtotal)}.</Text>}
          {quote.error && <Text style={{ color: colors.bad }}>{quote.error}</Text>}
        </View>
      </ScrollView>
      <View style={st.footer}>
        <Button title="Continuar" disabled={!q || belowMin || !!closed || !!q.dropped || quote.loading} onPress={() => router.push('/checkout')} />
      </View>
    </View>
  );
}

const st = StyleSheet.create({
  card: { backgroundColor: '#fff', borderRadius: radius.md, borderWidth: 1, borderColor: colors.line, marginTop: 14 },
  line: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: 14 },
  warn: { marginTop: 12, padding: 12, borderRadius: radius.sm, backgroundColor: colors.badSoft },
  qty: { flexDirection: 'row', alignItems: 'center', gap: 2, backgroundColor: colors.bg, borderRadius: radius.pill, padding: 3 },
  qtyBtn: { width: 34, height: 34, borderRadius: 17, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: colors.line },
  qtyBtnText: { fontSize: 18, fontWeight: '700', color: colors.brand },
  qtyText: { minWidth: 26, textAlign: 'center', fontWeight: '800', color: colors.ink },
  amount: { fontWeight: '700', color: colors.ink },
  totalLabel: { fontSize: 18, fontWeight: '800', color: colors.ink },
  footer: { padding: 16, backgroundColor: '#fff', borderTopWidth: 1, borderTopColor: colors.line },
});
