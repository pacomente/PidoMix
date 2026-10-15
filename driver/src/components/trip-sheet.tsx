import Ionicons from '@expo/vector-icons/Ionicons';
import { useState } from 'react';
import { Linking, Pressable, ScrollView, Text, TextInput, View } from 'react-native';

import { Button, SlideButton } from '@/components/ui';
import { km, money } from '@/lib/format';
import { openNav } from '@/lib/nav';
import { radius, themed, type Palette } from '@/lib/theme';
import type { Trip } from '@/lib/types';
import { useColors, usePrefs } from '@/state/prefs';

type St = ReturnType<typeof useSt>;

function Action({ icon, label, onPress, st, c }: { icon: React.ComponentProps<typeof Ionicons>['name']; label: string; onPress: () => void; st: St; c: Palette }) {
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [st.action, pressed && { opacity: 0.7 }]} accessibilityRole="button" accessibilityLabel={label}>
      <Ionicons name={icon} size={20} color={c.ink} />
      <Text style={st.actionText}>{label}</Text>
    </Pressable>
  );
}

/** Los dos pasos del viaje: retirar en el local y entregar al cliente. */
function Steps({ pickup, st }: { pickup: boolean; st: St }) {
  return (
    <View style={st.steps}>
      <View style={{ flex: 1 }}>
        <View style={[st.stepBar, st.stepOn]} />
        <Text style={[st.stepTxt, pickup && st.stepTxtOn]}>{pickup ? '1 · Retiro en el local' : '✓ Retirado'}</Text>
      </View>
      <View style={{ flex: 1 }}>
        <View style={[st.stepBar, !pickup && st.stepOn]} />
        <Text style={[st.stepTxt, !pickup && st.stepTxtOn]}>2 · Entrega al cliente</Text>
      </View>
    </View>
  );
}

/** Qué hacer con la plata: lo más importante al llegar a la puerta. */
function PaymentBox({ trip, st }: { trip: Trip; st: St }) {
  const p = trip.payment;
  if (p.paid) {
    return (
      <View style={[st.collect, st.paid]}>
        <Text style={[st.collectLabel, st.paidLabel]}>✓ YA PAGADO · {p.label.toUpperCase()}</Text>
        <Text style={st.collectValue}>No cobres nada</Text>
      </View>
    );
  }
  return (
    <View style={[st.collect, st.pending]}>
      <Text style={[st.collectLabel, st.pendingLabel]}>{p.transfer_pending ? '⚠ TRANSFERENCIA SIN CONFIRMAR' : '💵 COBRAR EN EFECTIVO'}</Text>
      <Text style={st.collectValue}>{money(trip.collect)}</Text>
      {p.transfer_pending
        ? <Text style={st.collectHint}>El cliente eligió transferencia pero el local todavía no la confirmó. Cobrale o pedile al local que la confirme (se actualiza solo).</Text>
        : p.cash_with ? <Text style={st.collectHint}>Paga con {money(p.cash_with)}{p.change ? ` · llevá ${money(p.change)} de vuelto` : ''}</Text> : null}
    </View>
  );
}

/** Al retirar: la plata que le pagás al local (si es en efectivo) y lo que vas a cobrar después. */
function PickupBox({ trip, st }: { trip: Trip; st: St }) {
  const payStore = trip.pay_store || 0;
  if (payStore > 0) {
    return (
      <View style={[st.collect, st.pending]}>
        <Text style={[st.collectLabel, st.pendingLabel]}>💵 PAGALE AL LOCAL EN EFECTIVO</Text>
        <Text style={st.collectValue}>{money(payStore)}</Text>
        <Text style={st.collectHint}>Cuando le pagues, el local te dicta el código de retiro. Después, al entregar, le cobrás al cliente {money(trip.collect)} (productos + envío).</Text>
      </View>
    );
  }
  return (
    <View style={[st.collect, trip.payment.paid ? st.paid : st.neutral]}>
      <Text style={st.collectHint}>{trip.payment.paid ? '✓ Ya está pagado: al cliente no le cobrás nada.' : `Al entregar vas a cobrar ${money(trip.collect)}${trip.payment.transfer_pending ? ' (salvo que el local confirme la transferencia)' : ' en efectivo'}.`}</Text>
    </View>
  );
}

