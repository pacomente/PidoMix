import Ionicons from '@expo/vector-icons/Ionicons';
import * as Location from 'expo-location';
import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Linking, Pressable, ScrollView, Text, View } from 'react-native';

import { radius, themed, type Palette } from '@/lib/theme';
import { useConfig } from '@/state/config';
import { useColors, usePrefs } from '@/state/prefs';
import { useSession } from '@/state/session';

type St = ReturnType<typeof useSt>;

function Step({ n, done, title, sub, action, onPress, st, c }: {
  n: number; done: boolean; title: string; sub: string; action?: string; onPress?: () => void; st: St; c: Palette;
}) {
  return (
    <Pressable onPress={onPress} disabled={!onPress} style={({ pressed }) => [st.step, pressed && { backgroundColor: c.card2 }]}
      accessibilityRole={onPress ? 'button' : undefined} accessibilityLabel={`${title}${done ? ', listo' : ', pendiente'}`}>
      <View style={[st.badge, done ? st.badgeOk : st.badgeNo]}>
        {done ? <Ionicons name="checkmark" size={18} color="#062B1C" /> : <Text style={st.badgeTxt}>{n}</Text>}
      </View>
      <View style={{ flex: 1 }}>
        <Text style={st.stepTitle}>{title}</Text>
        <Text style={st.stepSub}>{sub}</Text>
      </View>
      {!!action && <View style={[st.go, done && st.goDone]}><Text style={[st.goTxt, done && { color: c.ink }]}>{action}</Text></View>}
    </Pressable>
  );
}

/** Primeros pasos del repartidor nuevo: una lista corta para salir a la calle sin dudas (se guarda en el teléfono). */
export default function PrimerosPasos() {
  const c = useColors(), st = useSt(c);
  const { practiceDone, cashHelpSeen, set } = usePrefs();
  const { state } = useSession();
  const { support_whatsapp: support } = useConfig();
  const [gps, setGps] = useState(false);
  const [help, setHelp] = useState(false);
  const cour = state?.courier;
  const own = cour?.fleet === 'local';
  useFocusEffect(useCallback(() => { Location.getForegroundPermissionsAsync().then(p => setGps(p.granted)).catch(() => {}); }, []));

  const askGps = async () => { const p = await Location.requestForegroundPermissionsAsync().catch(() => null); setGps(!!p?.granted); };
  const steps = [true, gps, !!cour?.style?.avatar, practiceDone, cashHelpSeen];
  const done = steps.filter(Boolean).length;
  const first = (cour?.name || '').split(' ')[0];

  return (
    <ScrollView style={{ backgroundColor: c.bg }} contentContainerStyle={{ padding: 16, paddingBottom: 40, gap: 12 }}>
      <Text style={st.hello}>¡Hola{first ? `, ${first}` : ''}! 👋</Text>
      <Text style={st.muted}>Completá esto y salís a la calle sin dudas.</Text>
      <View style={st.progRow}>
        <View style={st.ring}><Text style={st.ringTxt}>{done}/{steps.length}</Text></View>
        <View style={{ flex: 1 }}>
          <Text style={st.progTitle}>{done === steps.length ? '¡Listo! Ya podés salir a repartir' : done >= 3 ? 'Ya casi estás' : 'Vamos de a poco'}</Text>
          <View style={st.bar}><View style={[st.barFill, { width: `${(done / steps.length) * 100}%` }]} /></View>
        </View>
      </View>

      <View style={st.card}>
        <Step st={st} c={c} n={1} done title="Tus datos y tu vehículo" sub={`Te dio de alta ${own ? cour?.store || 'tu local' : 'Trappi'}${cour?.vehicle ? ` · ${cour.vehicle}` : ''}`} />
        <Step st={st} c={c} n={2} done={gps} title="Permiso de ubicación" sub="Para que te lleguen pedidos cerca y el cliente te vea llegar" action={gps ? undefined : 'Activar'} onPress={gps ? undefined : askGps} />
        <Step st={st} c={c} n={3} done={!!cour?.style?.avatar} title="Elegí tu estilo" sub={cour?.style?.avatar ? `Te ves como ${cour.style.avatar} en el mapa` : 'Un personaje y un color para el mapa'} action={cour?.style?.avatar ? 'Cambiar' : 'Elegir'} onPress={() => router.push('/estilo')} />
        <Step st={st} c={c} n={4} done={practiceDone} title="Viaje de práctica" sub="Un pedido de mentira, de punta a punta · 2 min" action={practiceDone ? 'Repetir' : 'Empezar'} onPress={() => router.push('/practica')} />
        <Step st={st} c={c} n={5} done={cashHelpSeen} title={own ? 'Cómo cobrás' : 'Cómo cobrás y rendís'} sub="El efectivo, los pagos online y tus ganancias" action={help ? 'Cerrar' : 'Ver'}
          onPress={() => { setHelp(h => !h); set({ cashHelpSeen: true }); }} />
        {help && (
          <View style={st.help}>
            <Text style={st.helpTxt}>💳 <Text style={st.b}>Pagado online:</Text> no cobrás nada, solo entregás con el PIN.</Text>
            <Text style={st.helpTxt}>💵 <Text style={st.b}>Efectivo:</Text> la app te dice cuánto cobrar y si el cliente necesita vuelto.</Text>
            {own
              ? <Text style={st.helpTxt}>🏪 El efectivo y tus envíos los arreglás con {cour?.store || 'tu local'}, como siempre. En Ganancias ves cuántos viajes hiciste.</Text>
              : <Text style={st.helpTxt}>🧾 El efectivo que cobrás lo rendís a Trappi. En <Text style={st.b}>Mi caja</Text> ves cuánto tenés sin rendir y tu límite: si lo pasás, no te llegan pedidos en efectivo hasta que rindas.</Text>}
            <Text style={st.helpTxt}>📈 En <Text style={st.b}>Ganancias</Text> ves lo que ganaste por día y por semana, con el detalle de cada viaje.</Text>
          </View>
        )}
      </View>

      <Pressable onPress={() => router.push('/bienvenida')} style={st.card2} accessibilityRole="button" accessibilityLabel="Ver de nuevo cómo funciona">
        <Text style={{ fontSize: 24 }}>📖</Text>
        <View style={{ flex: 1 }}><Text style={st.stepTitle}>Ver de nuevo cómo funciona</Text><Text style={st.stepSub}>Las 4 pantallas de bienvenida</Text></View>
        <Ionicons name="chevron-forward" size={18} color={c.muted} />
      </Pressable>
      {!!support && (
        <Pressable onPress={() => Linking.openURL(`https://wa.me/${support.replace(/\D/g, '')}`)} style={st.card2} accessibilityRole="button" accessibilityLabel="Escribirle a Trappi por WhatsApp">
          <Text style={{ fontSize: 24 }}>💬</Text>
          <View style={{ flex: 1 }}><Text style={st.stepTitle}>¿Dudas? Escribinos</Text><Text style={st.stepSub}>Te ayudamos por WhatsApp</Text></View>
          <Ionicons name="chevron-forward" size={18} color={c.muted} />
        </Pressable>
      )}
      <Pressable onPress={() => router.replace('/')} style={[st.ready, done < steps.length && st.later]} accessibilityRole="button">
        <Text style={[st.readyTxt, done < steps.length && { color: c.ink }]}>{done === steps.length ? 'Ir al mapa y conectarme' : 'Lo termino después · ir al mapa'}</Text>
      </Pressable>
    </ScrollView>
  );
}

