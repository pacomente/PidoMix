import Ionicons from '@expo/vector-icons/Ionicons';
import { router } from 'expo-router';
import { useEffect } from 'react';
import { Pressable, ScrollView, StyleSheet, Switch, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Ill } from '@/components/kit';
import { Button, Empty, Loading } from '@/components/ui';
import { api } from '@/lib/api';
import { quoteBody, syncCart, weightLabel } from '@/lib/cart';
import { money } from '@/lib/format';
import { colors } from '@/lib/theme';
import { useFetch } from '@/lib/useFetch';
import { useApp } from '@/state/app-state';

/** Tu pedido: lo que vas a pedir, lo que se pesa marcado como aproximado y cómo se cobra la diferencia. */
export default function CartScreen() {
  const insets = useSafeAreaInsets();
  const { cart, setQuantity, clearCart, replaceCart, location, ready, callIfMissing, setCallIfMissing } = useApp();
  const sig = cart.map(l => `${l.product_id}:${l.modifiers.join('-')}@${l.grams ?? ''}x${l.quantity}`).join('|');
  const quote = useFetch(() => (cart.length ? api.quote(quoteBody(cart, location)) : Promise.resolve(null)), [sig, location?.lat, location?.lng]);
  const q = quote.data;

  // precios al día: si el comercio cambió algún precio, el carrito se actualiza solo
  useEffect(() => {
    if (!q || q.dropped) return;
    const synced = syncCart(cart, q);
    if (synced.some((l, i) => l.unit_price !== cart[i].unit_price)) replaceCart(synced);
  }, [q]); // eslint-disable-line react-hooks/exhaustive-deps

  const back = () => (router.canGoBack() ? router.back() : router.replace('/'));
  const header = (title: string, sub?: string) => (
    <View style={[st.head, { paddingTop: insets.top + 8 }]}>
      <Pressable onPress={back} style={st.round} accessibilityLabel="Volver"><Ionicons name="chevron-back" size={22} color={colors.ink} /></Pressable>
      <View style={{ flex: 1 }}>
        <Text style={st.title}>{title}</Text>
        {!!sub && <Text style={st.sub} numberOfLines={1}>{sub}</Text>}
      </View>
      {cart.length > 0 && <Pressable onPress={clearCart} hitSlop={8}><Text style={st.clear}>Vaciar</Text></Pressable>}
    </View>
  );
  if (!ready) return <Loading />;
  if (!cart.length) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.bg }}>
        {header('Tu pedido')}
        <Empty emoji="🛒" title="Tu pedido está vacío" text="Elegí un local y agregá lo que quieras." action={<Button title="Ver locales" onPress={() => router.navigate('/')} style={{ marginTop: 12 }} />} />
      </View>
    );
  }

  const localSubtotal = cart.reduce((n, l) => n + l.unit_price * l.quantity, 0);
  const subtotal = q?.subtotal ?? localSubtotal;
  const belowMin = !!q && q.minimum_order > 0 && subtotal < q.minimum_order;
  const closed = q?.store && !q.store.is_open && !q.store.can_schedule;
  const byWeight = cart.some(l => l.grams);
  const approx = byWeight ? '≈ ' : '';
  const ship = !q ? '…' : q.store && !q.store.delivery_enabled ? 'Solo retiro' : q.store?.coverage.covered === false ? 'No llega' : q.shipping === 0 ? 'Gratis' : money(q.shipping);
  const free = q?.free_shipping;

  return (
    <View style={{ flex: 1, backgroundColor: colors.bg }}>
      {header('Tu pedido', `${cart[0].store_name}${q?.store ? ` · ${q.store.eta_min}–${q.store.eta_max} min` : ''}`)}
      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 24, gap: 12 }}>
        {!!q?.dropped && (
          <View style={st.warn}>
            <Text style={{ color: colors.bad, fontWeight: '800' }}>Algunos productos ya no están disponibles.</Text>
            <Button title="Quitarlos" variant="danger" onPress={() => replaceCart(syncCart(cart, q))} style={{ marginTop: 8, minHeight: 40 }} />
          </View>
        )}
        {closed && <View style={st.warn}><Text style={{ color: colors.bad, fontWeight: '800' }}>{q!.store!.name} está cerrado ahora. {q!.store!.open_text || ''}</Text></View>}

        <View style={st.card}>
          {cart.map((l, i) => {
            const extra = l.modifiers_text && l.grams ? l.modifiers_text.replace(weightLabel(l.grams), '').replace(/^,\s*/, '') : l.modifiers_text;
            const item = q?.items.find(x => x.product_id === l.product_id);
            return (
              <View key={`${l.product_id}-${l.modifiers.join('-')}-${l.grams ?? ''}`} style={[st.line, i > 0 && st.lineSep]}>
                <View style={st.ill}><Ill e={emojiOf(item?.name ?? l.name)} size={34} /></View>
                <View style={{ flex: 1 }}>
                  <Text style={st.lname} numberOfLines={2}>{l.name}{l.grams ? ` · ${weightLabel(l.grams)}` : ''}</Text>
                  {!!extra && <Text style={st.lsub} numberOfLines={1}>{extra}</Text>}
                  <View style={st.qty}>
                    <Pressable onPress={() => setQuantity(i, l.quantity - 1)} hitSlop={6} accessibilityLabel={l.quantity === 1 ? `Quitar ${l.name}` : 'Uno menos'}>
                      {l.quantity === 1 ? <Ionicons name="trash-outline" size={16} color={colors.bad} /> : <Text style={st.qtyBtn}>−</Text>}
                    </Pressable>
                    <Text style={st.qtyText}>× {l.quantity}</Text>
                    <Pressable onPress={() => setQuantity(i, l.quantity + 1)} hitSlop={6} accessibilityLabel="Uno más"><Text style={st.qtyBtn}>+</Text></Pressable>
                  </View>
                </View>
                <View style={{ alignItems: 'flex-end', gap: 4 }}>
                  <Text style={st.lprice}>{l.grams ? '≈ ' : ''}{money(l.unit_price * l.quantity)}</Text>
                  {!!l.grams && <View style={st.weighs}><Text style={st.weighsText}>⚖ se pesa</Text></View>}
                </View>
              </View>
            );
          })}
        </View>

        {!!free && free.missing > 0 && (
          <View style={st.free}>
            <Text style={st.freeText}>🛵 Te faltan <Text style={{ fontWeight: '900' }}>{money(free.missing)}</Text> para el envío gratis</Text>
            <View style={st.freeBar}><View style={[st.freeFill, { width: `${Math.max(6, Math.min(100, (subtotal / free.from) * 100))}%` }]} /></View>
          </View>
        )}

        <View style={[st.card, { padding: 16, gap: 10 }]}>
          <View style={st.row}><Text style={st.muted}>Productos{byWeight ? ' (aprox.)' : ''}</Text><Text style={st.amount}>{approx}{money(subtotal)}</Text></View>
          <View style={st.row}><Text style={st.muted}>Envío</Text><Text style={st.amount}>{ship}</Text></View>
          <View style={st.sep} />
          <View style={st.row}><Text style={st.total}>Total{byWeight ? ' aprox.' : ''}</Text><Text style={st.total}>{approx}{money(q ? q.total : localSubtotal)}</Text></View>
          {belowMin && <Text style={{ color: colors.warn, fontWeight: '800' }}>El pedido mínimo es {money(q!.minimum_order)}. Te faltan {money(q!.minimum_order - subtotal)}.</Text>}
          {quote.error && <Text style={{ color: colors.bad }}>{quote.error}</Text>}
        </View>

        {byWeight && (
          <View style={st.note}>
            <Ill e="💰" size={26} />
            <Text style={st.noteText}>En <Text style={{ fontWeight: '900' }}>efectivo o transferencia</Text> pagás lo que marque la balanza (el local ajusta hasta ±10 % y te avisa). Con <Text style={{ fontWeight: '900' }}>Mercado Pago</Text> se cobra este total.</Text>
          </View>
        )}
        <View style={st.call}>
          <Ill e="📞" size={26} />
          <View style={{ flex: 1 }}>
            <Text style={st.callTitle}>{byWeight ? 'Si falta un corte, llamame' : 'Si falta algo, llamame'}</Text>
            <Text style={st.callSub}>Si no, lo reemplazan por uno parecido</Text>
          </View>
          <Switch value={callIfMissing} onValueChange={setCallIfMissing} trackColor={{ true: '#16A34A', false: colors.line }} thumbColor="#fff" accessibilityLabel="Si falta algo, llamame" />
        </View>
      </ScrollView>
      <View style={[st.footer, { paddingBottom: insets.bottom + 12 }]}>
        <Pressable onPress={() => router.push('/checkout')} disabled={!q || belowMin || !!closed || !!q.dropped || quote.loading}
          style={[st.go, (!q || belowMin || !!closed || !!q?.dropped || quote.loading) && { opacity: 0.5 }]} accessibilityRole="button">
          <Text style={st.goText}>Confirmar pedido</Text>
          <Text style={st.goText}>{approx}{money(q ? q.total : localSubtotal)}</Text>
        </Pressable>
      </View>
    </View>
  );
}