/** Teclado para un código de 4 números: el de retiro (lo dicta el local) o el PIN de entrega (lo ve el cliente). */
function CodeEntry({ title, hint, label, button, variant, busy, onSend, onCancel, st, c }: {
  title: string; hint: string; label: string; button: string; variant: 'go' | 'money'; busy: boolean;
  onSend: (code: string) => Promise<string | null>; onCancel: () => void; st: St; c: Palette;
}) {
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const send = async () => {
    setError(null);
    const err = await onSend(code);
    if (err) { setError(err); setCode(''); }
  };
  return (
    <View style={st.pinBox}>
      <Text style={st.pinTitle}>{title}</Text>
      <Text style={st.collectHint}>{hint}</Text>
      <TextInput value={code} onChangeText={v => { setCode(v.replace(/\D/g, '').slice(0, 4)); setError(null); }} keyboardType="number-pad" maxLength={4} autoFocus
        placeholder="••••" placeholderTextColor={c.muted} style={[st.pinInput, !!error && { borderColor: c.danger }]} accessibilityLabel={label} onSubmitEditing={() => code.length === 4 && send()} />
      {!!error && <Text style={st.pinError}>{error}</Text>}
      <Button big variant={variant} title={button} disabled={code.length !== 4} loading={busy} onPress={send} />
      <Pressable onPress={onCancel} style={st.release}><Text style={[st.releaseText, { color: c.muted }]}>Volver</Text></Pressable>
    </View>
  );
}

/** No pudo entregar: elegir el motivo. El pedido sigue en sus manos hasta que el local lo cancela. */
function FailPicker({ trip, busy, onFail, onCancel, st, c }: { trip: Trip; busy: boolean; onFail: (reason: string) => void; onCancel: () => void; st: St; c: Palette }) {
  return (
    <View style={st.pinBox}>
      <Text style={st.pinTitle}>¿Qué pasó?</Text>
      <Text style={st.collectHint}>Antes, llamá o escribile al cliente. Le avisamos al local para que lo resuelva.</Text>
      {(trip.fail_reasons || []).map(r => (
        <Button key={r.code} title={r.label} variant="light" loading={busy} onPress={() => onFail(r.code)} />
      ))}
      <Pressable onPress={onCancel} style={st.release}><Text style={[st.releaseText, { color: c.muted }]}>Volver</Text></Pressable>
    </View>
  );
}

/** Ya reportó que no pudo entregar: volver al local con el pedido. */
function FailedBox({ trip, st }: { trip: Trip; st: St }) {
  return (
    <View style={[st.collect, st.failed]}>
      <Text style={[st.collectLabel, st.failedLabel]}>⚠ NO SE PUDO ENTREGAR · {trip.failed}</Text>
      <Text style={st.failedText}>Volvé al local con el pedido{trip.pay_store ? ` y pedile que te devuelva ${money(trip.pay_store)}` : ''}.</Text>
      <Text style={st.collectHint}>El local lo cancela cuando se lo devolvés. Si el cliente aparece, lo podés entregar igual.</Text>
    </View>
  );
}

/** Panel inferior del viaje en curso: primero retirar en el local, después entregar al cliente.
 * eta: cuánto falta según la ruta por calle (si la hay). */
