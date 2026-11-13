import Ionicons from '@expo/vector-icons/Ionicons';
import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Button } from '@/components/ui';
import { api } from '@/lib/api';
import { radius, themed } from '@/lib/theme';
import type { StyleCatalog } from '@/lib/types';
import { useColors } from '@/state/prefs';
import { useSession } from '@/state/session';

/** «Tu estilo»: el personaje y el color con los que se ve en el mapa (y lo ve el cliente en el seguimiento).
 * Algunos personajes se desbloquean con entregas: lo controla el servidor. */
export default function Estilo() {
  const c = useColors(), st = useSt(c);
  const insets = useSafeAreaInsets();
  const { refresh } = useSession();
  const [cat, setCat] = useState<StyleCatalog | null>(null);
  const [avatar, setAvatar] = useState('');
  const [color, setColor] = useState('violeta');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.style().then(s => { setCat(s); setAvatar(s.avatar ?? ''); setColor(s.color); }).catch(e => setError(e instanceof Error ? e.message : 'No pudimos cargar los estilos.'));
  }, []);

  if (!cat) return <View style={st.center}>{error ? <Text style={st.err}>{error}</Text> : <ActivityIndicator color={c.ink} size="large" />}</View>;

  const hex = cat.colors.find(x => x.key === color)?.hex ?? c.go;
  const emoji = cat.avatars.find(a => a.key === avatar)?.emoji ?? null;
  const save = async () => {
    setSaving(true); setError(null);
    try {
      await api.setStyle(avatar, color);
      await refresh();
      router.back();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No se pudo guardar.');
    } finally { setSaving(false); }
  };

  return (
    <View style={{ flex: 1, backgroundColor: c.bg }}>
      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 120 }}>
        <Text style={st.sub}>Así te ves en el mapa. Lo ves vos y el cliente mientras le llevás el pedido.</Text>
        {/* vista previa: un pedacito de mapa con el personaje */}
        <View style={st.preview} accessible accessibilityLabel={emoji ? `Vista previa: ${emoji}` : 'Vista previa: el punto de siempre'}>
          {[30, 70].map(t => <View key={t} style={[st.road, { top: `${t}%` }]} />)}
          {[25, 70].map(l => <View key={l} style={[st.roadV, { left: `${l}%` }]} />)}
          {emoji
            ? <View style={[st.halo, { backgroundColor: hex + '40' }]}><View style={[st.me, { backgroundColor: hex }]}><Text style={st.meTxt}>{emoji}</Text></View></View>
            : <View style={st.dotHalo}><View style={st.dot} /></View>}
        </View>

        <Text style={st.h}>Personaje</Text>
        <View style={st.grid}>
          <Pressable onPress={() => setAvatar('')} style={[st.av, avatar === '' && st.avOn]} accessibilityRole="radio" accessibilityState={{ checked: avatar === '' }} accessibilityLabel="El punto de siempre">
            <View style={st.dot} />
          </Pressable>
          {cat.avatars.map(a => (
            <Pressable key={a.key} disabled={a.locked} onPress={() => setAvatar(a.key)} style={[st.av, avatar === a.key && st.avOn, a.locked && { opacity: 0.45 }]}
              accessibilityRole="radio" accessibilityState={{ checked: avatar === a.key, disabled: a.locked }}
              accessibilityLabel={a.locked ? `${a.label}: se desbloquea con ${a.unlock} entregas` : a.label}>
              <Text style={st.avTxt}>{a.emoji}</Text>
              {a.locked && <View style={st.lock}><Ionicons name="lock-closed" size={9} color="#14101F" /><Text style={st.lockTxt}>{a.unlock}</Text></View>}
            </Pressable>
          ))}
        </View>
        <Text style={st.note}>Llevás {cat.delivered} {cat.delivered === 1 ? 'entrega' : 'entregas'}. Los que tienen 🔒 se desbloquean al llegar a esa cantidad.</Text>

        <Text style={st.h}>Color</Text>
        <View style={st.colors}>
          {cat.colors.map(x => (
            <Pressable key={x.key} onPress={() => setColor(x.key)} style={[st.col, { backgroundColor: x.hex }, color === x.key && st.colOn]}
              accessibilityRole="radio" accessibilityState={{ checked: color === x.key }} accessibilityLabel={`Color ${x.key}`} />
          ))}
        </View>
        {!!error && <Text style={st.err}>{error}</Text>}
      </ScrollView>
      <View style={[st.foot, { paddingBottom: insets.bottom + 14 }]}>
        <Button title="Guardar mi estilo" variant="go" big loading={saving} onPress={save} />
      </View>
    </View>
  );
}

const useSt = themed(c => ({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: c.bg, padding: 24 },
  sub: { color: c.muted, fontSize: 14.5 },
  preview: { height: 180, borderRadius: radius.lg, backgroundColor: c.mapBg, marginTop: 14, alignItems: 'center', justifyContent: 'center', overflow: 'hidden' },
  road: { position: 'absolute', left: 0, right: 0, height: 10, backgroundColor: c.dark ? '#2C2A36' : '#FFFFFF' },
  roadV: { position: 'absolute', top: 0, bottom: 0, width: 10, backgroundColor: c.dark ? '#2C2A36' : '#FFFFFF' },
  halo: { width: 96, height: 96, borderRadius: 48, alignItems: 'center', justifyContent: 'center' },
  me: { width: 68, height: 68, borderRadius: 34, borderWidth: 4, borderColor: '#fff', alignItems: 'center', justifyContent: 'center' },
  meTxt: { fontSize: 36 },
  dotHalo: { width: 40, height: 40, borderRadius: 20, backgroundColor: 'rgba(108,43,217,.22)', alignItems: 'center', justifyContent: 'center' },
  dot: { width: 20, height: 20, borderRadius: 10, backgroundColor: c.go, borderWidth: 3, borderColor: '#fff' },
  h: { color: c.muted, fontWeight: '800', fontSize: 13, textTransform: 'uppercase', letterSpacing: 0.6, marginTop: 20, marginBottom: 10 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  av: { width: '18%', aspectRatio: 1, borderRadius: radius.md, backgroundColor: c.card, alignItems: 'center', justifyContent: 'center', borderWidth: 2, borderColor: 'transparent' },
  avOn: { borderColor: c.mint, backgroundColor: c.dark ? '#1D3B2E' : '#E3FBF0' },
  avTxt: { fontSize: 28 },
  lock: { position: 'absolute', right: -3, bottom: -3, flexDirection: 'row', alignItems: 'center', gap: 2, backgroundColor: c.warn, borderRadius: 99, paddingHorizontal: 5, paddingVertical: 1 },
  lockTxt: { color: '#14101F', fontSize: 10, fontWeight: '900' },
  note: { color: c.muted, fontSize: 13, marginTop: 10 },
  colors: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 },
  col: { width: 44, height: 44, borderRadius: 22, borderWidth: 3, borderColor: 'transparent' },
  colOn: { borderColor: c.dark ? '#fff' : '#14101F' },
  err: { color: c.dangerText, fontWeight: '700', marginTop: 14, textAlign: 'center' },
  foot: { position: 'absolute', left: 0, right: 0, bottom: 0, paddingHorizontal: 16, paddingTop: 12, backgroundColor: c.bg },
}));
