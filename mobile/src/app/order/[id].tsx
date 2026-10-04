import Ionicons from '@expo/vector-icons/Ionicons';
import { Stack, useLocalSearchParams } from 'expo-router';
import * as Notifications from 'expo-notifications';
import { useEffect, useState } from 'react';
import { AppState, Linking, Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

import { Button, Chip, Empty, ErrorState, Loading, statusTone, s as ui } from '@/components/ui';
import { api } from '@/lib/api';
import { money, timeOf } from '@/lib/format';
import { orderIdFrom, registerOrderPush } from '@/lib/push';
import { colors, radius } from '@/lib/theme';
import type { Order } from '@/lib/types';
import { useFetch } from '@/lib/useFetch';
import { useApp } from '@/state/app-state';

const POLL_MS = 15000;

export default function OrderScreen() {
  const { id, nuevo } = useLocalSearchParams<{ id: string; nuevo?: string }>();
  const { orders } = useApp();
  const saved = orders.find(o => String(o.id) === id);
  const res = useFetch(() => (saved ? api.order(saved.id, saved.token) : Promise.reject(new Error('Este pedido no está guardado en este teléfono.'))), [id, saved?.token]);
  const o = res.data;

  // mientras el pedido está en curso se actualiza solo (y al volver a la app)
  useEffect(() => {
    if (!o || o.final) return;
    const timer = setInterval(res.refresh, POLL_MS);
    const sub = AppState.addEventListener('change', s => s === 'active' && res.refresh());
    return () => { clearInterval(timer); sub.remove(); };
  }, [o?.final, o?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  // el teléfono queda anotado para los avisos de este pedido (y si llega uno, se actualiza al instante)
  useEffect(() => {
    if (!saved || o?.final !== false) return;
    registerOrderPush(saved.id, saved.token);
    const sub = Notifications.addNotificationReceivedListener(n => orderIdFrom(n) === saved.id && res.refresh());
    return () => sub.remove();
  }, [saved?.id, o?.final]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!saved) return <Empty emoji="🧾" title="No encontramos este pedido" text="Sólo podés seguir pedidos hechos desde este teléfono." />;
  if (res.loading && !o) return <Loading />;
  if (!o) return <ErrorState message={res.error || 'No encontramos ese pedido.'} onRetry={res.reload} />;
  const cancelled = o.status === 'CANCELADO';

  return (
    <ScrollView style={{ backgroundColor: colors.bg }} contentContainerStyle={{ padding: 16, paddingBottom: 32 }}
      refreshControl={<RefreshControl refreshing={res.refreshing} onRefresh={res.refresh} tintColor={colors.brand} />}>
      <Stack.Screen options={{ title: `Pedido #${o.id}` }} />
      {nuevo === '1' && o.status === 'PENDIENTE' && (
        <View style={st.hello}>
          <Text style={{ fontSize: 34 }}>🎉</Text>
          <Text style={st.helloTitle}>¡Pedido enviado!</Text>
          <Text style={{ color: colors.ink, textAlign: 'center' }}>{o.store.name} ya lo está viendo. Te avisamos acá apenas lo confirme.</Text>
        </View>
      )}
      <View style={st.card}>
        <View style={ui.row}>
          <Text style={ui.h2} numberOfLines={1}>{o.store.name}</Text>
          <Chip label={o.status_label} tone={statusTone(o.status)} />
        </View>
        <Text style={ui.muted}>{o.delivery_method === 'delivery' ? `🛵 Delivery${o.address ? ' a ' + o.address : ''}` : '🛍 Retirás en el local'} · {timeOf(o.created_at)}</Text>
        {!o.final && <Text style={{ color: colors.ink, marginTop: 6 }}>Demora estimada: <Text style={{ fontWeight: '800' }}>{o.store.eta_min} min</Text></Text>}
      </View>

      {cancelled ? (
        <View style={[st.card, { backgroundColor: colors.badSoft, borderColor: colors.badSoft }]}><Text style={{ color: colors.bad, fontWeight: '700' }}>El comercio canceló este pedido. Si tenés dudas, escribile por WhatsApp.</Text></View>
      ) : (
        <View style={st.card}>
          {o.steps.map((s, i) => (
            <View key={s.status} style={st.step}>
              <View style={{ alignItems: 'center' }}>
                <View style={[st.dot, (s.done || s.current) && st.dotOn, s.current && !o.final && st.dotNow]}>
                  {(s.done || (s.current && o.final)) && <Ionicons name="checkmark" size={14} color="#fff" />}
                </View>
                {i < o.steps.length - 1 && <View style={[st.bar, s.done && { backgroundColor: colors.brand }]} />}
              </View>
              <View style={{ flex: 1, paddingBottom: 16 }}>
                <Text style={[st.stepLabel, !(s.done || s.current) && { color: colors.muted, fontWeight: '600' }]}>{s.label}</Text>
                {!!s.at && <Text style={ui.muted}>{timeOf(s.at)}</Text>}
              </View>
            </View>
          ))}
        </View>
      )}

      {!!o.delivery_pin && (
        <View style={st.pin}>
          <View style={{ flex: 1 }}>
            <Text style={st.stepLabel}>Tu PIN de entrega</Text>
            <Text style={ui.muted}>Decíselo al repartidor cuando te entregue el pedido. No lo compartas antes.</Text>
          </View>
          <Text style={st.pinValue} accessibilityLabel={`PIN ${o.delivery_pin.split('').join(' ')}`} selectable>{o.delivery_pin}</Text>
        </View>
      )}
      {!cancelled && !!o.payment && <PaymentCard o={o} />}

      {!!o.whatsapp_url && (
        <Button title="Confirmar por WhatsApp" onPress={() => Linking.openURL(o.whatsapp_url!)} style={{ marginTop: 14, backgroundColor: '#1FA855', borderColor: '#1FA855' }} />
      )}
      {!o.whatsapp_url && !!o.store.whatsapp && (
        <Pressable onPress={() => Linking.openURL(`https://wa.me/${o.store.whatsapp!.replace(/\D/g, '')}?text=${encodeURIComponent(`Hola! Consulta por mi pedido #${o.id}`)}`)} style={st.wa}>
          <Ionicons name="logo-whatsapp" size={18} color={colors.good} /><Text style={{ color: colors.good, fontWeight: '700' }}>Escribirle al comercio</Text>
        </Pressable>
      )}

      {o.can_review && <ReviewForm orderId={o.id} token={saved.token} onDone={res.refresh} />}
      {o.review && (
        <View style={st.card}>
          <Text style={st.stepLabel}>Tu opinión</Text>
          <Text style={{ color: colors.star, fontSize: 18, letterSpacing: 2 }}>{'★'.repeat(o.review.rating)}<Text style={{ color: colors.line }}>{'★'.repeat(5 - o.review.rating)}</Text></Text>
          {!!o.review.comment && <Text style={{ color: colors.ink }}>{o.review.comment}</Text>}
          {!!o.review.reply && <View style={st.reply}><Text style={{ fontWeight: '700', color: colors.brand }}>Respuesta del comercio</Text><Text style={{ color: colors.ink }}>{o.review.reply}</Text></View>}
        </View>
      )}

      <View style={st.card}>
        <Text style={[st.stepLabel, { marginBottom: 6 }]}>Detalle</Text>
        {o.items.map((it, i) => (
          <View key={i} style={[ui.row, { alignItems: 'flex-start', marginBottom: 6 }]}>
            <View style={{ flex: 1 }}>
              <Text style={{ color: colors.ink }}>{it.quantity}× {it.name}</Text>
              {!!it.modifiers_text && <Text style={ui.muted}>+ {it.modifiers_text}</Text>}
            </View>
            <Text style={{ color: colors.ink }}>{money(it.line_total)}</Text>
          </View>
        ))}
        <View style={{ height: 1, backgroundColor: colors.line, marginVertical: 6 }} />
        <View style={ui.row}><Text style={ui.muted}>Subtotal</Text><Text style={{ color: colors.ink }}>{money(o.subtotal)}</Text></View>
        {o.delivery_method === 'delivery' && <View style={ui.row}><Text style={ui.muted}>Envío</Text><Text style={{ color: colors.ink }}>{o.shipping ? money(o.shipping) : 'Gratis'}</Text></View>}
        {!!o.discount && <View style={ui.row}><Text style={{ color: colors.good }}>Descuento</Text><Text style={{ color: colors.good }}>-{money(o.discount)}</Text></View>}
        <View style={[ui.row, { marginTop: 4 }]}><Text style={st.total}>Total</Text><Text style={st.total}>{money(o.total)}</Text></View>
      </View>
    </ScrollView>
  );
}

function PaymentCard({ o }: { o: Order }) {
  const p = o.payment!;
  const pickup = o.delivery_method === 'retiro';
  return (
    <View style={[st.card, p.paid && { backgroundColor: colors.goodSoft, borderColor: colors.goodSoft }]}>
      <Text style={[st.stepLabel, p.paid && { color: colors.good }]}>Pago · {p.label}</Text>
      {p.paid ? (
        <Text style={{ color: colors.ink }}>✓ Pagado.{!o.final ? ' No tenés que pagar nada al recibir.' : ''}</Text>
      ) : p.method === 'transferencia' ? (
        <>
          <Text style={{ color: colors.ink }}>{p.transfer_alias
            ? <>Transferí <Text style={{ fontWeight: '800' }}>{money(o.total)}</Text> al alias <Text style={{ fontWeight: '800' }} selectable>{p.transfer_alias}</Text> y mandale el comprobante al comercio.</>
            : <>El comercio te pasa sus datos por WhatsApp para que le transfieras <Text style={{ fontWeight: '800' }}>{money(o.total)}</Text>.</>}</Text>
          <Text style={[ui.muted, { fontSize: 12.5 }]}>Cuando el comercio confirme la transferencia lo vas a ver acá. Si no llega a confirmarla, pagás al recibir.</Text>
        </>
      ) : (
        <Text style={{ color: colors.ink }}>Pagás <Text style={{ fontWeight: '800' }}>{money(o.total)}</Text> en efectivo al {pickup ? 'retirar' : 'recibir'}.{p.cash_with ? ` Pagás con ${money(p.cash_with)}${p.change ? `: te llevan ${money(p.change)} de vuelto` : ''}.` : ''}</Text>
      )}
    </View>
  );
}

function ReviewForm({ orderId, token, onDone }: { orderId: number; token: string; onDone: () => void }) {
  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const send = async () => {
    setSending(true); setError(null);
    try { await api.review(orderId, token, rating, comment.trim()); onDone(); }
    catch (e) { setError(e instanceof Error ? e.message : 'No pudimos guardar tu opinión.'); }
    finally { setSending(false); }
  };
  return (
    <View style={st.card}>
      <Text style={st.stepLabel}>¿Qué tal estuvo?</Text>
      <View style={{ flexDirection: 'row', gap: 6, marginVertical: 8 }}>
        {[1, 2, 3, 4, 5].map(n => (
          <Pressable key={n} onPress={() => setRating(n)} hitSlop={6} accessibilityRole="button" accessibilityLabel={`${n} estrellas`}>
            <Text style={{ fontSize: 34, color: n <= rating ? colors.star : colors.line }}>★</Text>
          </Pressable>
        ))}
      </View>
      <TextInput value={comment} onChangeText={setComment} placeholder="Contanos tu experiencia (opcional)" placeholderTextColor={colors.muted} multiline maxLength={2000}
        style={st.input} />
      {error && <Text style={{ color: colors.bad, marginBottom: 8 }}>{error}</Text>}
      <Button title="Enviar opinión" disabled={!rating} loading={sending} onPress={send} />
    </View>
  );
}

const st = StyleSheet.create({
  hello: { alignItems: 'center', gap: 4, padding: 18, borderRadius: radius.md, backgroundColor: colors.goodSoft, marginBottom: 14 },
  helloTitle: { fontSize: 20, fontWeight: '800', color: colors.good },
  pin: { flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: '#fff', borderRadius: radius.md, borderWidth: 2, borderColor: colors.brand, padding: 14, marginTop: 14 },
  pinValue: { fontSize: 36, fontWeight: '900', letterSpacing: 6, color: colors.brand, fontVariant: ['tabular-nums'] },
  card: { backgroundColor: '#fff', borderRadius: radius.md, borderWidth: 1, borderColor: colors.line, padding: 14, marginTop: 14, gap: 4 },
  step: { flexDirection: 'row', gap: 12 },
  dot: { width: 24, height: 24, borderRadius: 12, borderWidth: 2, borderColor: colors.line, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center' },
  dotOn: { backgroundColor: colors.brand, borderColor: colors.brand },
  dotNow: { backgroundColor: '#fff', borderWidth: 6 },
  bar: { width: 2, flex: 1, backgroundColor: colors.line, marginVertical: 2 },
  stepLabel: { fontSize: 15.5, fontWeight: '800', color: colors.ink },
  wa: { marginTop: 14, flexDirection: 'row', gap: 8, alignItems: 'center', justifyContent: 'center', padding: 12 },
  reply: { marginTop: 8, padding: 10, borderRadius: radius.sm, backgroundColor: colors.brandSoft, gap: 2 },
  input: { backgroundColor: colors.bg, borderRadius: radius.sm, padding: 12, minHeight: 80, textAlignVertical: 'top', fontSize: 15, color: colors.ink, marginBottom: 10 },
  total: { fontSize: 18, fontWeight: '800', color: colors.ink },
});
