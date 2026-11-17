import Ionicons from '@expo/vector-icons/Ionicons';
import { CameraView, useCameraPermissions } from 'expo-camera';
import { Stack, router, useLocalSearchParams } from 'expo-router';
import * as Notifications from 'expo-notifications';
import { useEffect, useRef, useState } from 'react';
import { AppState, Image, Linking, Modal, Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Grad, Ill } from '@/components/kit';
import { LiveMap } from '@/components/live-map';
import { Button, Chip, Empty, ErrorState, Loading, statusTone, s as ui } from '@/components/ui';
import { API_URL, api } from '@/lib/api';
import { weightLabel } from '@/lib/cart';
import { money, timeOf } from '@/lib/format';
import { orderIdFrom, registerOrderPush } from '@/lib/push';
import { colors, radius } from '@/lib/theme';
import type { Order, OrderClaim, Tracking } from '@/lib/types';
import { useFetch } from '@/lib/useFetch';
import { useApp } from '@/state/app-state';

const POLL_MS = 15000;
const LIVE_POLL_MS = 8000;  // con el repartidor en camino, más seguido: se lo ve moverse
const DEFAULT_MAP = 'https://tiles.openfreemap.org/styles/liberty';

/** Seguimiento en vivo: dónde está el repartidor y cuánto falta. */
function LiveCard({ t, mapStyle }: { t: Tracking; mapStyle: string }) {
  const title = t.stage === 'other_delivery' ? `${t.name} está entregando otro pedido`
    : t.stage === 'to_you' ? `${t.name} va en camino a tu casa` : `${t.name} va a buscar tu pedido al local`;
  const sub = t.stage === 'other_delivery'
    ? ((t.ahead ?? 1) > 1 ? `Antes de vos tiene ${t.ahead} entregas cerca.` : 'Es cerca de tu casa: después va directo a vos.')
    : t.courier ? 'Lo ves moverse en el mapa.' : 'Todavía no tenemos su ubicación: se actualiza sola.';
  return (
    <View style={st.card}>
      <View style={[ui.row, { alignItems: 'flex-start', gap: 10 }]}>
        <View style={{ flex: 1 }}>
          <Text style={st.stepLabel}>{title}</Text>
          <Text style={ui.muted}>{sub}</Text>
        </View>
        {!!t.eta_min && <View style={st.eta}><Text style={st.etaText}>~{t.eta_min} min</Text></View>}
      </View>
      {t.stage !== 'other_delivery' && <View style={{ marginTop: 10 }}><LiveMap tracking={t} mapStyle={mapStyle} /></View>}
    </View>
  );
}

