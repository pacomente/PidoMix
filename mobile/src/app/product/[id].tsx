import * as Haptics from 'expo-haptics';
import { router, useLocalSearchParams } from 'expo-router';
import { useMemo, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Button, Chip, confirmReplace, ErrorState, Loading, Price, Thumb, s as ui } from '@/components/ui';
import { api } from '@/lib/api';
import { weightLabel } from '@/lib/cart';
import { money } from '@/lib/format';
import { colors, radius } from '@/lib/theme';
import type { CartLine, ModifierGroup } from '@/lib/types';
import { useFetch } from '@/lib/useFetch';
import { useApp } from '@/state/app-state';

const groupHint = (g: ModifierGroup) => {
  const min = g.required ? Math.max(1, g.min_select) : g.min_select;
  if (g.max_select === 1) return min ? 'Elegí 1' : 'Opcional · hasta 1';
  if (min && g.max_select) return min === g.max_select ? `Elegí ${min}` : `Elegí de ${min} a ${g.max_select}`;
  if (min) return `Elegí al menos ${min}`;
  return g.max_select ? `Opcional · hasta ${g.max_select}` : 'Opcional';
};

export default function ProductScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const insets = useSafeAreaInsets();
  const { cart, addToCart } = useApp();
  const res = useFetch(() => api.product(Number(id)), [id]);
  const [picked, setPicked] = useState<Record<number, number[]>>({});
  const [qty, setQty] = useState(1);
  const [grams, setGrams] = useState<number | null>(null);

  const p = res.data;
  const extras = useMemo(() => {
    if (!p) return 0;
    return p.groups.reduce((sum, g) => sum + g.options.filter(o => picked[g.id]?.includes(o.id)).reduce((n, o) => n + o.price_extra, 0), 0);
  }, [p, picked]);

  if (res.loading && !p) return <Loading />;
  if (res.error || !p) return <ErrorState message={res.error || 'Producto no encontrado'} onRetry={res.reload} />;

  const w = p.weight ?? null;
  const g = w ? (grams ?? (w.presets.includes(500) ? 500 : w.min)) : null;
  // por peso: el precio (y los extras) es por kg; el servidor lo vuelve a calcular al cotizar
  const unit = g ? Math.round((p.price + extras) * g / 10) / 100 : p.price + extras;
  const stepBy = (d: number) => { if (!w || !g) return; setGrams(Math.min(20000, Math.max(w.min, g + d * w.step))); Haptics.selectionAsync().catch(() => {}); };
  const missing = p.groups.filter(g => (picked[g.id]?.length ?? 0) < (g.required ? Math.max(1, g.min_select) : g.min_select));

  const toggle = (g: ModifierGroup, optionId: number) => {
    setPicked(cur => {
      const sel = cur[g.id] ?? [];
      if (sel.includes(optionId)) return { ...cur, [g.id]: sel.filter(x => x !== optionId) };
      if (g.max_select === 1) return { ...cur, [g.id]: [optionId] };
      if (g.max_select && sel.length >= g.max_select) return cur;
      return { ...cur, [g.id]: [...sel, optionId] };
    });
    Haptics.selectionAsync().catch(() => {});
  };

  const add = () => {
    const chosen = p.groups.flatMap(g => g.options.filter(o => picked[g.id]?.includes(o.id)));
    const line: CartLine = {
      product_id: p.id, quantity: qty, modifiers: chosen.map(o => o.id), name: p.name, unit_price: unit,
      modifiers_text: [...(g ? [weightLabel(g)] : []), ...chosen.map(o => o.name)].join(', ') || null, store_slug: p.store.slug, store_name: p.store.name,
      grams: g,
    };
    const done = () => { Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {}); router.back(); };
    if (addToCart(line) === 'other_store') confirmReplace(cart[0].store_name, () => { addToCart(line, true); done(); });
    else done();
  };

  return (
    <View style={{ flex: 1, backgroundColor: colors.bg }}>
      <ScrollView contentContainerStyle={{ paddingBottom: 24 }}>
        <Thumb uri={p.image_url} emoji={p.emoji} hue={p.hue} style={{ height: 300 }} emojiSize={110} />
        <View style={st.sheet}>
          <View style={st.badges}>
            {p.featured && <View style={[st.badge, { backgroundColor: '#FFE8D6' }]}><Text style={[st.badgeText, { color: '#C2410C' }]}>🔥 Más pedido</Text></View>}
            {!!w && <View style={[st.badge, { backgroundColor: colors.brandSoft }]}><Text style={[st.badgeText, { color: colors.brand }]}>⚖️ Se vende por peso</Text></View>}
            {p.customizable && !w && <View style={[st.badge, { backgroundColor: '#E6F8EE' }]}><Text style={[st.badgeText, { color: colors.good }]}>✨ Armalo a tu gusto</Text></View>}
          </View>
          <Text style={ui.h1}>{p.name}</Text>
          <Text style={ui.muted}>{p.store.name}</Text>
          {!!p.description && <Text style={{ color: colors.ink, fontSize: 15, lineHeight: 21 }}>{p.description}</Text>}
          <View style={{ marginTop: 4 }}><Price price={p.price} previous={p.previous_price} /></View>
          {!!w && <Text style={ui.muted}>Precio por kilo</Text>}
        </View>
        {!!w && !!g && (
          <View style={st.group}>
            <Text style={st.groupTitle}>¿Cuánto querés?</Text>
            <View style={st.wchips}>
              {w.presets.map(x => (
                <Pressable key={x} onPress={() => { setGrams(x); Haptics.selectionAsync().catch(() => {}); }} style={[st.wchip, x === g && st.wchipOn]} accessibilityRole="radio" accessibilityState={{ checked: x === g }}>
                  <Text style={[st.wchipText, x === g && { color: colors.brand }]}>{weightLabel(x)}</Text>
                </Pressable>
              ))}
            </View>
            <View style={st.wstep}>
              <Pressable onPress={() => stepBy(-1)} style={st.qtyBtn} accessibilityLabel="Menos"><Text style={st.qtyBtnText}>−</Text></Pressable>
              <View style={{ alignItems: 'center', minWidth: 130 }}>
                <Text style={st.wnow}>{weightLabel(g)}</Text>
                <Text style={ui.muted}>{money(unit)}</Text>
              </View>
              <Pressable onPress={() => stepBy(1)} style={st.qtyBtn} accessibilityLabel="Más"><Text style={st.qtyBtnText}>+</Text></Pressable>
            </View>
            <Text style={[ui.muted, { textAlign: 'center', fontSize: 12.5, marginTop: 8 }]}>El local lo pesa al prepararlo: puede variar unos gramos.</Text>
          </View>
        )}
        {p.groups.map(g => (
          <View key={g.id} style={st.group}>
            <View style={ui.row}>
              <Text style={st.groupTitle}>{g.name}</Text>
              {missing.includes(g) ? <Chip label="Obligatorio" tone="warn" /> : g.required ? <Chip label="Listo" tone="good" /> : null}
            </View>
            <Text style={[ui.muted, { marginBottom: 6 }]}>{groupHint(g)}</Text>
            {g.options.map(o => {
              const on = !!picked[g.id]?.includes(o.id);
              return (
                <Pressable key={o.id} onPress={() => toggle(g, o.id)} style={st.option} accessibilityRole={g.max_select === 1 ? 'radio' : 'checkbox'} accessibilityState={{ checked: on }}>
                  <View style={[g.max_select === 1 ? st.radio : st.check, on && st.on]}>{on && <Text style={{ color: '#fff', fontSize: 12, fontWeight: '900' }}>✓</Text>}</View>
                  <Text style={{ flex: 1, color: colors.ink, fontSize: 15 }}>{o.name}</Text>
                  {o.price_extra > 0 && <Text style={{ color: colors.muted, fontWeight: '600' }}>+{money(o.price_extra)}</Text>}
                </Pressable>
              );
            })}
          </View>
        ))}
      </ScrollView>
      <View style={[st.footer, { paddingBottom: insets.bottom + 12 }]}>
        <View style={st.qty}>
          <Pressable onPress={() => setQty(q => Math.max(1, q - 1))} style={st.qtyBtn} accessibilityLabel="Quitar uno"><Text style={st.qtyBtnText}>−</Text></Pressable>
          <Text style={st.qtyText}>{qty}</Text>
          <Pressable onPress={() => setQty(q => Math.min(99, q + 1))} style={st.qtyBtn} accessibilityLabel="Agregar uno"><Text style={st.qtyBtnText}>+</Text></Pressable>
        </View>
        <Button style={{ flex: 1 }} disabled={missing.length > 0 || p.sold_out}
          title={p.sold_out ? 'Sin stock' : missing.length ? `Elegí ${missing[0].name.toLowerCase()}` : `Agregar ${money(unit * qty)}`} onPress={add} />
      </View>
    </View>
  );
}

