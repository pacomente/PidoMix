import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { usePrefs } from '@/state/prefs';
import { useSession } from '@/state/session';

type Slide = { emoji: string; chips: string[]; title: string; text: string };

/** Bienvenida para el repartidor nuevo: 4 pantallas cortas la primera vez (se vuelven a ver desde «Primeros pasos»). */
export default function Bienvenida() {
  const insets = useSafeAreaInsets();
  const { set } = usePrefs();
  const { state } = useSession();
  const [i, setI] = useState(0);
  const own = state?.courier.fleet === 'local';
  const SLIDES: Slide[] = [
    { emoji: '🛵', chips: ['📍 Cerca tuyo', '🔔 Te suena'], title: 'Así funciona\nTrappi Repartidor',
      text: own ? `Te conectás y te llegan los pedidos de ${state?.courier.store || 'tu local'} para llevar. Dejá la app abierta: suena y vibra con cada pedido.`
        : 'Te conectás y te llegan pedidos de los locales de tu ciudad. Dejá la app abierta: suena y vibra con cada pedido.' },
    { emoji: '💸', chips: ['$ 2.400', '3,1 km'], title: 'Ves cuánto ganás\nantes de aceptar',
      text: 'Cada pedido te muestra la ganancia, los kilómetros y si cobrás en efectivo. Tenés unos segundos para aceptarlo o rechazarlo: rechazar no te penaliza.' },
    { emoji: '🔐', chips: ['PIN 4821', '✅ Entregado'], title: 'Retirás, llevás\ny entregás con el PIN',
      text: 'En el local deslizás «Retiré». En la puerta le pedís al cliente su PIN de 4 números (lo tiene en su pedido) y deslizás «Entregar». Así nadie se queda con un pedido ajeno.' },
    { emoji: '💵', chips: ['Ganancias', 'Caja'], title: 'Tus ganancias y\nel efectivo, claros',
      text: own ? 'En Ganancias ves lo que hiciste por día y por semana. El efectivo que cobrás lo rendís con tu local, como siempre.'
        : 'En Ganancias ves lo que hiciste por día y por semana. En Mi caja ves el efectivo que cobraste y cuánto tenés que rendir.' },
  ];
  const s = SLIDES[i];
  const last = i === SLIDES.length - 1;
  const finish = () => { set({ welcomeSeen: true }); router.replace('/primeros-pasos'); };

  return (
    <View style={{ flex: 1, backgroundColor: '#3B1782', paddingTop: insets.top + 12, paddingBottom: insets.bottom + 16, paddingHorizontal: 24 }}>
      <View style={{ position: 'absolute', left: 0, right: 0, bottom: 0, height: '45%', backgroundColor: '#111016', opacity: 0.6 }} pointerEvents="none" />
      <Pressable onPress={finish} style={{ alignSelf: 'flex-end', padding: 8 }} accessibilityRole="button" accessibilityLabel="Saltar la bienvenida">
        <Text style={{ color: '#D9D0F2', fontWeight: '800', fontSize: 15 }}>Saltar</Text>
      </Pressable>
      <View style={{ alignItems: 'center', marginTop: 24 }}>
        <View style={{ width: 230, height: 230, borderRadius: 115, backgroundColor: 'rgba(255,255,255,.08)', alignItems: 'center', justifyContent: 'center' }}>
          <Text style={{ fontSize: 100 }} accessibilityElementsHidden>{s.emoji}</Text>
        </View>
        <View style={{ flexDirection: 'row', gap: 8, marginTop: -18 }}>
          {s.chips.map(ch => <View key={ch} style={{ backgroundColor: '#fff', borderRadius: 14, paddingHorizontal: 12, paddingVertical: 7 }}><Text style={{ color: '#14101F', fontWeight: '900' }}>{ch}</Text></View>)}
        </View>
      </View>
      <Text style={{ color: '#fff', fontSize: 30, fontWeight: '900', lineHeight: 35, marginTop: 34 }} accessibilityRole="header">{s.title}</Text>
      <Text style={{ color: '#E4DCF7', fontSize: 16.5, lineHeight: 24, marginTop: 12 }}>{s.text}</Text>
      <View style={{ flex: 1 }} />
      <View style={{ flexDirection: 'row', gap: 6, marginBottom: 18 }} accessibilityLabel={`Pantalla ${i + 1} de ${SLIDES.length}`}>
        {SLIDES.map((_, k) => <View key={k} style={{ height: 7, width: k === i ? 26 : 7, borderRadius: 4, backgroundColor: k === i ? '#2EE59D' : 'rgba(255,255,255,.3)' }} />)}
      </View>
      <View style={{ flexDirection: 'row', gap: 10 }}>
        {i > 0 && (
          <Pressable onPress={() => setI(i - 1)} accessibilityRole="button" accessibilityLabel="Atrás"
            style={{ flex: 1, height: 58, borderRadius: 29, borderWidth: 2, borderColor: 'rgba(255,255,255,.35)', alignItems: 'center', justifyContent: 'center' }}>
            <Text style={{ color: '#fff', fontWeight: '800', fontSize: 16 }}>Atrás</Text>
          </Pressable>
        )}
        <View style={{ flex: 2 }}>
          <Pressable onPress={() => (last ? finish() : setI(i + 1))} accessibilityRole="button" accessibilityLabel={last ? 'Empezar' : 'Siguiente'}
            style={({ pressed }) => [{ height: 58, borderRadius: 29, backgroundColor: '#2EE59D', alignItems: 'center', justifyContent: 'center' }, pressed && { opacity: 0.85 }]}>
            <Text style={{ color: '#062B1C', fontWeight: '900', fontSize: 18 }}>{last ? '¡Empezar!' : 'Siguiente'}</Text>
          </Pressable>
        </View>
      </View>
    </View>
  );
}