export default function OrderScreen() {
  const { id, nuevo } = useLocalSearchParams<{ id: string; nuevo?: string }>();
  const insets = useSafeAreaInsets();
  const { orders } = useApp();
  const saved = orders.find(o => String(o.id) === id);
  const res = useFetch(() => (saved ? api.order(saved.id, saved.token) : Promise.reject(new Error('Este pedido no está guardado en este teléfono.'))), [id, saved?.token]);
  const o = res.data;
  const cfg = useFetch(() => api.config(), []);
  const live = !!o?.tracking && !o.final && !!o.tracking.courier && o.tracking.stage !== 'other_delivery';

  // mientras el pedido está en curso se actualiza solo (y al volver a la app)
  useEffect(() => {
    if (!o || o.final) return;
    const timer = setInterval(res.refresh, live ? LIVE_POLL_MS : POLL_MS);
    const sub = AppState.addEventListener('change', s => s === 'active' && res.refresh());
    return () => { clearInterval(timer); sub.remove(); };
  }, [o?.final, o?.status, live]); // eslint-disable-line react-hooks/exhaustive-deps

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
  const delivered = o.status === 'ENTREGADO';
  const back = () => (router.canGoBack() ? router.back() : router.replace('/orders'));

  // lo que va debajo en cualquier estado: avisos, peso real, pago, opinión, reclamo y el detalle
  const rest = (
    <>
      {o.courier_arrived && !o.final && !o.delivery_issue && (
        <View style={[st.card, { backgroundColor: '#E9F9EF', borderColor: '#BFEBD0' }]}>
          <Text style={{ color: '#0B6B45', fontWeight: '900', fontSize: 16 }}>🛵 Tu repartidor llegó</Text>
          <Text style={{ color: colors.ink }}>Te está esperando en la puerta. Si no podés salir, avisale por el chat.</Text>
        </View>
      )}
      {!!o.delivery_issue && (
        <View style={[st.card, { backgroundColor: colors.badSoft, borderColor: colors.badSoft }]}>
          <Text style={{ color: colors.bad, fontWeight: '700' }}>{o.delivery_issue}.</Text>
          {!!o.proof_photo && <Image source={{ uri: API_URL + o.proof_photo }} style={{ width: '100%', height: 200, borderRadius: radius.sm, marginTop: 8 }} resizeMode="cover" accessibilityLabel="Foto de prueba del repartidor" />}
        </View>
      )}
      {cancelled && <View style={[st.card, { backgroundColor: colors.badSoft, borderColor: colors.badSoft }]}><Text style={{ color: colors.bad, fontWeight: '700' }}>{o.delivery_issue ? 'Cancelamos este pedido porque no se pudo entregar.' : 'El local canceló este pedido. Si tenés dudas, escribile por WhatsApp.'}</Text></View>}
      {!!o.weight && <WeightCard o={o} token={saved.token} onDone={res.refresh} />}
      {!!o.pay_path && (
        <View style={[st.card, { borderColor: '#009EE3', borderWidth: 2 }]}>
          <Text style={st.stepLabel}>Falta pagar</Text>
          <Text style={{ color: colors.ink }}>Tu pedido se confirma cuando Mercado Pago apruebe el pago.</Text>
          <Button title={`Pagar ${money(o.total)} con Mercado Pago`} onPress={() => Linking.openURL(API_URL + o.pay_path)} style={{ marginTop: 8, backgroundColor: '#009EE3', borderColor: '#009EE3' }} />
        </View>
      )}
      {!cancelled && !delivered && !!o.payment && <PaymentCard o={o} />}
      {!!o.whatsapp_url && <Button title="Confirmar por WhatsApp" onPress={() => Linking.openURL(o.whatsapp_url!)} style={{ marginTop: 14, backgroundColor: '#1FA855', borderColor: '#1FA855' }} />}
      {o.review && (
        <View style={st.card}>
          <Text style={st.stepLabel}>Tu opinión</Text>
          <Text style={{ color: colors.star, fontSize: 18, letterSpacing: 2 }}>{'★'.repeat(o.review.rating)}<Text style={{ color: colors.line }}>{'★'.repeat(5 - o.review.rating)}</Text></Text>
          {!!o.review.comment && <Text style={{ color: colors.ink }}>{o.review.comment}</Text>}
          {!!o.review.reply && <View style={st.reply}><Text style={{ fontWeight: '700', color: colors.brand }}>Respuesta del local</Text><Text style={{ color: colors.ink }}>{o.review.reply}</Text></View>}
        </View>
      )}
      {!!o.claim && <ClaimCard claim={o.claim} orderId={o.id} token={saved.token} onDone={res.refresh} />}
      {!!o.chat && o.final && <Button title="Ver el chat con el repartidor" variant="ghost" onPress={() => router.push({ pathname: '/chat/[id]', params: { id: String(o.id) } })} style={{ marginTop: 14 }} />}
      <View style={st.card}>
        <Text style={[st.stepLabel, { marginBottom: 6 }]}>Detalle del pedido #{o.id}</Text>
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
        <View style={ui.row}><Text style={ui.muted}>Productos</Text><Text style={{ color: colors.ink }}>{money(o.subtotal)}</Text></View>
        {o.delivery_method === 'delivery' && <View style={ui.row}><Text style={ui.muted}>Envío</Text><Text style={{ color: colors.ink }}>{o.shipping ? money(o.shipping) : 'Gratis'}</Text></View>}
        {!!o.discount && <View style={ui.row}><Text style={{ color: colors.good }}>Descuento</Text><Text style={{ color: colors.good }}>-{money(o.discount)}</Text></View>}
        <View style={[ui.row, { marginTop: 4 }]}><Text style={st.total}>Total</Text><Text style={st.total}>{money(o.total)}</Text></View>
      </View>
      {!o.whatsapp_url && !!o.store.whatsapp && (
        <Pressable onPress={() => Linking.openURL(`https://wa.me/${o.store.whatsapp!.replace(/\D/g, '')}?text=${encodeURIComponent(`Hola! Consulta por mi pedido #${o.id}`)}`)} style={st.wa}>
          <Ionicons name="logo-whatsapp" size={18} color={colors.good} /><Text style={{ color: colors.good, fontWeight: '700' }}>Escribirle al local</Text>
        </Pressable>
      )}
    </>
  );

  // en camino con el repartidor: mapa a pantalla completa, la llegada arriba y la hoja del pedido abajo
  if (live) {
    const t = o.tracking!;
    return (
      <View style={{ flex: 1, backgroundColor: '#E8E5EE' }}>
        <Stack.Screen options={{ headerShown: false }} />
        <LiveMap tracking={t} mapStyle={cfg.data?.map_style || DEFAULT_MAP} full />
        <ScrollView style={StyleSheet.absoluteFill} contentContainerStyle={{ paddingTop: 430, paddingBottom: 0 }}
          refreshControl={<RefreshControl refreshing={res.refreshing} onRefresh={res.refresh} tintColor={colors.brand} />}>
          <View style={[st.sheet, { paddingBottom: insets.bottom + 24 }]}>
            <View style={st.grab} />
            <Segments o={o} />
            <CourierCard o={o} bare />
            {!!o.delivery_pin && <Pin pin={o.delivery_pin} name={t.name} />}
            <View style={[ui.row, { marginTop: 14 }]}><Text style={ui.muted}>Pedido #{o.id} · {o.store.name}</Text><Text style={st.stepLabel}>{money(o.total)}</Text></View>
            {rest}
          </View>
        </ScrollView>
        <View style={[st.liveTop, { paddingTop: insets.top + 8 }]} pointerEvents="box-none">
          <Pressable onPress={back} style={st.round} accessibilityLabel="Volver"><Ionicons name="chevron-back" size={22} color={colors.ink} /></Pressable>
          <View style={st.etaCard}>
            <Ill e="⏱" size={36} />
            <View style={{ flex: 1 }}>
              <Text style={st.etaBig}>{t.eta_min ? `Llega en ${t.eta_min} min` : t.stage === 'to_store' ? 'Va a buscar tu pedido' : 'Va en camino'}</Text>
              <Text style={st.etaSub}>{o.eta_text || (t.stage === 'to_store' ? 'Retira en el local' : 'Hacia tu casa')}</Text>
            </View>
            <View style={st.liveDot}><View style={st.liveDotIn} /><Text style={st.liveText}>En vivo</Text></View>
          </View>
        </View>
      </View>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: colors.bg }}>
      <Stack.Screen options={{ headerShown: false }} />
      <ScrollView contentContainerStyle={{ paddingBottom: 32 }} refreshControl={<RefreshControl refreshing={res.refreshing} onRefresh={res.refresh} tintColor={colors.brand} />}>
        {delivered ? <Celebration o={o} top={insets.top} onBack={back} /> : (
          <View style={[st.plainHead, { paddingTop: insets.top + 8 }]}>
            <Pressable onPress={back} style={st.round} accessibilityLabel="Volver"><Ionicons name="chevron-back" size={22} color={colors.ink} /></Pressable>
            <Text style={st.plainTitle}>Pedido #{o.id}</Text>
          </View>
        )}
        <View style={{ paddingHorizontal: 16 }}>
          {nuevo === '1' && o.status === 'PENDIENTE' && (
            <View style={st.hello}>
              <Ill e="🎉" size={44} />
              <Text style={st.helloTitle}>¡Pedido enviado!</Text>
              <Text style={{ color: colors.ink, textAlign: 'center' }}>{o.store.name} ya lo está viendo. Te avisamos acá apenas lo confirme.</Text>
            </View>
          )}
          {!delivered && !cancelled && <Hero o={o} />}
          {cancelled && (
            <View style={st.card}>
              <View style={ui.row}><Text style={ui.h2} numberOfLines={1}>{o.store.name}</Text><Chip label={o.status_label} tone={statusTone(o.status)} /></View>
              <Text style={ui.muted}>Pedido #{o.id} · {timeOf(o.created_at)}</Text>
            </View>
          )}
          {!o.final && o.tracking?.stage === 'other_delivery' && <LiveCard t={o.tracking} mapStyle={cfg.data?.map_style || DEFAULT_MAP} />}
          {!o.final && (!!o.tracking || !!o.courier) && <CourierCard o={o} />}
          {!!o.delivery_pin && <Pin pin={o.delivery_pin} name={o.tracking?.name || o.courier?.name} />}
          {delivered && o.can_review && <ReviewForm orderId={o.id} token={saved.token} store={o.store.name} onDone={res.refresh} />}
          {rest}
        </View>
      </ScrollView>
    </View>
  );
}

/** Progreso en cuatro tramos con su nombre (el actual en violeta). */
function Segments({ o }: { o: Order }) {
  const steps = o.steps.filter(s => s.status !== 'PENDIENTE');
  const current = steps.findIndex(s => s.current);
  return (
    <View>
      <View style={st.sheetSegs}>
        {steps.map((s, i) => <View key={s.status} style={[st.sheetSeg, (s.done || i < current) && { backgroundColor: colors.brand }, s.current && { backgroundColor: '#B79CF5' }]} />)}
      </View>
      <View style={st.sheetLabels}>
        {steps.map(s => <Text key={s.status} style={[st.sheetLabel, s.current && { color: colors.brand, fontWeight: '900' }]} numberOfLines={1}>{s.label.startsWith('En ') ? 'En camino' : s.label.split(' ')[0]}</Text>)}
      </View>
    </View>
  );
}

function Pin({ pin, name }: { pin: string; name?: string | null }) {
  return (
    <View style={st.pin}>
      <View style={{ flex: 1 }}>
        <Text style={st.pinSmall}>Tu PIN de entrega</Text>
        <Text style={st.pinHint}>{name ? `Dáselo a ${name} al recibir` : 'Decíselo al repartidor al recibir'}</Text>
      </View>
      <View style={st.pinDigits} accessibilityLabel={`PIN ${pin.split('').join(' ')}`}>
        {pin.split('').map((d, i) => <View key={i} style={st.pinBox}><Text style={st.pinDigit}>{d}</Text></View>)}
      </View>
    </View>
  );
}

/** Peso real: lo que pesó cada producto por peso; si se pasó del margen, aceptar o pedir que lo pesen de nuevo. */
function WeightCard({ o, token, onDone }: { o: Order; token: string; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const w = o.weight!;
  const weighed = w.lines.filter(l => l.real);
  if (!weighed.length) return null;
  const answer = async (accept: boolean) => {
    setBusy(true); setErr(null);
    try { await api.weightAnswer(o.id, token, accept); onDone(); } catch (e) { setErr(e instanceof Error ? e.message : 'No se pudo enviar.'); } finally { setBusy(false); }
  };
  const pending = w.status === 'pending';
  return (
    <View style={[st.card, pending && { borderColor: '#F59E0B', borderWidth: 2, backgroundColor: '#FFFBEB' }]}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}><Ill e="⚖" size={24} /><Text style={st.stepLabel}>{pending ? 'Se pasó del peso que pediste' : 'Lo que pesó tu pedido'}</Text></View>
      {weighed.map(l => (
        <View key={l.id} style={[ui.row, { marginTop: 6 }]}>
          <Text style={{ color: colors.ink, flex: 1 }}>{l.name} · pediste {weightLabel(l.ordered)}</Text>
          <Text style={{ color: colors.ink, fontWeight: '900' }}>{weightLabel(l.real!)}{w.adjusts && l.new != null ? ` · ${money(l.new)}` : ''}</Text>
        </View>
      ))}
      {!w.adjusts ? <Text style={[ui.muted, { marginTop: 6 }]}>Pagaste online: se cobra lo que pediste, aunque el peso varíe un poco.</Text>
        : pending ? (
          <>
            <Text style={{ color: colors.ink, marginTop: 8 }}>El total pasaría a <Text style={{ fontWeight: '900' }}>{money(o.total + w.diff)}</Text> (antes {money(o.total)}). ¿Lo aceptás?</Text>
            <View style={{ flexDirection: 'row', gap: 8, marginTop: 10 }}>
              <Button title={`Aceptar ${money(o.total + w.diff)}`} onPress={() => answer(true)} loading={busy} style={{ flex: 1 }} />
              <Button title="Que lo pesen de nuevo" variant="ghost" onPress={() => answer(false)} disabled={busy} style={{ flex: 1 }} />
            </View>
          </>
        ) : w.status === 'rejected' ? <Text style={[ui.muted, { marginTop: 6 }]}>Le avisamos al local que lo pese de nuevo, más cerca de lo que pediste.</Text>
        : <Text style={[ui.muted, { marginTop: 6 }]}>El total ya está ajustado al peso real (hasta ±{w.margin} %).</Text>}
      {!!err && <Text style={{ color: colors.bad, marginTop: 6 }}>{err}</Text>}
    </View>
  );
}

const HERO_TITLE: Record<string, string> = {
  PENDIENTE: 'Esperando que el local lo acepte', CONFIRMADO: '¡Aceptaron tu pedido!', PREPARANDO: 'Lo están preparando',
  LISTO: 'Tu pedido está listo', EN_CAMINO: 'Tu pedido va en camino',
};

/** Arriba del seguimiento: estado grande, cuándo llega y la barra de progreso. */
function Hero({ o }: { o: Order }) {
  const steps = o.steps;
  const current = Math.max(0, steps.findIndex(s => s.current));
  const t = o.tracking;
  const title = o.status === 'LISTO' && o.delivery_method === 'retiro' ? 'Listo para retirar' : HERO_TITLE[o.status] ?? o.status_label;
  const eta = t?.eta_min ? `Llega en ${t.eta_min} min` : o.scheduled_label ? `Programado para ${o.scheduled_label}` : o.eta_text || `Demora estimada: ${o.store.eta_min} min`;
  return (
    <View style={st.hero}>
      <View style={st.heroGlow} />
      <Text style={st.heroStore}>{o.store.name} · Pedido #{o.id}</Text>
      <Text style={st.heroTitle}>{title}</Text>
      <View style={st.heroEta}><Ionicons name="time" size={16} color="#fff" /><Text style={st.heroEtaText}>{eta}</Text></View>
      <View style={st.segs}>
        {steps.map((s, i) => <View key={s.status} style={[st.seg, (s.done || i < current) && st.segOn, s.current && st.segNow]} />)}
      </View>
      <View style={[ui.row, { marginTop: 6 }]}>
        <Text style={st.segLabel}>{steps[0]?.label}</Text>
        <Text style={[st.segLabel, { color: '#fff', fontWeight: '800' }]}>{steps[current]?.label}</Text>
        <Text style={st.segLabel}>{steps[steps.length - 1]?.label}</Text>
      </View>
      <Text style={st.heroWhere}>{o.delivery_method === 'delivery' ? `🛵 A ${o.address || 'tu dirección'}` : '🛍 Retirás en el local'}</Text>
    </View>
  );
}

/** Quién lo lleva: el personaje que eligió el repartidor, su nombre y el chat. */
function CourierCard({ o, bare }: { o: Order; bare?: boolean }) {
  const t = o.tracking;
  const name = t?.name || o.courier?.name;
  if (!name) return null;
  const vehicle = t?.vehicle || o.courier?.vehicle;
  return (
    <View style={[bare ? { marginTop: 16 } : st.card, st.courier]}>
      <View style={[st.cav, { backgroundColor: t?.color || colors.brandSoft }]}><Ill e={t?.avatar || '🛵'} size={30} /></View>
      <View style={{ flex: 1 }}>
        <Text style={st.stepLabel}>{name} te lo lleva</Text>
        <Text style={ui.muted}>{vehicle ? `${vehicle === 'auto' ? '🚗' : vehicle === 'bici' ? '🚲' : '🛵'} ${vehicle[0].toUpperCase()}${vehicle.slice(1)}` : 'Repartidor'}{o.courier_arrived ? ' · Llegó a tu puerta' : ''}</Text>
      </View>
      {!!o.chat && (
        <Pressable onPress={() => router.push({ pathname: '/chat/[id]', params: { id: String(o.id) } })} style={st.cbtn} accessibilityLabel="Chatear con el repartidor">
          <Ill e="💬" size={24} />
        </Pressable>
      )}
    </View>
  );
}

const CONFETTI = [['#6C2BD9', 30, 18, 20], ['#F59E0B', 80, 70, -30], ['#E11D48', 290, 30, 40], ['#0A8F55', 240, 8, -10], ['#38BDF8', 310, 110, 60],
  ['#FF6FB5', 18, 120, -50], ['#FFD43B', 170, 4, 15], ['#8B5CF6', 130, 128, -20]] as const;

/** Pedido entregado: se festeja, con los puntos que sumó. */
function Celebration({ o, top, onBack }: { o: Order; top: number; onBack: () => void }) {
  const at = o.steps.find(s => s.status === 'ENTREGADO')?.at;
  return (
    <Grad colors={['#BEF264', '#86EFAC']} style={[st.party, { paddingTop: top + 8 }]}>
      <Pressable onPress={onBack} style={[st.round, { alignSelf: 'flex-start', zIndex: 2 }]} accessibilityLabel="Volver"><Ionicons name="chevron-back" size={22} color={colors.ink} /></Pressable>
      {CONFETTI.map(([c, x, y, r], i) => <View key={i} style={[st.confetti, { backgroundColor: c, left: x, top: y + top + 40, transform: [{ rotate: `${r}deg` }] }]} />)}
      <Ill e="🥳" size={120} />
      <Text style={st.partyTitle}>¡Que lo disfrutes!</Text>
      <Text style={st.partySub}>Tu pedido de {o.store.name} llegó{at ? ` a las ${timeOf(at)}` : ''} 🙌</Text>
      {!!o.points_earned && (
        <View style={st.earn}>
          <Ill e="🥇" size={40} />
          <View style={{ flex: 1 }}>
            <Text style={st.earnTitle}>+{o.points_earned.toLocaleString('es-AR')} Puntos Trappi</Text>
            <Text style={ui.muted}>Ya están en tu cuenta para tu próximo pedido</Text>
          </View>
        </View>
      )}
    </Grad>
  );
}

function PaymentCard({ o }: { o: Order }) {
  const p = o.payment!;
  const pickup = o.delivery_method === 'retiro';
  return (
    <View style={[st.card, p.paid && { backgroundColor: colors.goodSoft, borderColor: colors.goodSoft }]}>
      <Text style={[st.stepLabel, p.paid && { color: colors.good }]}>Pago · {p.label}</Text>
      {p.online && !p.paid ? (
        <Text style={{ color: colors.ink }}>{p.status_text || 'Esperando el pago online'}. No le pagás nada al repartidor.</Text>
      ) : p.paid ? (
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

const CLAIM_STATUS = { abierto: ['Lo estamos revisando', colors.warn, colors.warnSoft], resuelto: ['Resuelto', colors.good, colors.goodSoft],
  rechazado: ['Revisado', colors.muted, colors.bg] } as const;

/** "¿Tuviste un problema con tu pedido?": motivo, comentario y una foto opcional (con la cámara). Si ya reclamó, cómo va. */
function ClaimCard({ claim, orderId, token, onDone }: { claim: OrderClaim; orderId: number; token: string; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState('');
  const [text, setText] = useState('');
  const [photo, setPhoto] = useState<string | null>(null);
  const [camera, setCamera] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [permission, requestPermission] = useCameraPermissions();
  const cam = useRef<CameraView>(null);

  if (!claim.can_claim) {
    const [label, tone, bg] = CLAIM_STATUS[claim.status];
    return (
      <View style={st.card}>
        <View style={ui.row}>
          <Text style={st.stepLabel}>Tu reclamo · {claim.reason}</Text>
          <View style={{ backgroundColor: bg, borderRadius: radius.pill, paddingHorizontal: 10, paddingVertical: 3 }}><Text style={{ color: tone, fontWeight: '800', fontSize: 12.5 }}>{label}</Text></View>
        </View>
        {!!claim.text && <Text style={{ color: colors.ink }}>“{claim.text}”</Text>}
        {claim.answer ? (
          <View style={st.reply}><Text style={{ fontWeight: '700', color: colors.brand }}>Respuesta{claim.resolution ? ` · ${claim.resolution}` : ''}</Text><Text style={{ color: colors.ink }}>{claim.answer}</Text></View>
        ) : <Text style={ui.muted}>Lo ven el comercio y Trappi. Te respondemos acá.</Text>}
      </View>
    );
  }
  if (!open) {
    return <Button title="¿Tuviste un problema con tu pedido?" variant="ghost" onPress={() => setOpen(true)} style={{ marginTop: 14 }} />;
  }
  const takePhoto = async () => {
    if (!permission?.granted && !(await requestPermission()).granted) { setError('Para sacar la foto, permití el uso de la cámara.'); return; }
    setCamera(true);
  };
  const shoot = async () => {
    const pic = await cam.current?.takePictureAsync({ quality: 0.5 });
    if (pic?.uri) setPhoto(pic.uri);
    setCamera(false);
  };
  const send = async () => {
    setSending(true); setError(null);
    try { await api.claim(orderId, token, reason, text.trim(), photo); onDone(); }
    catch (e) { setError(e instanceof Error ? e.message : 'No pudimos enviar el reclamo.'); }
    finally { setSending(false); }
  };
  return (
    <View style={st.card}>
      <Text style={st.stepLabel}>¿Qué pasó con tu pedido?</Text>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginVertical: 8 }}>
        {claim.reasons.map(r => (
          <Pressable key={r.key} onPress={() => setReason(r.key)} style={[st.reason, reason === r.key && st.reasonOn]} accessibilityRole="radio" accessibilityState={{ selected: reason === r.key }}>
            <Text style={[{ color: colors.ink, fontWeight: '700' }, reason === r.key && { color: '#fff' }]}>{r.label}</Text>
          </Pressable>
        ))}
      </View>
      <TextInput value={text} onChangeText={setText} placeholder="Contanos en pocas palabras (por ejemplo: faltaron las papas)" placeholderTextColor={colors.muted} multiline maxLength={1000} style={st.input} />
      {photo ? (
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 10 }}>
          <Image source={{ uri: photo }} style={{ width: 72, height: 72, borderRadius: radius.sm }} accessibilityLabel="Foto del reclamo" />
          <Pressable onPress={() => setPhoto(null)} hitSlop={8}><Text style={{ color: colors.bad, fontWeight: '700' }}>Sacar la foto</Text></Pressable>
        </View>
      ) : <Button title="📷 Agregar una foto (opcional)" variant="ghost" onPress={takePhoto} style={{ marginBottom: 10 }} />}
      {error && <Text style={{ color: colors.bad, marginBottom: 8 }}>{error}</Text>}
      <Button title="Enviar reclamo" disabled={!reason} loading={sending} onPress={send} />
      <Text style={[ui.muted, { fontSize: 12.5, marginTop: 6 }]}>Lo ven el comercio y Trappi. Podés reclamar hasta 48 h después de recibirlo.</Text>
      <Modal visible={camera} animationType="slide" onRequestClose={() => setCamera(false)}>
        <View style={{ flex: 1, backgroundColor: '#000' }}>
          <CameraView ref={cam} style={{ flex: 1 }} facing="back" />
          <View style={st.camBar}>
            <Pressable onPress={() => setCamera(false)} hitSlop={10} accessibilityLabel="Cancelar"><Text style={{ color: '#fff', fontWeight: '700', fontSize: 16 }}>Cancelar</Text></Pressable>
            <Pressable onPress={shoot} style={st.shutter} accessibilityLabel="Sacar foto" />
            <View style={{ width: 70 }} />
          </View>
        </View>
      </Modal>
    </View>
  );
}

const TAGS = ['😋 Muy rico', '🔥 Llegó caliente', '📦 Bien empaquetado', '⚡ Rápido', '🙌 Buena atención'];

function ReviewForm({ orderId, token, store, onDone }: { orderId: number; token: string; store: string; onDone: () => void }) {
  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState('');
  const [tags, setTags] = useState<string[]>([]);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const send = async () => {
    setSending(true); setError(null);
    try { await api.review(orderId, token, rating, [tags.join(' · '), comment.trim()].filter(Boolean).join('\n')); onDone(); }
    catch (e) { setError(e instanceof Error ? e.message : 'No pudimos guardar tu opinión.'); }
    finally { setSending(false); }
  };
  return (
    <View style={st.card}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
        <View style={st.revLogo}><Ill e="🛍️" size={30} /></View>
        <View style={{ flex: 1 }}>
          <Text style={[st.stepLabel, { fontSize: 17 }]}>¿Qué tal {store}?</Text>
          <Text style={ui.muted}>Tu opinión ayuda a otros vecinos</Text>
        </View>
      </View>
      <View style={{ flexDirection: 'row', gap: 8, marginVertical: 10, justifyContent: 'center' }}>
        {[1, 2, 3, 4, 5].map(n => (
          <Pressable key={n} onPress={() => setRating(n)} hitSlop={6} accessibilityRole="button" accessibilityLabel={`${n} estrellas`}>
            <Text style={{ fontSize: 40, color: n <= rating ? colors.star : '#E5E2EC' }}>★</Text>
          </Pressable>
        ))}
      </View>
      {rating >= 4 && (
        <View style={st.tags}>
          {TAGS.map(t => {
            const on = tags.includes(t);
            return (
              <Pressable key={t} onPress={() => setTags(cur => (on ? cur.filter(x => x !== t) : [...cur, t]))} style={[st.tag, on && st.tagOn]} accessibilityRole="checkbox" accessibilityState={{ checked: on }}>
                <Text style={[st.tagText, on && { color: '#92400E' }]}>{t}</Text>
              </Pressable>
            );
          })}
        </View>
      )}
      <TextInput value={comment} onChangeText={setComment} placeholder="Contanos tu experiencia (opcional)" placeholderTextColor={colors.muted} multiline maxLength={2000}
        style={st.input} />
      {error && <Text style={{ color: colors.bad, marginBottom: 8 }}>{error}</Text>}
      <Button title="Enviar opinión" disabled={!rating} loading={sending} onPress={send} />
    </View>
  );
}

const st = StyleSheet.create({
  eta: { backgroundColor: colors.brand, borderRadius: radius.pill, paddingHorizontal: 12, paddingVertical: 6 },
  etaText: { color: '#fff', fontWeight: '800' },
  hello: { alignItems: 'center', gap: 4, padding: 18, borderRadius: radius.md, backgroundColor: colors.goodSoft, marginBottom: 14 },
  helloTitle: { fontSize: 20, fontWeight: '800', color: colors.good },
  pin: { flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: '#14101F', borderRadius: 20, padding: 14, marginTop: 14 },
  pinSmall: { color: '#A9A3BC', fontWeight: '800', fontSize: 12.5 },
  pinHint: { color: '#fff', fontSize: 13, marginTop: 2, lineHeight: 18 },
  pinDigits: { flexDirection: 'row', gap: 5 },
  pinBox: { width: 36, height: 46, borderRadius: 11, backgroundColor: '#2A2440', alignItems: 'center', justifyContent: 'center' },
  pinDigit: { fontSize: 23, fontWeight: '900', color: '#FFD43B', fontVariant: ['tabular-nums'] },
  round: { width: 42, height: 42, borderRadius: 21, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center', shadowColor: '#000', shadowOpacity: 0.12, shadowRadius: 6, shadowOffset: { width: 0, height: 2 }, elevation: 3 },
  plainHead: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 16, paddingBottom: 6 },
  plainTitle: { fontSize: 22, fontWeight: '900', color: colors.ink, letterSpacing: -0.5 },
  liveTop: { position: 'absolute', left: 0, right: 0, top: 0, paddingHorizontal: 14, gap: 10 },
  etaCard: { flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: '#fff', borderRadius: 22, padding: 14,
    shadowColor: '#1E143C', shadowOpacity: 0.18, shadowRadius: 18, shadowOffset: { width: 0, height: 8 }, elevation: 6 },
  etaBig: { fontSize: 21, fontWeight: '900', color: colors.ink, letterSpacing: -0.5 },
  etaSub: { color: colors.muted, fontSize: 13 },
  liveDot: { flexDirection: 'row', alignItems: 'center', gap: 5, backgroundColor: '#E6F8EF', borderRadius: 99, paddingHorizontal: 9, paddingVertical: 5 },
  liveDotIn: { width: 7, height: 7, borderRadius: 4, backgroundColor: '#0A8F55' },
  liveText: { color: '#075E39', fontWeight: '900', fontSize: 12 },
  sheet: { backgroundColor: '#fff', borderTopLeftRadius: 28, borderTopRightRadius: 28, paddingHorizontal: 16, paddingTop: 10, minHeight: 600,
    shadowColor: '#1E143C', shadowOpacity: 0.18, shadowRadius: 20, shadowOffset: { width: 0, height: -6 }, elevation: 10 },
  grab: { width: 44, height: 5, borderRadius: 3, backgroundColor: '#E0DAEB', alignSelf: 'center', marginBottom: 14 },
  sheetSegs: { flexDirection: 'row', gap: 5 },
  sheetSeg: { flex: 1, height: 6, borderRadius: 9, backgroundColor: '#ECEAF1' },
  sheetLabels: { flexDirection: 'row', marginTop: 6 },
  sheetLabel: { flex: 1, fontSize: 11.5, color: colors.muted, fontWeight: '700', textAlign: 'center' },
  revLogo: { width: 48, height: 48, borderRadius: 14, backgroundColor: '#FFF3E2', alignItems: 'center', justifyContent: 'center' },
  hero: { backgroundColor: colors.brand, borderRadius: 24, padding: 18, overflow: 'hidden', shadowColor: colors.brand, shadowOpacity: 0.45, shadowRadius: 18, shadowOffset: { width: 0, height: 10 }, elevation: 6 },
  heroGlow: { position: 'absolute', right: -60, top: -70, width: 220, height: 220, borderRadius: 110, backgroundColor: '#9333EA', opacity: 0.55 },
  heroStore: { color: '#E9DDFF', fontWeight: '700', fontSize: 13 },
  heroTitle: { color: '#fff', fontSize: 25, fontWeight: '900', letterSpacing: -0.6, marginTop: 4 },
  heroEta: { flexDirection: 'row', alignItems: 'center', gap: 6, alignSelf: 'flex-start', backgroundColor: 'rgba(255,255,255,.18)', borderRadius: radius.pill, paddingHorizontal: 12, paddingVertical: 6, marginTop: 10 },
  heroEtaText: { color: '#fff', fontWeight: '800', fontSize: 14.5 },
  segs: { flexDirection: 'row', gap: 5, marginTop: 16 },
  seg: { flex: 1, height: 6, borderRadius: 9, backgroundColor: 'rgba(255,255,255,.25)' },
  segOn: { backgroundColor: '#fff' },
  segNow: { backgroundColor: '#FFD43B' },
  segLabel: { color: '#D9C9FF', fontSize: 11.5, fontWeight: '700' },
  heroWhere: { color: '#fff', fontSize: 13.5, marginTop: 12, opacity: 0.9 },
  courier: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  cav: { width: 52, height: 52, borderRadius: 26, alignItems: 'center', justifyContent: 'center', borderWidth: 3, borderColor: '#fff', shadowColor: '#000', shadowOpacity: 0.15, shadowRadius: 6, shadowOffset: { width: 0, height: 2 }, elevation: 2 },
  cbtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.brandSoft, alignItems: 'center', justifyContent: 'center' },
  party: { alignItems: 'center', paddingBottom: 22, paddingHorizontal: 16, borderBottomLeftRadius: 30, borderBottomRightRadius: 30, overflow: 'hidden', marginBottom: 4 },
  confetti: { position: 'absolute', width: 9, height: 14, borderRadius: 3 },
  partyTitle: { fontSize: 27, fontWeight: '900', color: colors.ink, letterSpacing: -0.6, marginTop: 6 },
  partySub: { color: '#3C3450', fontSize: 14, marginTop: 2 },
  earn: { flexDirection: 'row', alignItems: 'center', gap: 12, alignSelf: 'stretch', backgroundColor: '#fff', borderRadius: 18, padding: 12, marginTop: 14 },
  earnTitle: { fontSize: 17, fontWeight: '900', color: '#B45309' },
  tags: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, justifyContent: 'center', marginBottom: 12 },
  tag: { borderWidth: 1.5, borderColor: colors.line, borderRadius: radius.pill, paddingHorizontal: 11, paddingVertical: 6 },
  tagOn: { backgroundColor: '#FFF7E6', borderColor: '#F59E0B' },
  tagText: { fontWeight: '700', fontSize: 13, color: colors.ink },
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
  reason: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: radius.pill, borderWidth: 1.5, borderColor: colors.line, backgroundColor: '#fff' },
  reasonOn: { backgroundColor: colors.brand, borderColor: colors.brand },
  camBar: { position: 'absolute', left: 0, right: 0, bottom: 0, paddingBottom: 40, paddingTop: 20, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-around', backgroundColor: 'rgba(0,0,0,.35)' },
  shutter: { width: 74, height: 74, borderRadius: 37, backgroundColor: '#fff', borderWidth: 5, borderColor: 'rgba(255,255,255,.5)' },
});