/** emoji del producto a partir del nombre (para la ilustración de la línea) */
function emojiOf(name: string): string {
  const n = name.toLowerCase();
  const map: [string, string][] = [['nalga', '🥩'], ['asado', '🥩'], ['vac', '🥩'], ['bife', '🥩'], ['carne', '🥩'], ['pollo', '🍗'], ['pechuga', '🍗'], ['chori', '🌭'], ['chimichurri', '🧂'],
    ['hambur', '🍔'], ['burger', '🍔'], ['papas', '🍟'], ['pizza', '🍕'], ['empanada', '🥟'], ['coca', '🥤'], ['gaseosa', '🥤'], ['agua', '💧'], ['cerveza', '🍺'], ['leche', '🥛'], ['yogur', '🥛'],
    ['queso', '🧀'], ['pan', '🥖'], ['tomate', '🍅'], ['banana', '🍌'], ['manzana', '🍎'], ['helado', '🍦'], ['alfajor', '🍪'], ['chocolate', '🍫'], ['yerba', '🧉'], ['fideo', '🍝'],
    ['huevo', '🥚'], ['arroz', '🍚'], ['aceite', '🫒'], ['detergente', '🧴'], ['lavandina', '🧴'], ['papel', '🧻'], ['ibuprofeno', '💊']];
  return map.find(([k]) => n.includes(k))?.[1] ?? '🛍️';
}

