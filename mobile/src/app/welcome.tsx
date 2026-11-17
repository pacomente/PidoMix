import Ionicons from '@expo/vector-icons/Ionicons';
import { router, Stack } from 'expo-router';
import { setStatusBarStyle } from 'expo-status-bar';
import { useEffect } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Grad, Ill } from '@/components/kit';
import { openWebPage } from '@/lib/auth';
import { save } from '@/lib/storage';
import { useApp } from '@/state/app-state';

/** los rubros girando alrededor del logo: [emoji, ángulo en grados, tamaño] */
const ORBIT: [string, number, number][] = [['🥩', -70, 54], ['🍕', -20, 58], ['💊', 30, 46], ['🛵', 92, 66], ['🛒', 150, 58], ['🍔', 205, 62]];
const R = 128;

/** Primera vez que se abre la app: los rubros girando alrededor del logo, el mensaje y entrar con email. */
export default function WelcomeScreen() {
  const insets = useSafeAreaInsets();
  const { location } = useApp();
  useEffect(() => { setStatusBarStyle('light'); return () => setStatusBarStyle('dark'); }, []);
  const done = (to: 'login' | 'browse') => {
    save('welcomed', true);
    if (to === 'login') router.replace('/account');
    else router.replace(location ? '/' : '/location');
  };
  return (
    <Grad colors={['#7C3AED', '#4C1D95']} style={[st.wrap, { paddingTop: insets.top, paddingBottom: insets.bottom + 16 }]}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={st.orbitBox}>
        <View style={st.ring} />
        <View style={st.ring2} />
        {ORBIT.map(([e, deg, size]) => {
          const a = (deg * Math.PI) / 180;
          return <Ill key={e} e={e} size={size} style={{ position: 'absolute', left: 160 + R * Math.cos(a) - size / 2, top: 160 + R * Math.sin(a) - size / 2 }} />;
        })}
        <View style={st.logo}>
          <Text style={st.logoText}>Trappi</Text>
          <Ill e="✨" size={34} style={{ position: 'absolute', right: -10, top: -12 }} />
        </View>
      </View>
      <View style={{ paddingHorizontal: 26 }}>
        <Text style={st.title}>Todo lo de tu ciudad,{'\n'}en tu puerta</Text>
        <Text style={st.sub}>Comida, súper, kioscos, carnicerías y farmacias. Pedí en segundos y seguí a tu repartidor en vivo.</Text>
        <Pressable style={st.primary} onPress={() => done('login')} accessibilityRole="button">
          <Ionicons name="mail" size={20} color="#7C3AED" /><Text style={st.primaryText}>Entrar con mi email</Text>
        </Pressable>
        <Pressable style={st.ghost} onPress={() => done('browse')} accessibilityRole="button"><Text style={st.ghostText}>Mirar sin cuenta</Text></Pressable>
        <Text style={st.legal}>Te mandamos un código, sin contraseñas. Al seguir aceptás los{' '}
          <Text style={st.link} onPress={() => openWebPage('/terminos')}>Términos</Text> y la <Text style={st.link} onPress={() => openWebPage('/privacidad')}>Privacidad</Text>.</Text>
      </View>
    </Grad>
  );
}

const st = StyleSheet.create({
  wrap: { flex: 1, justifyContent: 'flex-end' },
  orbitBox: { width: 320, height: 320, alignSelf: 'center', marginBottom: 18 },
  ring: { position: 'absolute', left: 160 - R, top: 160 - R, width: R * 2, height: R * 2, borderRadius: R, borderWidth: 1.5, borderColor: 'rgba(255,255,255,.18)', borderStyle: 'dashed' },
  ring2: { position: 'absolute', left: 160 - 78, top: 160 - 78, width: 156, height: 156, borderRadius: 78, backgroundColor: 'rgba(255,255,255,.06)' },
  logo: { position: 'absolute', left: 160 - 66, top: 160 - 66, width: 132, height: 132, borderRadius: 32, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center',
    shadowColor: '#2E1065', shadowOpacity: 0.45, shadowRadius: 22, shadowOffset: { width: 0, height: 14 }, elevation: 10 },
  logoText: { color: '#6C2BD9', fontWeight: '900', fontSize: 34, letterSpacing: -1.2 },
  title: { color: '#fff', fontSize: 33, fontWeight: '900', letterSpacing: -1.1, lineHeight: 37 },
  sub: { color: '#E9DDFF', fontSize: 15.5, lineHeight: 22, marginTop: 10 },
  primary: { marginTop: 22, height: 56, borderRadius: 18, backgroundColor: '#fff', flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 10 },
  primaryText: { color: '#1A1523', fontWeight: '900', fontSize: 17 },
  ghost: { marginTop: 12, height: 54, borderRadius: 18, borderWidth: 1.5, borderColor: 'rgba(255,255,255,.4)', alignItems: 'center', justifyContent: 'center' },
  ghostText: { color: '#fff', fontWeight: '800', fontSize: 16 },
  legal: { color: 'rgba(233,221,255,.8)', fontSize: 12, textAlign: 'center', marginTop: 16, lineHeight: 17 },
  link: { textDecorationLine: 'underline', color: '#fff' },
});