export function TripSheet({ trip, busy, eta, onPickup, onDeliver, onRelease, onFail }: {
  trip: Trip; busy: boolean; eta?: { minutes: number; km: number } | null;
  onPickup: (code: string) => Promise<string | null>; onDeliver: (pin: string) => Promise<string | null>; onRelease: () => void; onFail: (reason: string) => void;
}) {
  const c = useColors(), st = useSt(c);
  const { navApp } = usePrefs();
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<'main' | 'code' | 'pin' | 'fail' | 'release'>('main');
  const count = trip.items.reduce((n, i) => n + i.quantity, 0);
  const pickup = trip.stage === 'pickup';
  const place = pickup ? trip.store : trip.customer;
  const contact = pickup ? trip.store.whatsapp : trip.customer.whatsapp;
  const phone = pickup ? trip.store.phone : trip.customer.phone;
  const main = mode === 'main';

  return (
    <View style={st.sheet}>
      <View style={st.grab} />
      <Steps pickup={pickup} st={st} />
      <View style={st.row}>
        <Text style={st.order}>Pedido #{trip.order_id}{eta ? ` · ${Math.max(1, Math.round(eta.minutes))} min · ${km(eta.km)}` : ''}</Text>
        <Text style={st.earn}>{money(trip.earnings)}</Text>
      </View>
      <Text style={st.title} numberOfLines={1}>{pickup ? trip.store.name : trip.customer.name}</Text>
      <Text style={st.address} numberOfLines={2}>{place.address || 'Sin dirección'}{!pickup && trip.customer.reference ? ` · ${trip.customer.reference}` : ''}</Text>
      {pickup && <Text style={[st.ready, trip.ready && { color: c.moneyText }]}>{trip.ready ? '✓ El pedido está listo para retirar' : '⏳ El local lo está preparando'}</Text>}
      {!pickup && main && (trip.failed ? <FailedBox trip={trip} st={st} /> : <PaymentBox trip={trip} st={st} />)}
      {pickup && main && <PickupBox trip={trip} st={st} />}

      {main && (
        <View style={st.actions}>
          <Pressable onPress={() => openNav(place, navApp)} style={({ pressed }) => [st.navBtn, pressed && { opacity: 0.85 }]} accessibilityRole="button" accessibilityLabel="Navegar">
            <Ionicons name="navigate" size={20} color="#fff" />
            <Text style={st.navBtnText}>Navegar</Text>
          </Pressable>
          {!!contact && <Action icon="logo-whatsapp" label="WhatsApp" onPress={() => Linking.openURL(contact)} st={st} c={c} />}
          {!!phone && <Action icon="call-outline" label="Llamar" onPress={() => Linking.openURL(`tel:${phone}`)} st={st} c={c} />}
        </View>
      )}

      {main && (
        <Pressable onPress={() => setOpen(o => !o)} style={st.detailsToggle} accessibilityRole="button" accessibilityLabel={open ? 'Ocultar productos' : 'Ver productos'}>
          <Text style={st.detailsText}>{count} {count === 1 ? 'producto' : 'productos'}{trip.trip_km ? ` · ${km(trip.trip_km)} de viaje` : ''}{trip.notes ? ' · 💬 tiene nota' : ''}</Text>
          <Ionicons name={open ? 'chevron-down' : 'chevron-up'} size={18} color={c.muted} />
        </Pressable>
      )}
      {open && main && (
        <ScrollView style={{ maxHeight: 160 }}>
          {trip.items.map((it, i) => <Text key={i} style={st.item}>{it.quantity}× {it.name}{it.modifiers_text ? ` (+ ${it.modifiers_text})` : ''}</Text>)}
          {!!trip.notes && <Text style={st.notes}>💬 {trip.notes}</Text>}
        </ScrollView>
      )}

      {mode === 'code' ? (
        <CodeEntry st={st} c={c} variant="go" busy={busy} label="Código de retiro" title={`Pedile el código de retiro a ${trip.store.name}`}
          hint={trip.pay_store ? `Pagale ${money(trip.pay_store)} al local y pedile el código: lo tiene en la comanda.` : 'Lo tiene en la comanda. Sin el código no se puede marcar retirado.'}
          button={trip.pay_store ? `Pagué ${money(trip.pay_store)} y retiré` : 'Confirmar retiro'}
          onSend={async code => { const err = await onPickup(code); if (!err) setMode('main'); return err; }} onCancel={() => setMode('main')} />
      ) : mode === 'pin' ? (
        <CodeEntry st={st} c={c} variant="money" busy={busy} label="PIN de entrega" title={`Pedile el PIN a ${trip.customer.name.split(' ')[0]}`}
          hint="Lo ve en su pedido (en la app o la web). Sin el PIN no se puede marcar entregado."
          button={trip.collect ? `Cobré ${money(trip.collect)} y entregué` : 'Confirmar entrega'} onSend={onDeliver} onCancel={() => setMode('main')} />
      ) : mode === 'fail' ? (
        <FailPicker st={st} c={c} trip={trip} busy={busy} onFail={reason => { setMode('main'); onFail(reason); }} onCancel={() => setMode('main')} />
      ) : mode === 'release' ? (
        <View style={st.pinBox}>
          <Text style={st.pinTitle}>¿No podés llevarlo?</Text>
          <Text style={st.collectHint}>El pedido se le ofrece a otro repartidor.</Text>
          <Button title="Sí, liberar el pedido" variant="danger" loading={busy} onPress={() => { setMode('main'); onRelease(); }} />
          <Pressable onPress={() => setMode('main')} style={st.release}><Text style={[st.releaseText, { color: c.muted }]}>Volver</Text></Pressable>
        </View>
      ) : pickup ? (
        <>
          {trip.pickup_code_required
            ? <Button big variant="go" icon="keypad" title="Retirar · cargar el código" loading={busy} onPress={() => setMode('code')} />
            : <SlideButton title={trip.pay_store ? `Pagué ${money(trip.pay_store)} y retiré` : 'Retiré el pedido'} loading={busy} onConfirm={() => { onPickup(''); }} />}
          <Pressable onPress={() => setMode('release')} style={st.release}><Text style={st.releaseText}>No puedo llevar este pedido</Text></Pressable>
        </>
      ) : (
        <>
          {trip.pin_required
            ? <Button big variant="money" icon="keypad" title="Entregar · pedir PIN" loading={busy} onPress={() => setMode('pin')} />
            : <SlideButton variant="money" title={trip.collect ? `Cobré ${money(trip.collect)} y entregué` : 'Entregué el pedido'} loading={busy} onConfirm={() => { onDeliver(''); }} />}
          {!trip.failed && !!trip.fail_reasons?.length && (
            <Pressable onPress={() => setMode('fail')} style={st.release}><Text style={st.releaseText}>No pude entregar</Text></Pressable>
          )}
        </>
      )}
    </View>
  );
}

