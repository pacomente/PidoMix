import { router, Stack } from 'expo-router';
import { setStatusBarStyle } from 'expo-status-bar';
import { useEffect } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { save } from '@/lib/storage';
import { colors } from '@/lib/theme';
import { useApp } from '@/state/app-state';

const BUBBLES = [['🍔', 24, 70, 74], ['🛒', 250, 40, 66], ['🥩', 150, 150, 58], ['💊', 300, 190, 48], ['🍦', 40, 230, 52], ['🍕', 210, 280, 60], ['🥕', 110, 330, 46]] as const;
const POINTS = [['🛵', 'Seguís tu pedido en vivo', 'Ves al repartidor en el mapa y cuánto falta'], ['🏅', 'Sumás puntos con cada pedido', 'Y subís de nivel: Bronce, Plata y Oro'],
  ['🏪', 'Todo tu barrio en una app', 'Comida, súper, kiosco, carnicería y farmacia']] as const;

/** Primera vez que se abre la app: qué es Trappi, con personalidad. Se muestra una sola vez. */
export default function WelcomeScreen() {
  const insets = useSafeAreaInsets();
  const { location } = useApp();
  useEffect(() => { setStatusBarStyle('light'); return () => setStatusBarStyle('dark'); }, []);
  const done = (to: 'start' | 'login') => {
    save('welcomed', true);
    if (to === 'login') router.replace('/account');
    else if (!location) router.replace('/location');
    else router.replace('/');
  };
  return (
    <View style={[st.wrap, { paddingTop: insets.top + 12, paddingBottom: insets.bottom + 18 }]}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={st.glowA} /><View style={st.glowB} />
      <View style={st.art}>
        {BUBBLES.map(([e, x, y, size], i) => (
          <View key={i} style={[st.bubble, { left: x, top: y, width: size + 26, height: size + 26, borderRadius: (size + 26) / 2 }]}><Text style={{ fontSize: size * 0.62 }}>{e}</Text></View>
        ))}
      </View>
      <Text style={st.logo}>Trappi</Text>
      <Text style={st.title}>Todo tu barrio,{'\n'}en un toque.</Text>
      <View style={st.points}>
        {POINTS.map(([e, t, d]) => (
          <View key={t} style={st.point}>
            <View style={st.pointIco}><Text style={{ fontSize: 20 }}>{e}</Text></View>
            <View style={{ flex: 1 }}><Text style={st.pointTitle}>{t}</Text><Text style={st.pointText}>{d}</Text></View>
          </View>
        ))}
      </View>
      <Pressable style={st.go} onPress={() => done('start')} accessibilityRole="button"><Text style={st.goText}>Empezar</Text></Pressable>
      <Pressable onPress={() => done('login')} hitSlop={10} accessibilityRole="button"><Text style={st.login}>Ya tengo cuenta · <Text style={{ textDecorationLine: 'underline' }}>Entrar</Text></Text></Pressable>
    </View>
  );
}

const st = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: colors.brand, paddingHorizontal: 22, overflow: 'hidden', justifyContent: 'flex-end' },
  glowA: { position: 'absolute', right: -90, top: -80, width: 320, height: 320, borderRadius: 160, backgroundColor: '#9333EA', opacity: 0.6 },
  glowB: { position: 'absolute', left: -110, top: 260, width: 300, height: 300, borderRadius: 150, backgroundColor: '#4C1D95', opacity: 0.45 },
  art: { position: 'absolute', left: 0, right: 0, top: 40, height: 420 },
  bubble: { position: 'absolute', backgroundColor: 'rgba(255,255,255,.16)', borderWidth: 1, borderColor: 'rgba(255,255,255,.25)', alignItems: 'center', justifyContent: 'center' },
  logo: { color: '#FFD43B', fontWeight: '900', fontSize: 20, letterSpacing: -0.3 },
  title: { color: '#fff', fontSize: 38, fontWeight: '900', letterSpacing: -1.2, lineHeight: 42, marginTop: 4 },
  points: { gap: 10, marginTop: 18, marginBottom: 22 },
  point: { flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: 'rgba(255,255,255,.12)', borderRadius: 18, padding: 11 },
  pointIco: { width: 40, height: 40, borderRadius: 13, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center' },
  pointTitle: { color: '#fff', fontWeight: '800', fontSize: 15 },
  pointText: { color: '#E9DDFF', fontSize: 12.5, marginTop: 1 },
  go: { backgroundColor: '#fff', borderRadius: 18, paddingVertical: 16, alignItems: 'center', shadowColor: '#000', shadowOpacity: 0.25, shadowRadius: 14, shadowOffset: { width: 0, height: 8 }, elevation: 6 },
  goText: { color: colors.brand, fontWeight: '900', fontSize: 17 },
  login: { color: '#fff', fontWeight: '700', textAlign: 'center', marginTop: 14, fontSize: 14.5 },
});