const st = StyleSheet.create({
  head: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 16, paddingBottom: 12, backgroundColor: colors.bg },
  round: { width: 42, height: 42, borderRadius: 21, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center' },
  title: { fontSize: 24, fontWeight: '900', color: colors.ink, letterSpacing: -0.6 },
  sub: { color: colors.muted, fontSize: 13.5 },
  clear: { color: colors.bad, fontWeight: '800' },
  card: { backgroundColor: '#fff', borderRadius: 22 },
  line: { flexDirection: 'row', alignItems: 'flex-start', gap: 12, padding: 14 },
  lineSep: { borderTopWidth: 1, borderTopColor: '#F1EFF5' },
  ill: { width: 52, height: 52, borderRadius: 16, backgroundColor: '#FFF1F2', alignItems: 'center', justifyContent: 'center' },
  lname: { fontWeight: '900', color: colors.ink, fontSize: 15.5 },
  lsub: { color: colors.muted, fontSize: 13, marginTop: 1 },
  qty: { flexDirection: 'row', alignItems: 'center', gap: 12, marginTop: 6 },
  qtyBtn: { fontSize: 18, fontWeight: '900', color: colors.brand },
  qtyText: { fontWeight: '800', color: colors.muted },
  lprice: { fontWeight: '900', color: colors.ink, fontSize: 16 },
  weighs: { backgroundColor: '#FFF7E6', borderRadius: 8, paddingHorizontal: 7, paddingVertical: 2 },
  weighsText: { color: '#92400E', fontWeight: '800', fontSize: 11.5 },
  warn: { padding: 12, borderRadius: 16, backgroundColor: colors.badSoft },
  free: { backgroundColor: '#F0FDF4', borderRadius: 18, padding: 12, gap: 6 },
  freeText: { color: '#15803D', fontWeight: '700' },
  freeBar: { height: 7, borderRadius: 9, backgroundColor: '#DCFCE7', overflow: 'hidden' },
  freeFill: { height: '100%', borderRadius: 9, backgroundColor: '#16A34A' },
  row: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  muted: { color: colors.muted, fontSize: 15 },
  amount: { fontWeight: '700', color: colors.ink, fontSize: 15 },
  sep: { height: 1, backgroundColor: '#F1EFF5' },
  total: { fontSize: 20, fontWeight: '900', color: colors.ink, letterSpacing: -0.4 },
  note: { flexDirection: 'row', gap: 12, alignItems: 'center', padding: 14, borderRadius: 20, backgroundColor: '#F5F3FF' },
  noteText: { flex: 1, color: '#4C1D95', fontSize: 13.5, lineHeight: 19 },
  call: { flexDirection: 'row', gap: 12, alignItems: 'center', padding: 14, borderRadius: 20, backgroundColor: '#fff' },
  callTitle: { fontWeight: '900', color: colors.ink, fontSize: 15 },
  callSub: { color: colors.muted, fontSize: 12.5 },
  footer: { paddingHorizontal: 16, paddingTop: 12, backgroundColor: '#fff', borderTopWidth: 1, borderTopColor: colors.line },
  go: { height: 58, borderRadius: 18, backgroundColor: colors.brand, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 20,
    shadowColor: colors.brand, shadowOpacity: 0.4, shadowRadius: 12, shadowOffset: { width: 0, height: 6 }, elevation: 5 },
  goText: { color: '#fff', fontWeight: '900', fontSize: 17 },
});