const st = StyleSheet.create({
  sheet: { marginTop: -28, backgroundColor: colors.bg, borderTopLeftRadius: 28, borderTopRightRadius: 28, padding: 16, paddingTop: 20, gap: 6 },
  badges: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginBottom: 2 },
  badge: { borderRadius: radius.pill, paddingHorizontal: 10, paddingVertical: 4 },
  badgeText: { fontWeight: '800', fontSize: 12.5 },
  group: { backgroundColor: '#fff', marginHorizontal: 16, marginBottom: 12, padding: 14, borderRadius: radius.md, borderWidth: 1, borderColor: colors.line },
  groupTitle: { fontSize: 17, fontWeight: '800', color: colors.ink },
  option: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 11, borderTopWidth: 1, borderTopColor: colors.line },
  radio: { width: 22, height: 22, borderRadius: 11, borderWidth: 2, borderColor: colors.line, alignItems: 'center', justifyContent: 'center' },
  check: { width: 22, height: 22, borderRadius: 6, borderWidth: 2, borderColor: colors.line, alignItems: 'center', justifyContent: 'center' },
  on: { backgroundColor: colors.brand, borderColor: colors.brand },
  footer: { flexDirection: 'row', gap: 12, alignItems: 'center', paddingHorizontal: 16, paddingTop: 12, backgroundColor: '#fff', borderTopWidth: 1, borderTopColor: colors.line },
  wchips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 10 },
  wchip: { paddingHorizontal: 14, paddingVertical: 9, borderRadius: radius.pill, borderWidth: 1.5, borderColor: colors.line, backgroundColor: '#fff' },
  wchipOn: { borderColor: colors.brand, backgroundColor: colors.brandSoft },
  wchipText: { fontWeight: '800', color: colors.ink, fontSize: 14.5 },
  wstep: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 18, marginTop: 14 },
  wnow: { fontSize: 26, fontWeight: '900', color: colors.ink, letterSpacing: -0.6 },
  qty: { flexDirection: 'row', alignItems: 'center', gap: 4, backgroundColor: colors.bg, borderRadius: radius.pill, padding: 4 },
  qtyBtn: { width: 40, height: 40, borderRadius: 20, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: colors.line },
  qtyBtnText: { fontSize: 22, fontWeight: '700', color: colors.brand, lineHeight: 24 },
  qtyText: { minWidth: 28, textAlign: 'center', fontWeight: '800', fontSize: 16, color: colors.ink },
});