const useSt = themed(c => ({
  hello: { color: c.ink, fontSize: 26, fontWeight: '900' },
  muted: { color: c.muted, marginTop: -6 },
  progRow: { flexDirection: 'row', alignItems: 'center', gap: 14, marginTop: 4 },
  ring: { width: 60, height: 60, borderRadius: 30, borderWidth: 5, borderColor: c.mint, alignItems: 'center', justifyContent: 'center' },
  ringTxt: { color: c.ink, fontWeight: '900', fontSize: 16 },
  progTitle: { color: c.ink, fontWeight: '900', fontSize: 16 },
  bar: { height: 8, borderRadius: 4, backgroundColor: c.line, marginTop: 8, overflow: 'hidden' },
  barFill: { height: 8, borderRadius: 4, backgroundColor: c.mint },
  card: { backgroundColor: c.card, borderRadius: radius.lg, paddingHorizontal: 14, paddingVertical: 4 },
  card2: { backgroundColor: c.card, borderRadius: radius.lg, padding: 14, flexDirection: 'row', alignItems: 'center', gap: 12 },
  step: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 13, borderRadius: radius.sm },
  badge: { width: 32, height: 32, borderRadius: 16, alignItems: 'center', justifyContent: 'center' },
  badgeOk: { backgroundColor: c.mint },
  badgeNo: { borderWidth: 2, borderColor: c.line },
  badgeTxt: { color: c.muted, fontWeight: '900' },
  stepTitle: { color: c.ink, fontWeight: '800', fontSize: 15.5 },
  stepSub: { color: c.muted, fontSize: 12.5, marginTop: 1 },
  go: { backgroundColor: c.go, borderRadius: 99, paddingHorizontal: 12, paddingVertical: 7 },
  goDone: { backgroundColor: c.card2 },
  goTxt: { color: '#fff', fontWeight: '900', fontSize: 12.5 },
  help: { backgroundColor: c.card2, borderRadius: radius.md, padding: 12, gap: 8, marginBottom: 10 },
  helpTxt: { color: c.ink, fontSize: 14, lineHeight: 20 },
  b: { fontWeight: '900' },
  ready: { backgroundColor: c.go, borderRadius: 99, height: 58, alignItems: 'center', justifyContent: 'center', marginTop: 6 },
  readyTxt: { color: '#fff', fontWeight: '900', fontSize: 17 },
  later: { backgroundColor: 'transparent', borderWidth: 2, borderColor: c.line },
}));
