import * as Haptics from 'expo-haptics';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Ill } from '@/components/kit';
import { money } from '@/lib/format';
import { api } from '@/lib/api';
import { useRepeat } from '@/lib/repeat';
import { colors } from '@/lib/theme';
import type { ModifierGroup } from '@/lib/types';
import { useFetch } from '@/lib/useFetch';
import { useApp } from '@/state/app-state';

const PINK = '#EC4899';
const CAFE = '#6F4E37';

const Tags = ({ tags }: { tags?: string[] }) => (
  <>{(tags ?? []).map(t => <Text key={t} style={[st.tag, t === 'VEGANO' ? st.tagVeg : st.tagTacc]}>{t}</Text>)}</>
);

// "Frutilla (sin TACC)": la marca ya va aparte, en verde
const clean = (n: string) => n.replace(/\s*[(-]?\s*(sin tacc|sin gluten|vegano|vegana)\s*\)?/gi, '').trim();

/** Heladería: el pote se va llenando con el color de cada gusto, en el orden en que se sirven. */
export function FlavorPicker({ group, sel, onToggle }: { group: ModifierGroup; sel: number[]; onToggle: (id: number) => void }) {
  const max = group.max_select;
  const chosen = sel.map(id => group.options.find(o => o.id === id)).filter(Boolean) as ModifierGroup['options'];
  // bochas: hasta 3 arriba del pote (2 abajo y 1 arriba), el resto se cuenta
  const spots = [{ left: 4, top: 24 }, { left: 50, top: 24 }, { left: 27, top: 2 }, { left: 27, top: 30 }];
  return (
    <View>
      <View style={st.potRow}>
        <View style={st.pot} accessibilityElementsHidden>
          {chosen.slice(0, 4).map((o, i) => <View key={o.id} style={[st.scoop, spots[i], { backgroundColor: o.color || '#F3D3E2' }]} />)}
          <View style={st.potBase}><Text style={st.potText}>{chosen.length ? `${chosen.length}/${max}` : 'VACÍO'}</Text></View>
        </View>
        <View style={{ flex: 1 }}>
          <Text style={st.potTitle}>{chosen.length} de {max} gustos</Text>
          <Text style={st.potSub}>{chosen.length >= max ? '¡Listo! Tocá uno elegido para sacarlo.' : 'Se sirven en el orden en que los elegís.'}</Text>
          <View style={st.bars}>{Array.from({ length: max }, (_, i) => <View key={i} style={[st.bar, i < chosen.length && { backgroundColor: PINK }]} />)}</View>
        </View>
      </View>
      {group.options.map(o => {
        const n = sel.indexOf(o.id);
        const full = n < 0 && sel.length >= max;
        return (
          <Pressable key={o.id} onPress={() => { onToggle(o.id); }} style={[st.flavor, full && { opacity: 0.45 }]}
            accessibilityRole="checkbox" accessibilityState={{ checked: n >= 0, disabled: full }} accessibilityLabel={`${o.name}${n >= 0 ? `, gusto ${n + 1}` : ''}`}>
            <View style={[st.dot, { backgroundColor: o.color || '#F3D3E2' }]} />
            <View style={{ flex: 1 }}>
              <Text style={st.flavorName}>{clean(o.name)} <Tags tags={o.tags} /></Text>
              {o.price_extra > 0 && <Text style={st.extra}>+{money(o.price_extra)}</Text>}
            </View>
            <View style={[st.num, n >= 0 && st.numOn]}>{n >= 0 && <Text style={st.numText}>{n + 1}</Text>}</View>
          </Pressable>
        );
      })}
    </View>
  );
}

