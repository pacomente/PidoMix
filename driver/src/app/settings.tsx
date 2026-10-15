import Ionicons from '@expo/vector-icons/Ionicons';
import { Pressable, ScrollView, Text, View } from 'react-native';

import { radius, themed, type Palette } from '@/lib/theme';
import { useColors, usePrefs, type NavApp, type ThemePref } from '@/state/prefs';

type St = ReturnType<typeof useSt>;

function Choice<T extends string>({ value, options, onPick, st, c }: { value: T; options: { key: T; label: string; sub?: string; icon: React.ComponentProps<typeof Ionicons>['name'] }[]; onPick: (v: T) => void; st: St; c: Palette }) {
  return (
    <View style={st.group}>
      {options.map((o, i) => {
        const on = o.key === value;
        return (
          <Pressable key={o.key} onPress={() => onPick(o.key)} style={[st.opt, i > 0 && st.optLine]} accessibilityRole="radio" accessibilityState={{ checked: on }} accessibilityLabel={o.label}>
            <Ionicons name={o.icon} size={22} color={c.ink} />
            <View style={{ flex: 1 }}>
              <Text style={st.optText}>{o.label}</Text>
              {!!o.sub && <Text style={st.optSub}>{o.sub}</Text>}
            </View>
            <Ionicons name={on ? 'radio-button-on' : 'radio-button-off'} size={22} color={on ? c.go : c.muted} />
          </Pressable>
        );
      })}
    </View>
  );
}

/** Ajustes del teléfono: tema de la app y con qué app navega. Se guardan en el celular. */
export default function Settings() {
  const c = useColors(), st = useSt(c);
  const { theme, navApp, set } = usePrefs();
  return (
    <ScrollView style={{ backgroundColor: c.bg }} contentContainerStyle={{ padding: 16, gap: 10, paddingBottom: 40 }}>
      <Text style={st.h}>Pantalla</Text>
      <Choice<ThemePref> st={st} c={c} value={theme} onPick={v => set({ theme: v })} options={[
        { key: 'auto', label: 'Automático', sub: 'Como el teléfono: oscuro de noche si lo tenés así', icon: 'phone-portrait-outline' },
        { key: 'light', label: 'Claro', sub: 'Se ve mejor a pleno sol', icon: 'sunny-outline' },
        { key: 'dark', label: 'Oscuro', sub: 'No encandila de noche y gasta menos batería', icon: 'moon-outline' },
      ]} />
      <Text style={st.h}>Navegación</Text>
      <Choice<NavApp> st={st} c={c} value={navApp} onPick={v => set({ navApp: v })} options={[
        { key: 'ask', label: 'Preguntarme cada vez', icon: 'help-circle-outline' },
        { key: 'google', label: 'Google Maps', icon: 'navigate-outline' },
        { key: 'waze', label: 'Waze', icon: 'car-sport-outline' },
      ]} />
      <Text style={st.note}>El botón «Navegar» del viaje abre la app que elijas con la dirección del local o del cliente.</Text>
    </ScrollView>
  );
}

const useSt = themed(c => ({
  h: { color: c.muted, fontWeight: '800', fontSize: 13, textTransform: 'uppercase', letterSpacing: 0.6, marginTop: 10, marginLeft: 4 },
  group: { backgroundColor: c.card, borderRadius: radius.md, overflow: 'hidden' },
  opt: { flexDirection: 'row', alignItems: 'center', gap: 14, paddingVertical: 14, paddingHorizontal: 16, minHeight: 60 },
  optLine: { borderTopWidth: 1, borderTopColor: c.line },
  optText: { color: c.ink, fontWeight: '800', fontSize: 16 },
  optSub: { color: c.muted, fontSize: 13, marginTop: 1 },
  note: { color: c.muted, fontSize: 13, marginHorizontal: 4 },
}));
