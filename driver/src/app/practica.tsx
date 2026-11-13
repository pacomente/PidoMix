import Ionicons from '@expo/vector-icons/Ionicons';
import { router } from 'expo-router';
import { useMemo, useState } from 'react';
import { Pressable, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { DriverMap, type MapTarget } from '@/components/driver-map';
import { OfferCard } from '@/components/offer-card';
import { TripSheet } from '@/components/trip-sheet';
import { money } from '@/lib/format';
import { playConfirm } from '@/lib/sounds';
import { radius, themed } from '@/lib/theme';
import type { Offer, Trip } from '@/lib/types';
import { useColors, usePrefs } from '@/state/prefs';
import { useSession } from '@/state/session';

// Viaje de práctica: un pedido de mentira que no pasa por el servidor (no toca pedidos, ganancias ni la caja).
const PIN = '4821';
type Phase = 'offer' | 'pickup' | 'dropoff' | 'done';

function places(base: { lat: number; lng: number }) {
  return { store: { lat: base.lat + 0.004, lng: base.lng + 0.005 }, home: { lat: base.lat - 0.008, lng: base.lng + 0.012 } };
}

export default function Practica() {
  const insets = useSafeAreaInsets();
  const c = useColors(), st = useSt(c);
  const { set } = usePrefs();
  const { position, state } = useSession();
  const [phase, setPhase] = useState<Phase>('offer');
  const [nudge, setNudge] = useState<string | null>(null);
  const [arrivedP, setArrivedP] = useState(false);
  const [sheetH, setSheetH] = useState(300);
  const [base] = useState(() => (position ? { lat: position.lat, lng: position.lng } : { lat: -38.7183, lng: -62.2663 }));
  const p = places(base);

  const offer: Offer = useMemo(() => ({
    id: -1, order_id: 1001, expires_in: 90, seconds: 90, earnings: 2400, store: { name: 'Local de práctica', address: 'A 900 m de donde estás', ...p.store },
    dropoff: { address: 'Cliente de práctica · Barrio Centro', ...p.home }, to_store_km: 0.9, trip_km: 2.2, items: 3, own_store: false,
    paid_online: false, collect: 14900, payout: { total: 2400, lines: [{ label: 'Base', amount: 1500 }, { label: 'Por km', amount: 900 }] },
  }), []); // eslint-disable-line react-hooks/exhaustive-deps

  const trip: Trip = {
    order_id: 1001, status: phase === 'dropoff' ? 'EN_CAMINO' : 'LISTO', stage: phase === 'dropoff' ? 'dropoff' : 'pickup', ready: true, earnings: 2400, total: 14900,
    collect: 14900, payment: { method: 'efectivo', label: 'Efectivo', paid: false, cash_with: 20000, change: 5100, transfer_pending: false },
    pin_required: true, pickup_code_required: false, pay_store: 0, failed: null, fail_reasons: [{ code: 'practica', label: 'El cliente no atiende' }],
    payout: offer.payout, route_km: 2.2, zone: null,
    store: { name: 'Local de práctica', address: 'A 900 m de donde estás', phone: null, whatsapp: null, ...p.store },
    customer: { name: 'Ana Práctica', phone: null, whatsapp: null, address: 'Barrio Centro', reference: 'Timbre 2B', ...p.home },
    items: [{ quantity: 2, name: 'Hamburguesa clásica', modifiers_text: null }, { quantity: 1, name: 'Papas grandes', modifiers_text: null }],
    notes: 'Tocá el timbre 2B', trip_km: 2.2, safety: phase === 'dropoff' ? { arrived: arrivedP, wait_left: null, wait_minutes: 10 } : null,
  };

  const targets = useMemo<MapTarget[]>(() => (phase === 'dropoff'
    ? [{ kind: 'customer', point: p.home, label: 'Ana' }]
    : [{ kind: 'store', point: p.store, label: 'Local de práctica' }, { kind: 'customer', point: p.home, label: 'Entrega' }]), [phase]); // eslint-disable-line react-hooks/exhaustive-deps

  const tips: Record<Phase, { step: string; title: string; text: string }> = {
    offer: { step: 'Paso 1 de 3', title: 'Aceptar el pedido', text: 'Arriba ves cuánto ganás (tocalo para ver el detalle), los km y si cobrás en efectivo. Si te sirve, tocá «Aceptar».' },
    pickup: { step: 'Paso 2 de 3', title: 'Retirar en el local', text: 'Andá al local con «Navegar». Cuando te dan el pedido, deslizá el botón «Retiré el pedido» hasta el final.' },
    dropoff: { step: 'Paso 3 de 3', title: 'Cobrar y entregar', text: `Cobrás ${money(14900)}: te paga con ${money(20000)}, le das ${money(5100)} de vuelto. Al llegar tocá «Llegué» y pedile el PIN (en la práctica es ${PIN}).` },
    done: { step: '', title: '', text: '' },
  };
  const tip = tips[phase];
  const exit = () => router.back();

  if (phase === 'done') {
    return (
      <View style={[st.doneWrap, { paddingTop: insets.top + 40, paddingBottom: insets.bottom + 20 }]}>
        <Text style={{ fontSize: 90, textAlign: 'center' }}>{state?.courier.style?.avatar || '🎉'}</Text>
        <Text style={st.doneTitle}>¡Lo hiciste perfecto!</Text>
        <Text style={st.doneText}>Así es un viaje de punta a punta: aceptás, retirás, cobrás y entregás con el PIN. Los pedidos de verdad son iguales.</Text>
        <View style={st.doneMoney}><Text style={st.doneMoneyTxt}>+{money(2400)}</Text><Text style={st.doneMoneySub}>es lo que ganarías en un viaje así (esta vez no cuenta)</Text></View>
        <View style={{ flex: 1 }} />
        <Pressable style={st.doneBtn} onPress={() => router.replace('/primeros-pasos')} accessibilityRole="button"><Text style={st.doneBtnTxt}>Volver a primeros pasos</Text></Pressable>
      </View>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: c.mapBg }}>
      <DriverMap me={base} meStyle={state?.courier.style ?? null} targets={targets} bottomInset={sheetH} />
      <View style={[st.banner, { top: insets.top + 8 }]}>
        <Text style={st.bannerTxt}>🎓 MODO PRÁCTICA · no es un pedido real</Text>
        <Pressable onPress={exit} hitSlop={10} accessibilityRole="button" accessibilityLabel="Salir de la práctica"><Ionicons name="close" size={22} color="#14101F" /></Pressable>
      </View>
      <View style={[st.tip, { top: insets.top + 56 }]} accessibilityLiveRegion="polite">
        <Text style={st.tipStep}>{tip.step}</Text>
        <Text style={st.tipTitle}>{tip.title}</Text>
        <Text style={st.tipText}>{nudge || tip.text}</Text>
      </View>
      <View style={[st.bottom, { paddingBottom: insets.bottom + (phase === 'offer' ? 12 : 0) }]} onLayout={e => setSheetH(e.nativeEvent.layout.height)}>
        {phase === 'offer' ? (
          <View style={{ paddingHorizontal: 12 }}>
            <OfferCard offer={offer} busy={false} onAccept={() => { playConfirm(); setNudge(null); setPhase('pickup'); }}
              onReject={() => setNudge('Rechazar no te penaliza: el pedido pasa a otro repartidor. En la práctica, aceptalo para seguir 😉')} />
          </View>
        ) : (
          <TripSheet trip={trip} busy={false} eta={{ minutes: phase === 'pickup' ? 3 : 7, km: phase === 'pickup' ? 0.9 : 2.2 }}
            onPickup={async () => { playConfirm(); setNudge(null); setPhase('dropoff'); return null; }}
            onDeliver={async pin => {
              if (pin !== PIN) return `Ese no es el PIN. En la práctica es ${PIN}.`;
              playConfirm(); set({ practiceDone: true }); setPhase('done'); return null;
            }}
            onArrived={async () => { setArrivedP(true); setNudge('¡Bien! Al tocar «Llegué» le avisamos al cliente que estás en la puerta. Ahora pedile el PIN.'); return null; }}
            onRelease={() => setNudge('Si de verdad no podés llevarlo, el pedido se le ofrece a otro repartidor. En la práctica, seguí 😉')}
            onFail={() => setNudge('Si el cliente no atiende, avisás desde acá y el local te dice qué hacer. En la práctica, seguí 😉')} />
        )}
      </View>
    </View>
  );
}

