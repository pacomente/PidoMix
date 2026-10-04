import Ionicons from '@expo/vector-icons/Ionicons';
import { router } from 'expo-router';
import { Alert, Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { colors, radius } from '@/lib/theme';
import { useSession } from '@/state/session';

const VEHICLE: Record<string, string> = { moto: '🛵 Moto', bici: '🚲 Bici', auto: '🚗 Auto', pie: '🚶 A pie' };

function Item({ icon, label, onPress, danger }: { icon: React.ComponentProps<typeof Ionicons>['name']; label: string; onPress: () => void; danger?: boolean }) {
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [st.item, pressed && { backgroundColor: '#1d1d1d' }]}>
      <Ionicons name={icon} size={22} color={danger ? '#FF6B57' : '#fff'} />
      <Text style={[st.itemText, danger && { color: '#FF6B57' }]}>{label}</Text>
    </Pressable>
  );
}

export default function Menu() {
  const insets = useSafeAreaInsets();
  const { state, logout } = useSession();
  const c = state?.courier;
  return (
    <View style={st.back}>
      <Pressable style={StyleSheet.absoluteFill} onPress={() => router.back()} accessibilityLabel="Cerrar menú" />
      <View style={[st.panel, { paddingTop: insets.top + 20, paddingBottom: insets.bottom + 20 }]}>
        <View style={st.avatar}><Text style={st.avatarText}>{(c?.name || '?').slice(0, 1).toUpperCase()}</Text></View>
        <Text style={st.name}>{c?.name}</Text>
        <Text style={st.meta}>{VEHICLE[c?.vehicle || ''] || c?.vehicle} · {c?.fleet === 'local' ? `Repartidor de ${c?.store}` : 'Flota Trappi'}</Text>
        <Text style={st.meta}>{c?.phone}</Text>
        <View style={{ height: 24 }} />
        <Item icon="wallet-outline" label="Ganancias" onPress={() => { router.back(); router.push('/earnings'); }} />
        <Item icon="map-outline" label="Volver al mapa" onPress={() => router.back()} />
        <View style={{ flex: 1 }} />
        <Item icon="log-out-outline" label="Cerrar sesión" danger onPress={() => Alert.alert('¿Cerrar sesión?', 'Te vas a desconectar y vas a tener que volver a entrar con tu PIN.', [
          { text: 'Cancelar', style: 'cancel' },
          { text: 'Cerrar sesión', style: 'destructive', onPress: async () => { await logout(); router.replace('/login'); } },
        ])} />
      </View>
    </View>
  );
}

const st = StyleSheet.create({
  back: { flex: 1, backgroundColor: 'rgba(0,0,0,.5)' },
  panel: { width: '82%', maxWidth: 360, flex: 1, backgroundColor: '#000', paddingHorizontal: 20 },
  avatar: { width: 64, height: 64, borderRadius: 32, backgroundColor: colors.dark2, alignItems: 'center', justifyContent: 'center' },
  avatarText: { color: '#fff', fontSize: 28, fontWeight: '900' },
  name: { color: '#fff', fontSize: 24, fontWeight: '900', marginTop: 12 },
  meta: { color: '#AAA', marginTop: 2 },
  item: { flexDirection: 'row', alignItems: 'center', gap: 14, paddingVertical: 16, paddingHorizontal: 8, borderRadius: radius.sm },
  itemText: { color: '#fff', fontSize: 17, fontWeight: '700' },
});