const useSt = themed(c => ({
  sheet: { backgroundColor: c.card, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, padding: 18, paddingTop: 10, gap: 6, shadowColor: '#000', shadowOpacity: c.shadow, shadowRadius: 16, elevation: 12 },
  grab: { alignSelf: 'center', width: 40, height: 5, borderRadius: 3, backgroundColor: c.line, marginBottom: 6 },
  steps: { flexDirection: 'row', gap: 6, marginBottom: 6 },
  stepBar: { height: 4, borderRadius: 2, backgroundColor: c.line },
  stepOn: { backgroundColor: c.go },
  stepTxt: { fontSize: 11.5, fontWeight: '700', color: c.muted, marginTop: 4 },
  stepTxtOn: { color: c.ink },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  order: { color: c.muted, fontWeight: '700', flex: 1 },
  earn: { fontWeight: '900', fontSize: 18, color: c.moneyText },
  title: { fontSize: 24, fontWeight: '900', color: c.ink, letterSpacing: -0.4, marginTop: 2 },
  address: { fontSize: 15.5, color: c.ink, opacity: 0.85 },
  ready: { fontWeight: '700', color: c.cashText, marginTop: 2 },
  collect: { marginTop: 6, padding: 12, borderRadius: radius.sm, borderWidth: 1, gap: 2 },
  collectLabel: { fontWeight: '800' },
  collectValue: { fontSize: 28, fontWeight: '900', color: c.ink },
  collectHint: { color: c.muted, fontSize: 13 },
  paid: { backgroundColor: c.paidBg, borderColor: c.paidLine },
  paidLabel: { color: c.moneyText },
  pending: { backgroundColor: c.cashBg, borderColor: c.cashLine },
  pendingLabel: { color: c.cashText },
  neutral: { backgroundColor: c.card2, borderColor: c.line },
  failed: { backgroundColor: c.failBg, borderColor: c.failLine },
  failedLabel: { color: c.dangerText },
  failedText: { fontSize: 18, fontWeight: '800', color: c.ink },
  pinBox: { marginTop: 6, gap: 8 },
  pinTitle: { fontSize: 20, fontWeight: '900', color: c.ink },
  pinInput: { alignSelf: 'stretch', textAlign: 'center', fontSize: 40, fontWeight: '900', letterSpacing: 18, paddingVertical: 10, borderRadius: radius.sm, borderWidth: 2, borderColor: c.line, color: c.ink, backgroundColor: c.card2 },
  pinError: { color: c.dangerText, fontWeight: '700', textAlign: 'center' },
  actions: { flexDirection: 'row', gap: 8, marginVertical: 10 },
  navBtn: { flex: 1, minHeight: 50, borderRadius: radius.pill, backgroundColor: c.go, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8 },
  navBtnText: { color: '#fff', fontWeight: '900', fontSize: 17 },
  action: { minHeight: 50, paddingHorizontal: 14, borderRadius: radius.pill, backgroundColor: c.card2, flexDirection: 'row', alignItems: 'center', gap: 6 },
  actionText: { fontSize: 14, fontWeight: '800', color: c.ink },
  detailsToggle: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: 8, borderTopWidth: 1, borderTopColor: c.line },
  detailsText: { color: c.muted, fontWeight: '600' },
  item: { fontSize: 15, color: c.ink, paddingVertical: 2 },
  notes: { marginTop: 6, padding: 10, borderRadius: 8, backgroundColor: c.cashBg, color: c.cashText, fontWeight: '700' },
  release: { alignItems: 'center', paddingVertical: 10 },
  releaseText: { color: c.dangerText, fontWeight: '700' },
}));