const useSt = themed(c => ({
  banner: { position: 'absolute', left: 12, right: 12, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', backgroundColor: c.warn, borderRadius: radius.md, paddingHorizontal: 14, paddingVertical: 9 },
  bannerTxt: { color: '#14101F', fontWeight: '900', fontSize: 14 },
  tip: { position: 'absolute', left: 12, right: 12, backgroundColor: c.card, borderRadius: radius.md, padding: 14, borderWidth: 2, borderColor: c.go, shadowColor: '#000', shadowOpacity: 0.3, shadowRadius: 10, elevation: 8 },
  tipStep: { color: c.go, fontWeight: '900', fontSize: 12.5, textTransform: 'uppercase', letterSpacing: 0.5 },
  tipTitle: { color: c.ink, fontWeight: '900', fontSize: 18, marginTop: 2 },
  tipText: { color: c.muted, fontSize: 14.5, lineHeight: 20, marginTop: 4 },
  bottom: { position: 'absolute', left: 0, right: 0, bottom: 0 },
  doneWrap: { flex: 1, backgroundColor: c.bg, paddingHorizontal: 24 },
  doneTitle: { color: c.ink, fontSize: 30, fontWeight: '900', textAlign: 'center', marginTop: 16 },
  doneText: { color: c.muted, fontSize: 16, lineHeight: 23, textAlign: 'center', marginTop: 10 },
  doneMoney: { backgroundColor: c.paidBg, borderRadius: radius.lg, padding: 16, marginTop: 24, alignItems: 'center' },
  doneMoneyTxt: { color: c.moneyText, fontSize: 34, fontWeight: '900' },
  doneMoneySub: { color: c.muted, fontSize: 13, textAlign: 'center' },
  doneBtn: { backgroundColor: c.go, borderRadius: 99, height: 58, alignItems: 'center', justifyContent: 'center' },
  doneBtnTxt: { color: '#fff', fontWeight: '900', fontSize: 17 },
}));
