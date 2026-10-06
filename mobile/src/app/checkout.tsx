import { Link, router } from 'expo-router';
import { useEffect, useState } from 'react';
import { KeyboardAvoidingView, Linking, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View, type TextInputProps } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { LoginCard } from '@/components/login-card';
import { Button, Empty, s as ui } from '@/components/ui';
import { API_URL, api } from '@/lib/api';
import { quoteBody } from '@/lib/cart';
import { getPushTokenQuick } from '@/lib/push';
import { money } from '@/lib/format';
import { colors, radius } from '@/lib/theme';
import type { PaymentMethod, Quote } from '@/lib/types';
import { useFetch } from '@/lib/useFetch';
import { useApp } from '@/state/app-state';

export default function CheckoutScreen() {
  const insets = useSafeAreaInsets();
  const { cart, location, customer, setCustomer, clearCart, rememberOrder, account } = useApp();
  const [form, setForm] = useState({ ...customer, address: customer.address || location?.label || '', notes: '', coupon: '' });
  // con la cuenta obligatoria, sin sesión primero hay que entrar
  const config = useFetch(() => api.config(), []);
  const needsLogin = !account && !!config.data?.account?.required;
  // al entrar (o al tener la cuenta), lo guardado en ella completa lo que falte
  const [filledFor, setFilledFor] = useState<number | null>(null);
  if (account && filledFor !== account.id) {
    setFilledFor(account.id);
    setForm(f => ({ ...f, first_name: f.first_name || account.first_name, last_name: f.last_name || account.last_name, phone: f.phone || account.phone,
      address: f.address || account.address, reference: f.reference || account.reference }));
  }
  const [method, setMethod] = useState<'delivery' | 'retiro'>('delivery');
  const [pay, setPay] = useState<PaymentMethod>('efectivo');
  const [cashWith, setCashWith] = useState('');
  const [coupon, setCoupon] = useState(''); // el cupón aplicado (el campo puede tener otro texto sin aplicar)
  const [quote, setQuote] = useState<Quote | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const set = (k: keyof typeof form) => (v: string) => setForm(f => ({ ...f, [k]: v }));

  useEffect(() => {
    if (!cart.length) return;
    let alive = true;
    api.quote(quoteBody(cart, location, { delivery_method: method, coupon }))
      .then(q => {
        if (!alive) return;
        setQuote(q);
        // si el comercio no reparte o no llega, se pasa a retiro
        if (method === 'delivery' && q.store && (!q.store.delivery_enabled || q.store.coverage.covered === false)) setMethod('retiro');
      })
      .catch(e => alive && setError(e.message));
    return () => { alive = false; };
  }, [cart, location, method, coupon]);

  if (!cart.length) return <Empty emoji="🛒" title="Tu pedido está vacío" />;
  const store = quote?.store;
  const canDeliver = !!store && store.delivery_enabled && store.coverage.covered !== false;
  const needsLocation = method === 'delivery' && !!store?.coverage.zoned && !location;

  const submit = async () => {
    setError(null);
    if (!form.first_name.trim() || !form.phone.trim()) return setError('Completá tu nombre y teléfono.');
    if (method === 'delivery' && !form.address.trim()) return setError('Indicá la dirección de entrega.');
    const cash = pay === 'efectivo' ? parseMoney(cashWith) : null;
    if (cash !== null && quote && cash < quote.total) return setError(`El monto con el que pagás es menor al total (${money(quote.total)}).`);
    setSending(true);
    try {
      // el permiso de notificaciones se pide acá, cuando tiene sentido: para avisar cómo va el pedido
      const pushToken = await getPushTokenQuick();
      const res = await api.createOrder({
        ...quoteBody(cart, location, { delivery_method: method, coupon }),
        first_name: form.first_name.trim(), last_name: form.last_name.trim(), phone: form.phone.trim(),
        address: method === 'delivery' ? form.address.trim() : '', reference: method === 'delivery' ? form.reference.trim() : '', notes: form.notes.trim(),
        push_token: pushToken || '', platform: Platform.OS,
        payment_method: pay, cash_with: cash,
      });
      setCustomer({ first_name: form.first_name.trim(), last_name: form.last_name.trim(), phone: form.phone.trim(), address: form.address.trim(), reference: form.reference.trim() });
      rememberOrder({ id: res.id, token: res.token, store_name: store?.name || cart[0].store_name, created_at: new Date().toISOString(), fromAccount: !!account });
      clearCart();
      router.dismissAll();
      router.push({ pathname: '/order/[id]', params: { id: String(res.id), nuevo: '1' } });
      if (res.pay_path) Linking.openURL(API_URL + res.pay_path);  // Mercado Pago (el link se arma en el servidor)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No pudimos enviar el pedido.');
    } finally {
      setSending(false);
    }
  };

  return (
    <KeyboardAvoidingView style={{ flex: 1, backgroundColor: colors.bg }} behavior={Platform.OS === 'ios' ? 'padding' : undefined} keyboardVerticalOffset={90}>
      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 24 }} keyboardShouldPersistTaps="handled">
        {needsLogin && <LoginCard title="Entrá para hacer tu pedido" />}
        {account && <Text style={[ui.muted, { marginBottom: 4 }]}>Pedís como <Text style={{ fontWeight: '800', color: colors.ink }}>{account.name || account.email}</Text></Text>}
        <Text style={st.label}>¿Cómo lo recibís?</Text>
        <View style={st.segment}>
          {(['delivery', 'retiro'] as const).map(m => {
            const off = m === 'delivery' && !canDeliver;
            return (
              <Pressable key={m} disabled={off} onPress={() => setMethod(m)} style={[st.segBtn, method === m && st.segOn, off && { opacity: 0.45 }]} accessibilityRole="radio" accessibilityState={{ checked: method === m, disabled: off }}>
                <Text style={[st.segText, method === m && { color: '#fff' }]}>{m === 'delivery' ? '🛵 Delivery' : '🛍 Retiro en el local'}</Text>
                {m === 'delivery' && store && <Text style={[st.segSub, method === m && { color: '#E9DDFF' }]}>{!store.delivery_enabled ? 'No disponible' : store.coverage.covered === false ? 'No llega a tu zona' : store.coverage.cost !== null ? (store.coverage.cost === 0 ? 'Gratis' : money(store.coverage.cost)) : `desde ${money(store.coverage.from_cost)}`}</Text>}
                {m === 'retiro' && store?.address && <Text style={[st.segSub, method === m && { color: '#E9DDFF' }]} numberOfLines={1}>{store.address}</Text>}
              </Pressable>
            );
          })}
        </View>

        <Text style={st.label}>Tus datos</Text>
        <View style={{ flexDirection: 'row', gap: 10 }}>
          <Field style={{ flex: 1, minWidth: 0 }} placeholder="Nombre" value={form.first_name} onChangeText={set('first_name')} autoComplete="given-name" textContentType="givenName" />
          <Field style={{ flex: 1, minWidth: 0 }} placeholder="Apellido" value={form.last_name} onChangeText={set('last_name')} autoComplete="family-name" textContentType="familyName" />
        </View>
        <Field placeholder="Teléfono (WhatsApp)" value={form.phone} onChangeText={set('phone')} keyboardType="phone-pad" autoComplete="tel" textContentType="telephoneNumber" />

        {method === 'delivery' && (
          <>
            <Text style={st.label}>Dirección de entrega</Text>
            {needsLocation ? (
              <Link href="/location" asChild>
                <Pressable style={st.locHint}><Text style={{ color: colors.brand, fontWeight: '700' }}>📍 Marcá tu ubicación en el mapa para calcular el envío</Text></Pressable>
              </Link>
            ) : location ? (
              <Link href="/location" asChild><Pressable><Text style={[ui.muted, { marginBottom: 8 }]}>📍 {location.label} · <Text style={{ color: colors.brand, fontWeight: '700' }}>Cambiar</Text></Text></Pressable></Link>
            ) : null}
            {store?.coverage.mode === 'trappi' && store.coverage.covered && (
              <View style={st.fleet}>
                <Text style={{ fontWeight: '800', color: colors.good }}>🚚 Entrega Trappi{store.coverage.zone ? ` · Zona ${store.coverage.zone}` : ''}</Text>
                <Text style={{ color: colors.ink }}>{store.coverage.route_km != null ? `${String(store.coverage.route_km.toFixed(1)).replace('.', ',')} km${store.coverage.route_estimated ? ' (estimado)' : ''} · ` : ''}Envío {quote?.shipping ? money(quote.shipping) : 'gratis'}{store.coverage.eta_min ? ` · ${store.coverage.eta_min}–${store.coverage.eta_max} min` : ''}</Text>
              </View>
            )}
            {store?.coverage.mode === 'trappi' && store.coverage.covered === false && (
              <View style={st.error}><Text style={{ color: colors.bad, fontWeight: '700' }}>❌ Fuera de cobertura. {store.coverage.reason || 'Esta dirección está fuera de la zona de entrega de este comercio.'}</Text></View>
            )}
            <Field placeholder="Calle, número, piso/depto" value={form.address} onChangeText={set('address')} autoComplete="street-address" textContentType="fullStreetAddress" />
            <Field placeholder="Referencia (opcional): portón negro, timbre 2…" value={form.reference} onChangeText={set('reference')} />
          </>
        )}

        <Text style={st.label}>Notas para el comercio</Text>
        <Field placeholder="Sin cebolla, tocar timbre… (opcional)" value={form.notes} onChangeText={set('notes')} multiline style={{ minHeight: 70, textAlignVertical: 'top' }} />

        <Text style={st.label}>¿Cómo pagás?</Text>
        <View style={st.segment}>
          {([...(store?.payment_methods ?? ['efectivo', 'transferencia']), ...(store?.mp_available ? ['mercadopago'] : [])] as PaymentMethod[]).map(m => (
            <Pressable key={m} onPress={() => setPay(m)} style={[st.segBtn, pay === m && st.segOn]} accessibilityRole="radio" accessibilityState={{ checked: pay === m }}>
              <Text style={[st.segText, pay === m && { color: '#fff' }]}>{m === 'efectivo' ? '💵 Efectivo' : m === 'mercadopago' ? '💳 Mercado Pago' : '🏦 Transferencia'}</Text>
              <Text style={[st.segSub, pay === m && { color: '#E9DDFF' }]} numberOfLines={1}>{m === 'efectivo' ? (method === 'delivery' ? 'Al recibir' : 'Al retirar') : m === 'mercadopago' ? 'Pagás ahora' : store?.transfer_alias ? `Alias ${store.transfer_alias}` : 'Al local'}</Text>
            </Pressable>
          ))}
        </View>
        {pay === 'mercadopago' ? (
          <View style={st.payNote}><Text style={{ color: colors.ink }}>Al confirmar te llevamos a Mercado Pago. El pedido se confirma cuando el pago queda aprobado y el repartidor no te cobra nada.</Text></View>
        ) : pay === 'efectivo' ? (
          <Field placeholder="¿Con cuánto pagás? (opcional, para el vuelto)" value={cashWith} onChangeText={setCashWith} keyboardType="numeric" style={{ marginTop: 10 }} />
        ) : (
          <View style={st.payNote}>
            <Text style={{ color: colors.ink }}>{store?.transfer_alias
              ? <>Transferí <Text style={{ fontWeight: '800' }}>{money(quote?.total)}</Text> al alias <Text style={{ fontWeight: '800' }} selectable>{store.transfer_alias}</Text> y mandale el comprobante al comercio por WhatsApp.</>
              : 'Después de confirmar, el comercio te pasa sus datos por WhatsApp para que le transfieras.'}</Text>
            <Text style={[ui.muted, { fontSize: 12.5, marginTop: 4 }]}>Cuando el comercio confirme tu pago, el repartidor no te cobra nada.</Text>
          </View>
        )}

        <Text style={st.label}>Cupón</Text>
        <View style={{ flexDirection: 'row', gap: 10 }}>
          <Field style={{ flex: 1, minWidth: 0 }} placeholder="Código" value={form.coupon} onChangeText={set('coupon')} autoCapitalize="characters" autoCorrect={false} />
          <Button title={coupon && coupon === form.coupon.trim() ? 'Quitar' : 'Aplicar'} variant="secondary" style={{ minHeight: 48 }}
            onPress={() => { if (coupon && coupon === form.coupon.trim()) { setCoupon(''); set('coupon')(''); } else setCoupon(form.coupon.trim()); }} />
        </View>
        {!!coupon && quote?.coupon_error && <Text style={{ color: colors.bad, marginTop: -4 }}>{quote.coupon_error}</Text>}
        {!!coupon && quote && !quote.coupon_error && quote.discount > 0 && <Text style={{ color: colors.good, fontWeight: '700', marginTop: -4 }}>¡Cupón aplicado! Ahorrás {money(quote.discount)}</Text>}

        <View style={st.summary}>
          {cart.map(l => (
            <View key={`${l.product_id}-${l.modifiers.join('-')}`} style={ui.row}>
              <Text style={{ color: colors.ink, flex: 1 }} numberOfLines={1}>{l.quantity}× {l.name}</Text>
              <Text style={{ color: colors.ink }}>{money(l.unit_price * l.quantity)}</Text>
            </View>
          ))}
          <View style={st.sep} />
          <View style={ui.row}><Text style={ui.muted}>Subtotal</Text><Text style={{ color: colors.ink }}>{money(quote?.subtotal)}</Text></View>
          {method === 'delivery' && <View style={ui.row}><Text style={ui.muted}>Envío</Text><Text style={{ color: colors.ink }}>{quote?.shipping === 0 ? 'Gratis' : money(quote?.shipping)}</Text></View>}
          {!!quote?.discount && <View style={ui.row}><Text style={{ color: colors.good }}>Descuento</Text><Text style={{ color: colors.good }}>-{money(quote.discount)}</Text></View>}
          <View style={ui.row}><Text style={st.total}>Total</Text><Text style={st.total}>{money(quote?.total)}</Text></View>
          {method === 'delivery' && <Text style={[ui.muted, { fontSize: 12.5 }]}>Te damos un PIN para que se lo digas al repartidor cuando te entregue.</Text>}
        </View>
        {error && <View style={st.error}><Text style={{ color: colors.bad, fontWeight: '700' }}>{error}</Text></View>}
      </ScrollView>
      <View style={[st.footer, { paddingBottom: insets.bottom + 12 }]}>
        <Button title={needsLogin ? 'Entrá con tu cuenta para pedir' : quote ? `Confirmar pedido · ${money(quote.total)}` : 'Calculando…'} disabled={!quote || needsLocation || needsLogin} loading={sending} onPress={submit} />
      </View>
    </KeyboardAvoidingView>
  );
}

