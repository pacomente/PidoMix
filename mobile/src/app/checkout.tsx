import Ionicons from '@expo/vector-icons/Ionicons';
import { router, Stack } from 'expo-router';
import { useEffect, useState } from 'react';
import { KeyboardAvoidingView, Linking, Platform, Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, View, type TextInputProps } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Ill } from '@/components/kit';
import { LoginCard } from '@/components/login-card';
import { Empty } from '@/components/ui';
import { API_URL, api } from '@/lib/api';
import { quoteBody, weightLabel } from '@/lib/cart';
import { money } from '@/lib/format';
import { getPushTokenQuick } from '@/lib/push';
import { colors } from '@/lib/theme';
import type { PaymentMethod, Product, Quote, SavedAddress } from '@/lib/types';
import { prefs } from '@/lib/prefs';
import { useFetch } from '@/lib/useFetch';
import { useApp } from '@/state/app-state';

const PAY: Record<PaymentMethod, [string, string, string]> = {
  mercadopago: ['💳', 'Mercado Pago', 'Tarjeta, débito o dinero en cuenta'],
  efectivo: ['💵', 'Efectivo', '¿Con cuánto pagás? Te llevamos el vuelto'],
  transferencia: ['🏦', 'Transferencia', 'Al alias del local'],
};

/** Todo en una pantalla: envío o retiro, dirección con horario estimado, cómo pagás, Puntos Trappi de un toque y el ahorro en verde. */
export default function CheckoutScreen() {
  const insets = useSafeAreaInsets();
  const { cart, location, setLocation, customer, setCustomer, clearCart, rememberOrder, account, addToCart, callIfMissing } = useApp();
  const [form, setForm] = useState({ ...customer, address: customer.address || location?.label || '', notes: '', coupon: '' });
  const config = useFetch(() => api.config(), []);
  const needsLogin = !account && !!config.data?.account?.required;
  const [filledFor, setFilledFor] = useState<number | null>(null);
  if (account && filledFor !== account.id) {
    setFilledFor(account.id);
    setForm(f => ({ ...f, first_name: f.first_name || account.first_name, last_name: f.last_name || account.last_name, phone: f.phone || account.phone,
      address: f.address || account.address, reference: f.reference || account.reference }));
  }
  // lo que eligió en la ficha del local (cafetería: «Retiro» de entrada)
  const [method, setMethod] = useState<'delivery' | 'retiro'>(prefs.method ?? 'delivery');
  const [pay, setPay] = useState<PaymentMethod>('efectivo');
  const [cashWith, setCashWith] = useState('');
  const [coupon, setCoupon] = useState('');
  const [usePoints, setUsePoints] = useState(false);
  const [useVoucher, setUseVoucher] = useState(true);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [when, setWhen] = useState(''); // '' = lo antes posible; '2026-10-22T20:15' = programado
  const [day, setDay] = useState(0);
  const [addrId, setAddrId] = useState<number | null>(null);
  const [editData, setEditData] = useState(false);
  const [more, setMore] = useState<'coupon' | 'notes' | null>(null);
  const saved = useFetch(() => (account ? api.myAddresses().then(r => r.addresses) : Promise.resolve([] as SavedAddress[])), [account?.id]);
  const set = (k: keyof typeof form) => (v: string) => setForm(f => ({ ...f, [k]: v }));

  useEffect(() => {
    if (!cart.length) return;
    let alive = true;
    api.quote(quoteBody(cart, location, { delivery_method: method, coupon, use_points: usePoints, use_voucher: useVoucher }))
      .then(q => {
        if (!alive) return;
        setQuote(q);
        if (method === 'delivery' && q.store && (!q.store.delivery_enabled || q.store.coverage.covered === false)) setMethod('retiro');
      })
      .catch(e => alive && setError(e.message));
    return () => { alive = false; };
  }, [cart, location, method, coupon, usePoints, useVoucher]);

  const sched = quote?.schedule ?? [];
  const openNow = !!quote?.store?.is_open;
  if (quote && !openNow && !when && sched.length) setWhen(sched[0].values[0]);

  if (!cart.length) return <Empty emoji="🛒" title="Tu pedido está vacío" />;
  const store = quote?.store;
  const pickAddress = (a: SavedAddress) => {
    setAddrId(a.id);
    setForm(f => ({ ...f, address: a.address, reference: a.reference || '' }));
    if (a.lat != null && a.lng != null) setLocation({ lat: a.lat, lng: a.lng, label: a.address });
  };
  const addTogether = (p: Product) => {
    if (!store) return;
    addToCart({ product_id: p.id, quantity: 1, modifiers: [], name: p.name, unit_price: p.price, modifiers_text: null, store_slug: store.slug, store_name: store.name });
  };
  const canDeliver = !!store && store.delivery_enabled && store.coverage.covered !== false;
  const needsLocation = method === 'delivery' && !!store?.coverage.zoned && !location;
  const methods = [...(store?.mp_available ? ['mercadopago'] : []), ...(store?.payment_methods ?? ['efectivo', 'transferencia'])] as PaymentMethod[];
  const hasData = !!form.first_name.trim() && !!form.phone.trim();
  const byWeight = cart.some(l => l.grams);
  const etaText = () => {
    if (when) return `programado: ${when.slice(11)}`;
    const now = new Date();
    const a = new Date(now.getTime() + (store?.eta_min ?? 30) * 60000), b = new Date(now.getTime() + (store?.eta_max ?? 40) * 60000);
    const hm = (d: Date) => `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
    return `llega ${hm(a)}–${hm(b)}`;
  };

  const submit = async () => {
    setError(null);
    if (!form.first_name.trim() || !form.phone.trim()) { setEditData(true); return setError('Completá tu nombre y teléfono.'); }
    if (method === 'delivery' && !form.address.trim()) return setError('Indicá la dirección de entrega.');
    if (!openNow && !when) return setError('El local está cerrado: elegí un horario para programar tu pedido.');
    const cash = pay === 'efectivo' ? parseMoney(cashWith) : null;
    if (cash !== null && quote && cash < quote.total) return setError(`El monto con el que pagás es menor al total (${money(quote.total)}).`);
    setSending(true);
    try {
      const pushToken = await getPushTokenQuick();
      const res = await api.createOrder({
        ...quoteBody(cart, location, { delivery_method: method, coupon, use_points: usePoints, use_voucher: useVoucher }),
        first_name: form.first_name.trim(), last_name: form.last_name.trim(), phone: form.phone.trim(),
        address: method === 'delivery' ? form.address.trim() : '', reference: method === 'delivery' ? form.reference.trim() : '', notes: form.notes.trim(),
        push_token: pushToken || '', platform: Platform.OS, payment_method: pay, cash_with: cash, scheduled_for: when, call_if_missing: callIfMissing,
      });
      setCustomer({ first_name: form.first_name.trim(), last_name: form.last_name.trim(), phone: form.phone.trim(), address: form.address.trim(), reference: form.reference.trim() });
      rememberOrder({ id: res.id, token: res.token, store_name: store?.name || cart[0].store_name, created_at: new Date().toISOString(), fromAccount: !!account });
      clearCart();
      router.dismissAll();
      router.push({ pathname: '/order/[id]', params: { id: String(res.id), nuevo: '1' } });
      if (res.pay_path) Linking.openURL(API_URL + res.pay_path);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No pudimos enviar el pedido.');
    } finally {
      setSending(false);
    }
  };

  return (
    <KeyboardAvoidingView style={{ flex: 1, backgroundColor: colors.bg }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={[st.head, { paddingTop: insets.top + 8 }]}>
        <Pressable onPress={() => router.back()} style={st.round} accessibilityLabel="Volver"><Ionicons name="chevron-back" size={22} color={colors.ink} /></Pressable>
        <Text style={st.title}>Confirmá tu pedido</Text>
      </View>
      <ScrollView contentContainerStyle={{ padding: 16, paddingTop: 4, paddingBottom: 24, gap: 12 }} keyboardShouldPersistTaps="handled">
        {needsLogin && <LoginCard title="Entrá para hacer tu pedido" />}

        {/* envío o retiro, dirección y horario */}
        <View style={st.card}>
          <View style={st.seg}>
            {(['delivery', 'retiro'] as const).map(m => {
              const off = m === 'delivery' && !canDeliver;
              return (
                <Pressable key={m} disabled={off} onPress={() => setMethod(m)} style={[st.segBtn, method === m && st.segOn, off && { opacity: 0.4 }]} accessibilityRole="radio" accessibilityState={{ checked: method === m, disabled: off }}>
                  <Ill e={m === 'delivery' ? '🛵' : '🏪'} size={20} /><Text style={st.segText}>{m === 'delivery' ? 'Envío' : 'Retiro'}</Text>
                </Pressable>
              );
            })}
          </View>
          {method === 'delivery' ? (
            needsLocation ? (
              <Pressable onPress={() => router.push('/location')} style={st.addr}><Ill e="📍" size={30} /><Text style={[st.addrTitle, { flex: 1, color: colors.brand }]}>Marcá tu ubicación para calcular el envío</Text></Pressable>
            ) : (
              <View style={st.addr}>
                <Ill e="🏠" size={34} />
                <View style={{ flex: 1 }}>
                  <Text style={st.addrTitle} numberOfLines={1}>{form.address || location?.label || 'Tu dirección'}</Text>
                  <Text style={st.addrSub}>{form.reference ? `${form.reference} · ` : ''}{etaText()}</Text>
                </View>
                <Pressable onPress={() => router.push('/location')} hitSlop={8}><Text style={st.link}>Cambiar</Text></Pressable>
              </View>
            )
          ) : (
            <View style={st.addr}>
              <Ill e="🏪" size={34} />
              <View style={{ flex: 1 }}>
                <Text style={st.addrTitle} numberOfLines={1}>Retirás en {store?.name ?? 'el local'}</Text>
                <Text style={st.addrSub} numberOfLines={1}>{store?.address ? `${store.address} · ` : ''}{when ? `programado: ${when.slice(11)}` : `listo en ${store?.eta_min ?? 20}–${store?.eta_max ?? 30} min`}</Text>
              </View>
            </View>
          )}
          {method === 'delivery' && !!saved.data?.length && (
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8, paddingTop: 10 }}>
              {saved.data.map(a => (
                <Pressable key={a.id} onPress={() => pickAddress(a)} style={[st.pill, addrId === a.id && st.pillOn]} accessibilityRole="button" accessibilityLabel={`Usar ${a.label}: ${a.address}`}>
                  <Text style={[st.pillText, addrId === a.id && { color: colors.brand }]}>{a.label}</Text>
                </Pressable>
              ))}
            </ScrollView>
          )}
          {method === 'delivery' && store?.coverage.mode === 'trappi' && store.coverage.covered === false && (
            <Text style={st.err}>Fuera de cobertura. {store.coverage.reason || 'Esta dirección está fuera de la zona de entrega.'}</Text>
          )}
          {(sched.length > 0 || (quote && !openNow)) && (
            <View style={{ marginTop: 12, gap: 8 }}>
              <View style={st.seg}>
                {([['', '⚡', 'Lo antes posible'], ['sched', '🕒', 'Programar']] as const).map(([k, e, title]) => {
                  const on = k === '' ? !when : !!when;
                  const off = k === '' ? !openNow : !sched.length;
                  return (
                    <Pressable key={k} disabled={off} onPress={() => setWhen(k === '' ? '' : sched[day]?.values[0] || sched[0].values[0])} style={[st.segBtn, on && st.segOn, off && { opacity: 0.4 }]} accessibilityRole="radio" accessibilityState={{ checked: on, disabled: off }}>
                      <Ill e={e} size={16} /><Text style={[st.segText, { fontSize: 13.5 }]}>{title}</Text>
                    </Pressable>
                  );
                })}
              </View>
              {!!when && (
                <>
                  <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
                    {sched.map((d, i) => <Pressable key={d.date} onPress={() => { setDay(i); setWhen(d.values[0]); }} style={[st.pill, i === day && st.pillOn]}><Text style={[st.pillText, i === day && { color: colors.brand }]}>{d.label}</Text></Pressable>)}
                  </ScrollView>
                  <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
                    {(sched[day] ?? sched[0])?.values.map((v, i) => <Pressable key={v} onPress={() => setWhen(v)} style={[st.pill, when === v && st.pillOn]}><Text style={[st.pillText, when === v && { color: colors.brand }]}>{(sched[day] ?? sched[0]).slots[i]}</Text></Pressable>)}
                  </ScrollView>
                </>
              )}
            </View>
          )}
        </View>

        {/* tus datos: si ya están, en una línea */}
        <View style={st.card}>
          {hasData && !editData ? (
            <View style={st.addr}>
              <Ill e="👤" size={30} />
              <View style={{ flex: 1 }}>
                <Text style={st.addrTitle} numberOfLines={1}>{`${form.first_name} ${form.last_name}`.trim()}</Text>
                <Text style={st.addrSub}>{form.phone}</Text>
              </View>
              <Pressable onPress={() => setEditData(true)} hitSlop={8}><Text style={st.link}>Editar</Text></Pressable>
            </View>
          ) : (
            <View style={{ gap: 8 }}>
              <Text style={st.label}>TUS DATOS</Text>
              <View style={{ flexDirection: 'row', gap: 8 }}>
                <Field style={{ flex: 1, minWidth: 0 }} placeholder="Nombre" value={form.first_name} onChangeText={set('first_name')} autoComplete="given-name" />
                <Field style={{ flex: 1, minWidth: 0 }} placeholder="Apellido" value={form.last_name} onChangeText={set('last_name')} autoComplete="family-name" />
              </View>
              <Field placeholder="Teléfono (WhatsApp)" value={form.phone} onChangeText={set('phone')} keyboardType="phone-pad" autoComplete="tel" />
              {method === 'delivery' && <Field placeholder="Calle, número, piso/depto" value={form.address} onChangeText={set('address')} autoComplete="street-address" />}
              {method === 'delivery' && <Field placeholder="Referencia (opcional): portón negro, timbre 2…" value={form.reference} onChangeText={set('reference')} />}
            </View>
          )}
        </View>

        {/* cómo pagás */}
        <View style={st.card}>
          <Text style={st.label}>¿CÓMO PAGÁS?</Text>
          {methods.map((m, i) => (
            <Pressable key={m} onPress={() => setPay(m)} style={[st.payRow, i > 0 && st.paySep]} accessibilityRole="radio" accessibilityState={{ checked: pay === m }}>
              <Ill e={PAY[m][0]} size={28} />
              <View style={{ flex: 1 }}>
                <Text style={st.payTitle}>{PAY[m][1]}</Text>
                <Text style={st.paySub}>{m === 'transferencia' && store?.transfer_alias ? `Alias ${store.transfer_alias}` : m === 'efectivo' ? `${method === 'delivery' ? 'Al recibir' : 'Al retirar'} · te llevamos el vuelto` : PAY[m][2]}</Text>
              </View>
              <View style={[st.radio, pay === m && st.radioOn]}>{pay === m && <View style={st.radioDot} />}</View>
            </Pressable>
          ))}
          {pay === 'efectivo' && <Field placeholder="¿Con cuánto pagás? (opcional)" value={cashWith} onChangeText={setCashWith} keyboardType="numeric" style={{ marginTop: 6 }} />}
          {pay === 'transferencia' && <Text style={st.payNote}>{store?.transfer_alias ? `Transferí ${money(quote?.total)} al alias ${store.transfer_alias} y mandale el comprobante al local.` : 'Después de confirmar, el local te pasa sus datos por WhatsApp.'}</Text>}
          {pay === 'mercadopago' && <Text style={st.payNote}>Al confirmar te llevamos a Mercado Pago. El repartidor no te cobra nada.{byWeight ? ' Lo que va por peso se cobra al precio de ahora.' : ''}</Text>}
        </View>

        {!!quote?.points?.enabled && (
          <View style={st.points}>
            <Ill e="🥇" size={34} />
            <View style={{ flex: 1 }}>
              <Text style={st.pointsTitle}>{quote.points.usable ? `Usar ${quote.points.usable.toLocaleString('es-AR')} Puntos Trappi` : `Tenés ${quote.points.balance.toLocaleString('es-AR')} Puntos Trappi`}</Text>
              <Text style={st.pointsSub}>{quote.points.usable ? `-${money(quote.points.discount)}${quote.points.earn ? ` y sumás ${quote.points.earn} más` : ''}` : quote.points.reason || (quote.points.earn ? `Con este pedido sumás ${quote.points.earn}` : 'En este pedido no se pueden usar.')}</Text>
            </View>
            {!!quote.points.usable && <Switch value={usePoints} onValueChange={setUsePoints} trackColor={{ true: '#16A34A', false: colors.line }} thumbColor="#fff" accessibilityLabel="Usar mis puntos" />}
          </View>
        )}
        {!!quote?.voucher && (
          <View style={[st.points, { backgroundColor: '#FFF1F2' }]}>
            <Ill e="🎟️" size={30} />
            <View style={{ flex: 1 }}>
              <Text style={st.pointsTitle}>Descuento de Trappi</Text>
              <Text style={st.pointsSub}>{quote.voucher.usable ? `Ahorrás ${money(quote.voucher.discount)} · vence el ${quote.voucher.expires_text}` : quote.voucher.text}</Text>
            </View>
            {quote.voucher.usable && <Switch value={useVoucher} onValueChange={setUseVoucher} trackColor={{ true: '#16A34A', false: colors.line }} thumbColor="#fff" accessibilityLabel="Usar mi descuento" />}
          </View>
        )}

        <View style={st.card}>
          <Pressable onPress={() => setMore(m => (m === 'coupon' ? null : 'coupon'))} style={st.moreRow}><Ill e="🎫" size={22} /><Text style={st.moreText}>{coupon && !quote?.coupon_error ? `Cupón ${coupon}` : 'Tengo un cupón'}</Text><Ionicons name={more === 'coupon' ? 'chevron-up' : 'chevron-down'} size={18} color={colors.muted} /></Pressable>
          {more === 'coupon' && (
            <View style={{ flexDirection: 'row', gap: 8, marginTop: 8 }}>
              <Field style={{ flex: 1, minWidth: 0, marginBottom: 0 }} placeholder="Código" value={form.coupon} onChangeText={set('coupon')} autoCapitalize="characters" autoCorrect={false} />
              <Pressable onPress={() => { if (coupon && coupon === form.coupon.trim()) { setCoupon(''); set('coupon')(''); } else setCoupon(form.coupon.trim()); }} style={st.apply}>
                <Text style={st.applyText}>{coupon && coupon === form.coupon.trim() ? 'Quitar' : 'Aplicar'}</Text>
              </Pressable>
            </View>
          )}
          {!!coupon && quote?.coupon_error && <Text style={st.err}>{quote.coupon_error}</Text>}
          <Pressable onPress={() => setMore(m => (m === 'notes' ? null : 'notes'))} style={[st.moreRow, st.paySep]}><Ill e="💬" size={22} /><Text style={st.moreText}>{form.notes ? form.notes : 'Nota para el local'}</Text><Ionicons name={more === 'notes' ? 'chevron-up' : 'chevron-down'} size={18} color={colors.muted} /></Pressable>
          {more === 'notes' && <Field placeholder="Sin cebolla, tocar timbre… (opcional)" value={form.notes} onChangeText={set('notes')} multiline style={{ minHeight: 64, textAlignVertical: 'top', marginTop: 8 }} />}
        </View>

        {!!quote?.together?.length && (
          <View style={st.card}>
            <Text style={st.label}>¿LE SUMÁS ALGO?</Text>
            {quote.together.map(p => (
              <View key={p.id} style={st.moreRow}>
                <Ill e={p.emoji} size={26} /><Text style={[st.moreText, { flex: 1 }]} numberOfLines={1}>{p.name} · <Text style={{ fontWeight: '900' }}>{money(p.price)}</Text></Text>
                {p.customizable || p.weight
                  ? <Pressable onPress={() => router.push({ pathname: '/product/[id]', params: { id: String(p.id) } })} style={st.addSmall}><Text style={st.addSmallText}>Elegir</Text></Pressable>
                  : <Pressable onPress={() => addTogether(p)} style={st.addSmall} accessibilityLabel={`Agregar ${p.name}`}><Text style={st.addSmallText}>+ Sumar</Text></Pressable>}
              </View>
            ))}
          </View>
        )}

        {/* totales: el ahorro en verde */}
        <View style={[st.card, { gap: 8 }]}>
          {cart.map(l => (
            <View key={`${l.product_id}-${l.modifiers.join('-')}-${l.grams ?? ''}`} style={st.row}>
              <Text style={st.lineName} numberOfLines={1}>{l.quantity}× {l.name}{l.grams ? ` · ${weightLabel(l.grams)} aprox.` : ''}</Text>
              <Text style={st.lineAmt}>{money(l.unit_price * l.quantity)}</Text>
            </View>
          ))}
          <View style={st.sep} />
          <View style={st.row}><Text style={st.muted}>Productos</Text><Text style={st.amt}>{money(quote?.subtotal)}</Text></View>
          {method === 'delivery' && <View style={st.row}><Text style={st.muted}>Envío</Text><Text style={st.amt}>{quote?.shipping === 0 ? 'Gratis' : money(quote?.shipping)}</Text></View>}
          {(quote?.promos ?? []).map(pr => <View key={pr.name} style={st.row}><Text style={st.good}>🏷 {pr.name}</Text><Text style={st.good}>-{money(pr.amount)}</Text></View>)}
          {!!quote && quote.discount - (quote.promo_discount ?? 0) > 0 && <View style={st.row}><Text style={st.good}>Cupón {quote.coupon_code}</Text><Text style={st.good}>-{money(quote.discount - (quote.promo_discount ?? 0))}</Text></View>}
          {!!quote?.voucher_discount && <View style={st.row}><Text style={st.good}>Descuento Trappi</Text><Text style={st.good}>-{money(quote.voucher_discount)}</Text></View>}
          {!!quote?.points_discount && <View style={st.row}><Text style={st.good}>Puntos Trappi</Text><Text style={st.good}>-{money(quote.points_discount)}</Text></View>}
          <View style={st.sep} />
          <View style={st.row}><Text style={st.total}>Total{byWeight ? ' aprox.' : ''}</Text><Text style={st.total}>{money(quote?.total)}</Text></View>
          {method === 'delivery' && <Text style={st.paySub}>Te damos un PIN para que se lo digas al repartidor cuando te entregue.</Text>}
        </View>
        {error && <View style={st.errBox}><Text style={st.err}>{error}</Text></View>}
      </ScrollView>
      <View style={[st.footer, { paddingBottom: insets.bottom + 12 }]}>
        <Pressable onPress={submit} disabled={!quote || needsLocation || needsLogin || sending} style={[st.go, (!quote || needsLocation || needsLogin || sending) && { opacity: 0.5 }]} accessibilityRole="button">
          <Text style={st.goText}>{needsLogin ? 'Entrá con tu cuenta para pedir' : sending ? 'Enviando…' : pay === 'mercadopago' ? 'Confirmar y pagar' : 'Confirmar pedido'}</Text>
          {!needsLogin && !!quote && <Text style={st.goText}>{money(quote.total)}</Text>}
        </Pressable>
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
  head: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 16, paddingBottom: 12, backgroundColor: colors.bg },
  round: { width: 42, height: 42, borderRadius: 21, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center' },
  title: { fontSize: 24, fontWeight: '900', color: colors.ink, letterSpacing: -0.6 },
  card: { backgroundColor: '#fff', borderRadius: 22, padding: 14 },
  seg: { flexDirection: 'row', backgroundColor: '#F4F3F8', borderRadius: 16, padding: 4, gap: 4 },
  segBtn: { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, height: 42, borderRadius: 12 },
  segOn: { backgroundColor: '#fff', shadowColor: '#1E143C', shadowOpacity: 0.08, shadowRadius: 6, shadowOffset: { width: 0, height: 2 }, elevation: 2 },
  segText: { fontWeight: '900', color: colors.ink, fontSize: 15 },
  addr: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingTop: 12 },
  addrTitle: { fontWeight: '900', color: colors.ink, fontSize: 16 },
  addrSub: { color: colors.muted, fontSize: 13, marginTop: 1 },
  link: { color: colors.brand, fontWeight: '900', fontSize: 14 },
  pill: { paddingHorizontal: 13, paddingVertical: 8, borderRadius: 99, borderWidth: 1.5, borderColor: colors.line, backgroundColor: '#fff' },
  pillOn: { borderColor: colors.brand, backgroundColor: colors.brandSoft },
  pillText: { fontWeight: '800', color: colors.ink, fontSize: 13.5 },
  label: { color: colors.muted, fontWeight: '900', fontSize: 12.5, letterSpacing: 0.8, marginBottom: 6 },
  payRow: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 12 },
  paySep: { borderTopWidth: 1, borderTopColor: '#F1EFF5' },
  payTitle: { fontWeight: '900', color: colors.ink, fontSize: 15.5 },
  paySub: { color: colors.muted, fontSize: 12.5, marginTop: 1 },
  radio: { width: 24, height: 24, borderRadius: 12, borderWidth: 2, borderColor: '#D3CEDD', alignItems: 'center', justifyContent: 'center' },
  radioOn: { borderColor: colors.brand, backgroundColor: colors.brand },
  radioDot: { width: 9, height: 9, borderRadius: 5, backgroundColor: '#fff' },
  payNote: { color: colors.ink, fontSize: 13, backgroundColor: colors.brandSoft, borderRadius: 12, padding: 10, marginTop: 6 },
  points: { flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: '#FEF6C3', borderRadius: 22, padding: 14 },
  pointsTitle: { fontWeight: '900', color: colors.ink, fontSize: 15.5 },
  pointsSub: { color: '#78350F', fontSize: 12.5, marginTop: 1 },
  moreRow: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 8 },
  moreText: { flex: 1, color: colors.ink, fontWeight: '700', fontSize: 14.5 },
  apply: { paddingHorizontal: 16, borderRadius: 12, backgroundColor: colors.brandSoft, justifyContent: 'center' },
  applyText: { color: colors.brand, fontWeight: '900' },
  addSmall: { paddingHorizontal: 12, paddingVertical: 7, borderRadius: 99, backgroundColor: colors.brandSoft },
  addSmallText: { color: colors.brand, fontWeight: '900' },
  input: { backgroundColor: '#F7F6FA', borderRadius: 12, paddingHorizontal: 14, paddingVertical: 12, fontSize: 16, color: colors.ink, marginBottom: 0 },
  row: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 10 },
  lineName: { flex: 1, color: colors.ink, fontSize: 13.5 },
  lineAmt: { color: colors.ink, fontSize: 13.5 },
  sep: { height: 1, backgroundColor: '#F1EFF5' },
  muted: { color: colors.muted, fontSize: 15 },
  amt: { color: colors.ink, fontSize: 15 },
  good: { color: colors.good, fontWeight: '900', fontSize: 15 },
  total: { fontSize: 21, fontWeight: '900', color: colors.ink, letterSpacing: -0.4 },
  err: { color: colors.bad, fontWeight: '700', marginTop: 6 },
  errBox: { padding: 12, borderRadius: 16, backgroundColor: colors.badSoft },
  footer: { paddingHorizontal: 16, paddingTop: 12, backgroundColor: '#fff', borderTopWidth: 1, borderTopColor: colors.line },
  go: { height: 58, borderRadius: 18, backgroundColor: colors.brand, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 20,
    shadowColor: colors.brand, shadowOpacity: 0.4, shadowRadius: 12, shadowOffset: { width: 0, height: 6 }, elevation: 5 },
  goText: { color: '#fff', fontWeight: '900', fontSize: 17 },
});