/** Cafetería: los tamaños como tarjetas, con la taza que crece. Muestra el precio final de cada tamaño. */
export function SizeCards({ group, sel, base, onPick }: { group: ModifierGroup; sel: number[]; base: number; onPick: (id: number) => void }) {
  return (
    <View style={st.sizes}>
      {group.options.map((o, i) => {
        const on = sel.includes(o.id);
        const size = 24 + Math.min(i, 3) * 7;
        return (
          <Pressable key={o.id} onPress={() => { onPick(o.id); Haptics.selectionAsync().catch(() => {}); }} style={[st.size, on && st.sizeOn]}
            accessibilityRole="radio" accessibilityState={{ checked: on }}>
            <View style={{ height: 46, justifyContent: 'flex-end' }}><Ill e="☕" size={size} /></View>
            <Text style={st.sizeName} numberOfLines={1}>{o.name.replace(/\s*\d{2,4}\s*(ml|cc)\b/i, '')}</Text>
            <Text style={st.sizeSub}>{o.ml ? `${o.ml} ml · ` : ''}{money(base + o.price_extra)}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

/** Opciones de a una como chips, con el recargo al lado ("Almendras +$400"). */
export function PriceChips({ group, sel, onToggle, dark = colors.ink }: { group: ModifierGroup; sel: number[]; onToggle: (id: number) => void; dark?: string }) {
  return (
    <View style={st.chips}>
      {group.options.map(o => {
        const on = sel.includes(o.id);
        return (
          <Pressable key={o.id} onPress={() => onToggle(o.id)} style={[st.chip, on && { backgroundColor: dark, borderColor: dark }]}
            accessibilityRole={group.max_select === 1 ? 'radio' : 'checkbox'} accessibilityState={{ checked: on }}>
            <Text style={[st.chipText, on && { color: '#fff' }]}>{o.name}{o.price_extra > 0 && <Text style={[st.chipExtra, on && { color: '#E8C9A3' }]}> +{money(o.price_extra)}</Text>}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

export const RUBRO_BUTTON: Record<string, string> = { heladeria: PINK, cafeteria: CAFE };

const st = StyleSheet.create({
  potRow: { flexDirection: 'row', alignItems: 'center', gap: 14, backgroundColor: '#FFF1F7', borderRadius: 20, padding: 12, marginBottom: 6 },
  pot: { width: 100, height: 100 },
  scoop: { position: 'absolute', width: 46, height: 46, borderRadius: 23, borderWidth: 1, borderColor: 'rgba(0,0,0,.06)' },
  potBase: { position: 'absolute', left: 8, right: 8, bottom: 2, height: 46, backgroundColor: '#fff', borderWidth: 2, borderColor: '#F9D2E4',
    borderTopLeftRadius: 6, borderTopRightRadius: 6, borderBottomLeftRadius: 20, borderBottomRightRadius: 20, alignItems: 'center', justifyContent: 'center' },
  potText: { fontSize: 11, fontWeight: '900', color: '#9D174D', letterSpacing: 0.4 },
  potTitle: { fontSize: 20, fontWeight: '900', color: colors.ink, letterSpacing: -0.4 },
  potSub: { color: colors.muted, fontSize: 13, marginTop: 2 },
  bars: { flexDirection: 'row', gap: 5, marginTop: 8 },
  bar: { width: 22, height: 7, borderRadius: 9, backgroundColor: '#F3D3E2' },
  flavor: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: '#F1EFF5' },
  dot: { width: 34, height: 34, borderRadius: 17, borderWidth: 1, borderColor: 'rgba(0,0,0,.08)' },
  flavorName: { fontSize: 15.5, fontWeight: '700', color: colors.ink },
  extra: { color: colors.muted, fontSize: 12.5 },
  tag: { fontSize: 10, fontWeight: '900', overflow: 'hidden' },
  tagTacc: { color: '#15803D' },
  tagVeg: { color: '#B45309' },
  num: { width: 28, height: 28, borderRadius: 14, borderWidth: 2, borderColor: '#DCD8E6', alignItems: 'center', justifyContent: 'center' },
  numOn: { backgroundColor: PINK, borderColor: PINK },
  numText: { color: '#fff', fontWeight: '900', fontSize: 14 },
  sizes: { flexDirection: 'row', gap: 8 },
  size: { flex: 1, borderWidth: 1.5, borderColor: colors.line, borderRadius: 16, paddingVertical: 10, paddingHorizontal: 4, alignItems: 'center', backgroundColor: '#fff' },
  sizeOn: { borderColor: CAFE, backgroundColor: '#FFF6EA' },
  sizeName: { fontWeight: '900', color: colors.ink, fontSize: 14.5, marginTop: 4 },
  sizeSub: { color: colors.muted, fontSize: 11.5, fontWeight: '700', marginTop: 2 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: { paddingHorizontal: 14, paddingVertical: 9, borderRadius: 99, borderWidth: 1.5, borderColor: colors.line, backgroundColor: '#fff' },
  chipText: { fontWeight: '800', color: colors.ink, fontSize: 14 },
  chipExtra: { color: colors.muted, fontWeight: '700' },
  usual: { flexDirection: 'row', alignItems: 'center', gap: 12, borderRadius: 20, padding: 12, marginTop: 12 },
  usualSmall: { color: '#F3D9B8', fontSize: 11, fontWeight: '800', letterSpacing: 0.6 },
  usualName: { color: '#fff', fontWeight: '900', fontSize: 15.5 },
  usualSub: { color: '#EBDCCB', fontSize: 12.5 },
  usualBtn: { backgroundColor: '#FFD43B', borderRadius: 12, paddingHorizontal: 11, paddingVertical: 8 },
  usualBtnText: { color: '#3B2416', fontWeight: '900', fontSize: 13 },
  coldNote: { flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: '#ECFEFF', borderRadius: 16, padding: 12, marginTop: 12 },
  coldText: { flex: 1, color: '#0E7490', fontSize: 13, lineHeight: 18 },
});

/** Cafetería / heladería: "tu café de siempre": el último pedido entregado en este local, para repetirlo con un toque. */
export function UsualCard({ storeName, rubro }: { storeName: string; rubro?: string | null }) {
  const { orders } = useApp();
  const repeat = useRepeat();
  const mine = orders.filter(x => x.store_name === storeName).slice(0, 3);
  // el último pedido entregado en este local (el más nuevo puede estar todavía en curso)
  const res = useFetch(async () => {
    for (const x of mine) {
      const o = await api.order(x.id, x.token).catch(() => null);
      if (o?.status === 'ENTREGADO' && o.items.length) return o;
    }
    return null;
  }, [mine.map(x => x.id).join()]);
  const o = res.data;
  if (!o) return null;
  const it = o.items[0];
  const cafe = rubro === 'cafeteria';
  const extra = o.items.length > 1 ? ` y ${o.items.length - 1} más` : '';
  return (
    <Pressable onPress={() => repeat(o)} style={[st.usual, { backgroundColor: cafe ? '#3B2416' : '#9D174D' }]} accessibilityRole="button" accessibilityLabel={`Repetir ${it.name}`}>
      <Ill e={cafe ? '☕' : '🍨'} size={40} />
      <View style={{ flex: 1 }}>
        <Text style={st.usualSmall}>{cafe ? 'TU CAFÉ DE SIEMPRE' : 'TU HELADO DE SIEMPRE'}</Text>
        <Text style={st.usualName} numberOfLines={1}>{it.quantity > 1 ? `${it.quantity}× ` : ''}{it.name}{extra}</Text>
        {!!it.modifiers_text && <Text style={st.usualSub} numberOfLines={1}>{it.modifiers_text}</Text>}
      </View>
      <View style={st.usualBtn}><Text style={st.usualBtnText}>↻ Repetir</Text></View>
    </Pressable>
  );
}

/** Heladería: aviso arriba de la carta. */
export function ColdNotice() {
  return (
    <View style={st.coldNote}>
      <Ill e="❄" size={24} />
      <Text style={st.coldText}><Text style={{ fontWeight: '900', color: '#155E75' }}>Helado: </Text>en el seguimiento ves hace cuánto salió del local, para guardarlo en el freezer a tiempo.</Text>
    </View>
  );
}