/** "20.000" o "20000" → 20000 (vacío → null) */
function parseMoney(v: string): number | null {
  const n = Number(v.replace(/\./g, '').replace(',', '.').replace(/[^\d.]/g, ''));
  return v.trim() && Number.isFinite(n) && n > 0 ? n : null;
}

function Field({ style, ...props }: TextInputProps) {
  return <TextInput placeholderTextColor={colors.muted} {...props} style={[st.input, style]} />;
}

const st = StyleSheet.create({
  label: { fontSize: 15, fontWeight: '800', color: colors.ink, marginTop: 18, marginBottom: 8 },
  segment: { flexDirection: 'row', gap: 10 },
  segBtn: { flex: 1, padding: 12, borderRadius: radius.md, borderWidth: 1.5, borderColor: colors.line, backgroundColor: '#fff', gap: 2 },
  segOn: { backgroundColor: colors.brand, borderColor: colors.brand },
  segText: { fontWeight: '800', color: colors.ink },
  segSub: { fontSize: 12.5, color: colors.muted },
  input: { backgroundColor: '#fff', borderWidth: 1, borderColor: colors.line, borderRadius: radius.sm, paddingHorizontal: 14, paddingVertical: 12, fontSize: 16, color: colors.ink, marginBottom: 10 },
  locHint: { padding: 12, borderRadius: radius.sm, backgroundColor: colors.brandSoft, marginBottom: 10 },
  summary: { marginTop: 18, backgroundColor: '#fff', borderRadius: radius.md, borderWidth: 1, borderColor: colors.line, padding: 14, gap: 6 },
  sep: { height: 1, backgroundColor: colors.line, marginVertical: 4 },
  total: { fontSize: 18, fontWeight: '800', color: colors.ink },
  fleet: { padding: 12, borderRadius: radius.sm, backgroundColor: colors.goodSoft, marginBottom: 10, gap: 2 },
  payNote: { marginTop: 10, padding: 12, borderRadius: radius.sm, backgroundColor: colors.brandSoft },
  error: { marginTop: 12, padding: 12, borderRadius: radius.sm, backgroundColor: colors.badSoft },
  footer: { paddingHorizontal: 16, paddingTop: 12, backgroundColor: '#fff', borderTopWidth: 1, borderTopColor: colors.line },
});
