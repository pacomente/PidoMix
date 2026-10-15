import Ionicons from '@expo/vector-icons/Ionicons';
import { router } from 'expo-router';
import { Alert, Linking, Platform, Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { money } from '@/lib/format';
import { radius, themed, type Palette } from '@/lib/theme';
import { APP_VERSION } from '@/lib/version';
import { useConfig } from '@/state/config';
import { useColors } from '@/state/prefs';
import { useSession } from '@/state/session';

const VEHICLE: Record<string, string> = { moto: '🛵 Moto', bici: '🚲 Bici', auto: '🚗 Auto', pie: '🚶 A pie' };

function Item({ icon, label, onPress, danger, c, st }: { icon: React.ComponentProps<typeof Ionicons>['name']; label: string; onPress: () => void; danger?: boolean; c: Palette; st: ReturnType<typeof useSt> }) {
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [st.item, pressed && { backgroundColor: c.card2 }]} accessibilityRole="button" accessibilityLabel={label}>
      <Ionicons name={icon} size={22} color={danger ? c.dangerText : c.ink} />
      <Text style={[st.itemText, danger && { color: c.dangerText }]}>{label}</Text>
      {!danger && <Ionicons name="chevron-forward" size={18} color={c.muted} style={{ marginLeft: 'auto' }} />}
    </Pressable>
  );
}

export default function Menu() {
  const insets = useSafeAreaInsets();
  const c = useColors(), st = useSt(c);
  const { state, logout } = useSession();
  const { support_whatsapp: support } = useConfig();
  const cour = state?.courier;
  const go = (path: '/earnings' | '/caja' | '/settings') => { router.back(); router.push(path); };
  const doLogout = async () => { await logout(); router.replace('/login'); };
  const askLogout = () => {
    if (Platform.OS === 'web') { if (window.confirm('¿Cerrar sesión?')) doLogout(); return; }  // Alert no tiene botones en la web
    Alert.alert('¿Cerrar sesión?', 'Te vas a desconectar y vas a tener que volver a entrar con tu PIN.', [
      { text: 'Cancelar', style: 'cancel' },
      { text: 'Cerrar sesión', style: 'destructive', onPress: doLogout },
    ]);
  };
  return (
    <View style={st.back}>
      <Pressable style={StyleSheet.absoluteFill} onPress={() => router.back()} accessibilityLabel="Cerrar menú" />
      <View style={[st.panel, { paddingTop: insets.top + 20, paddingBottom: insets.bottom + 20 }]}>
        <View style={st.avatar}><Text style={st.avatarText}>{(cour?.name || '?').slice(0, 1).toUpperCase()}</Text></View>
        <Text style={st.name}>{cour?.name}</Text>
        <Text style={st.meta}>{VEHICLE[cour?.vehicle || ''] || cour?.vehicle} · {cour?.fleet === 'local' ? `Repartidor de ${cour?.store}` : 'Flota Trappi'}</Text>
        <Text style={st.meta}>{cour?.phone}</Text>
        {!!state && (
          <View style={st.today}>
            <View style={{ flex: 1 }}><Text style={st.todayLbl}>Hoy</Text><Text style={st.todayVal}>{money(state.earnings.today)}</Text></View>
            <View style={{ flex: 1 }}><Text style={st.todayLbl}>7 días</Text><Text style={st.todayVal}>{money(state.earnings.week)}</Text></View>
          </View>
        )}
        <View style={{ height: 12 }} />
        <Item c={c} st={st} icon="wallet-outline" label="Ganancias" onPress={() => go('/earnings')} />
        {cour?.fleet === 'trappi' && <Item c={c} st={st} icon="cash-outline" label="Mi caja" onPress={() => go('/caja')} />}
        <Item c={c} st={st} icon="settings-outline" label="Ajustes" onPress={() => go('/settings')} />
        {!!support && <Item c={c} st={st} icon="logo-whatsapp" label="Ayuda de Trappi" onPress={() => Linking.openURL(`https://wa.me/${support.replace(/\D/g, '')}`)} />}
        <Item c={c} st={st} icon="map-outline" label="Volver al mapa" onPress={() => router.back()} />
        <View style={{ flex: 1 }} />
        <Item c={c} st={st} icon="log-out-outline" label="Cerrar sesión" danger onPress={askLogout} />
        <Text style={st.version}>Trappi Repartidor {APP_VERSION}</Text>
      </View>
    </View>
  );
}

const useSt = themed(c => ({
  back: { flex: 1, backgroundColor: 'rgba(0,0,0,.5)' },
  panel: { width: '82%', maxWidth: 360, flex: 1, backgroundColor: c.bg, paddingHorizontal: 20 },
  avatar: { width: 64, height: 64, borderRadius: 32, backgroundColor: c.card2, alignItems: 'center', justifyContent: 'center' },
  avatarText: { color: c.ink, fontSize: 28, fontWeight: '900' },
  name: { color: c.ink, fontSize: 24, fontWeight: '900', marginTop: 12 },
  meta: { color: c.muted, marginTop: 2 },
  today: { flexDirection: 'row', gap: 10, backgroundColor: c.card, borderRadius: radius.md, padding: 14, marginTop: 16 },
  todayLbl: { color: c.muted, fontWeight: '700', fontSize: 12.5 },
  todayVal: { color: c.ink, fontWeight: '900', fontSize: 20 },
  item: { flexDirection: 'row', alignItems: 'center', gap: 14, paddingVertical: 15, paddingHorizontal: 8, borderRadius: radius.sm },
  itemText: { color: c.ink, fontSize: 17, fontWeight: '700' },
  version: { color: c.muted, fontSize: 12, textAlign: 'center', marginTop: 8 },
}));
