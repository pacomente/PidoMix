import Ionicons from '@expo/vector-icons/Ionicons';
import * as Haptics from 'expo-haptics';
import { Image } from 'expo-image';
import { router, Stack, useLocalSearchParams } from 'expo-router';
import { useMemo, useState } from 'react';
import { Pressable, ScrollView, Share, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Grad, Ill } from '@/components/kit';
import { FlavorPicker, PriceChips, RUBRO_BUTTON, SizeCards } from '@/components/rubro-options';
import { confirmReplace, ErrorState, Loading } from '@/components/ui';
import { api } from '@/lib/api';
import { weightLabel } from '@/lib/cart';
import { money } from '@/lib/format';
import { colors } from '@/lib/theme';
import type { CartLine, ModifierGroup } from '@/lib/types';
import { useFetch } from '@/lib/useFetch';
import { useApp } from '@/state/app-state';

/** "1,000 kg" (como la balanza) */
const scale = (g: number) => `${(g / 1000).toFixed(3).replace('.', ',')} kg`;
/** botones del peso: "½ kg", "1 kg", "1½ kg" */
const nice = (g: number) => ({ 250: '¼ kg', 500: '½ kg', 750: '¾ kg', 1500: '1½ kg' } as Record<number, string>)[g] ?? weightLabel(g);
// un grupo de opciones sin costo y de a una (cómo se prepara, grosor) se elige con chips
const isChips = (g: ModifierGroup) => g.max_select === 1 && !g.required && !g.min_select && g.options.every(o => !o.price_extra);
// en la cafetería, la leche o la intensidad también van como chips, con el recargo al lado
const isPriceChips = (g: ModifierGroup, rubro?: string) => ['cafeteria', 'restaurante', 'bar'].includes(rubro ?? '') && g.options.length <= 6 && g.options.every(o => o.name.length <= 18);

/** Producto: foto o ilustración grande, «Más pedido», opciones claras (o el peso, para lo que se vende por kg) y el total. */
export default function ProductScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const insets = useSafeAreaInsets();
  const { cart, addToCart, favorites, location } = useApp();
  const res = useFetch(() => api.product(Number(id)), [id]);
  const [picked, setPicked] = useState<Record<number, number[]>>({});
  const [qty, setQty] = useState(1);
  const [grams, setGrams] = useState<number | null>(null);
  const [sides, setSides] = useState<number[]>([]);  // restaurante / bar: bebida, postre o "va bien con" (van como productos aparte)
  const night = res.data?.rubro === 'restaurante' || res.data?.rubro === 'bar';
  const menu = useFetch(() => (night && res.data ? api.store(res.data.store.slug, location).then(r => r.menu) : Promise.resolve(null)), [res.data?.store.slug, night]);

  const p = res.data;
  const extras = useMemo(() => (p ? p.groups.reduce((sum, g) => sum + g.options.filter(o => picked[g.id]?.includes(o.id)).reduce((n, o) => n + o.price_extra, 0), 0) : 0), [p, picked]);
  if (res.loading && !p) return <Loading />;
  if (res.error || !p) return <ErrorState message={res.error || 'Producto no encontrado'} onRetry={res.reload} />;

  const w = p.weight ?? null;
  const g = w ? (grams ?? (w.presets.includes(1000) ? 1000 : w.presets.includes(500) ? 500 : w.min)) : null;
  const perKg = p.price + extras;
  // por peso: el precio (y los extras) es por kg; el servidor lo vuelve a calcular al cotizar
  const unit = g ? Math.round(perKg * g / 10) / 100 : perKg;
  const presets = w ? [...new Set([w.min, ...w.presets])].filter(x => x >= w.min).slice(0, 4) : [];
  const missing = p.groups.filter(gr => (picked[gr.id]?.length ?? 0) < (gr.required ? Math.max(1, gr.min_select) : gr.min_select));
  const fav = favorites.includes(p.store.slug);

  const toggle = (gr: ModifierGroup, optionId: number) => {
    setPicked(cur => {
      const sel = cur[gr.id] ?? [];
      if (sel.includes(optionId)) return { ...cur, [gr.id]: sel.filter(x => x !== optionId) };
      if (gr.max_select === 1) return { ...cur, [gr.id]: [optionId] };
      if (gr.max_select && sel.length >= gr.max_select) return cur;
      return { ...cur, [gr.id]: [...sel, optionId] };
    });
    Haptics.selectionAsync().catch(() => {});
  };
  const stepBy = (d: number) => { if (!w || !g) return; setGrams(Math.min(20000, Math.max(w.min, g + d * w.step))); Haptics.selectionAsync().catch(() => {}); };
  const add = () => {
    // en el orden en que se eligieron (los gustos de helado se sirven así)
    const chosen = p.groups.flatMap(gr => (picked[gr.id] ?? []).map(oid => gr.options.find(o => o.id === oid)!).filter(Boolean));
    const line: CartLine = {
      product_id: p.id, quantity: qty, modifiers: chosen.map(o => o.id), name: p.name, unit_price: unit,
      modifiers_text: [...(g ? [weightLabel(g)] : []), ...chosen.map(o => o.name)].join(', ') || null, store_slug: p.store.slug, store_name: p.store.name, grams: g,
    };
    const extraLines: CartLine[] = all.filter(x => sides.includes(x.id)).map(x => ({
      product_id: x.id, quantity: 1, modifiers: [], name: x.name, unit_price: x.price, modifiers_text: null, store_slug: p.store.slug, store_name: p.store.name,
    }));
    const done = () => { extraLines.forEach(l => addToCart(l)); Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {}); router.back(); };
    if (addToCart(line) === 'other_store') confirmReplace(cart[0].store_name, () => { addToCart(line, true); done(); });
    else done();
  };
  // restaurante: «¿lo hacés menú?» con bebida y postre del local; bar: lo que «va bien con» la birra (comida del local)
  const all = (menu.data ?? []).flatMap(m => m.products.map(x => ({ ...x, sec: m.title.toLowerCase() })))
    .filter(x => x.id !== p.id && !x.customizable && !x.weight && !x.sold_out);
  const pick = (re: RegExp, yes = true) => all.filter(x => re.test(x.sec) === yes).slice(0, 4);
  const DRINKS = /bebid|gaseos|refresc|jugo|cerve|birra|trago|vino|tirad|sin alcohol/;
  const companions: { title: string; items: typeof all }[] = !night || w ? []
    : p.rubro === 'bar' ? [{ title: 'Va bien con', items: pick(DRINKS, false) }]
    : [{ title: 'Bebida', items: pick(/bebid|gaseos|refresc|jugo/) }, { title: 'Postre', items: pick(/postre|dulce/) }];
  const shownComp = companions.filter(c => c.items.length);
  const sidesTotal = all.filter(x => sides.includes(x.id)).reduce((n, x) => n + x.price, 0);
  const toggleSide = (sid: number) => { setSides(cur => (cur.includes(sid) ? cur.filter(x => x !== sid) : [...cur, sid])); Haptics.selectionAsync().catch(() => {}); };
  // lo elegido, a la vista sobre el plato (hasta 3)
  const chosenNames = p.groups.flatMap(gr => (picked[gr.id] ?? []).map(oid => gr.options.find(o => o.id === oid)?.name)).filter(Boolean).slice(0, 3) as string[];
  const head: readonly [string, string, ...string[]] = night && !w ? ['#6C2BD9', '#4C1D95', '#1E143C'] : w ? ['#FECDD3', '#FDA4AF'] : p.rubro === 'heladeria' ? ['#FFF1F7', '#FBCFE8'] : p.rubro === 'cafeteria' ? ['#FFF1DE', '#F5D9B5'] : ['#FEF3C7', '#FCD34D'];
  const btn = p.rubro === 'bar' ? '#FFD43B' : RUBRO_BUTTON[p.rubro ?? ''] ?? colors.brand;
  // cafetería y heladería: la foto más chica, lo importante es armarlo (tamaño, gustos)
  const compact = !!RUBRO_BUTTON[p.rubro ?? ''];
  // bar: toda la pantalla en violeta oscuro con amarillo (como la imagen)
  const dk = p.rubro === 'bar';
  const D = { bg: '#1A1035', card: '#271A4D', line: '#3A2A6B', yellow: '#FFD43B', sub: '#A79FC4' };
  const red = '#E11D48';

  return (
    <View style={{ flex: 1, backgroundColor: dk ? D.bg : '#fff' }}>
      <Stack.Screen options={{ headerShown: false }} />
      <ScrollView contentContainerStyle={{ paddingBottom: 24 }}>
        <Grad colors={head} style={[st.hero, { paddingTop: insets.top + 8 }, compact && { height: 250 }]}>
          <View style={st.heroTop}>
            <Pressable onPress={() => router.back()} style={st.round} accessibilityLabel="Cerrar"><Ionicons name="close" size={22} color={colors.ink} /></Pressable>
            <Pressable onPress={() => Share.share({ message: `${p.name} en ${p.store.name}: pedilo en Trappi` }).catch(() => {})} style={st.round} accessibilityLabel="Compartir">
              <Ionicons name={fav ? 'heart' : 'share-outline'} size={20} color={fav ? red : colors.ink} />
            </Pressable>
          </View>
          <View style={st.heroArt}>
            {p.image_url ? <Image source={{ uri: p.image_url }} style={[st.photo, compact && { height: 150 }]} contentFit="cover" /> : <Ill e={p.emoji} size={compact ? 140 : 190} />}
            {!p.image_url && !night && <Ill e="✨" size={30} style={{ position: 'absolute', left: 40, top: 20 }} />}
            {night && chosenNames.map((n, i) => (
              <View key={n} style={[st.pill, i === 0 ? { left: 0, top: 18 } : i === 1 ? { right: 0, top: 70 } : { left: 8, bottom: 6 }]}>
                <Text style={st.pillText} numberOfLines={1}>{n}</Text>
              </View>
            ))}
          </View>
          {!!w && <View style={st.kgPill}><Ill e="⚖" size={16} /><Text style={st.kgPillText}>Se vende por kg</Text></View>}
        </Grad>

        <View style={[st.sheet, dk && { backgroundColor: D.bg }]}>
          <View style={{ flexDirection: 'row', alignItems: 'flex-start', gap: 10 }}>
            <Text style={[st.name, { flex: 1 }, dk && { color: '#fff' }]}>{p.name}</Text>
            {p.featured && !w && <View style={st.hot}><Text style={st.hotText}>🔥 Más pedido</Text></View>}
          </View>
          {w ? <Text style={[st.price, { color: red }]}>{money(p.price)} <Text style={st.perKg}>por kg</Text></Text> : null}
          {!!p.description && <Text style={[st.desc, dk && { color: D.sub }]}>{p.description}{w ? '' : ''}</Text>}
          {!w && (
            <View style={{ flexDirection: 'row', alignItems: 'baseline', gap: 8 }}>
              <Text style={[st.price, dk && { color: '#fff' }]}>{money(p.price)}</Text>
              {!!p.previous_price && <Text style={st.prev}>{money(p.previous_price)}</Text>}
            </View>
          )}
          {!!p.unit_price_text && <Text style={st.unitText}>{p.unit_price_text}</Text>}

          {!!w && !!g && (
            <View style={{ marginTop: 14 }}>
              <View style={st.rowBetween}><Text style={st.gTitle}>¿Cuánto querés?</Text><Text style={st.gHint}>de a {weightLabel(w.step)}</Text></View>
              <View style={st.wboxes}>
                {presets.map(x => {
                  const on = x === g;
                  return (
                    <Pressable key={x} onPress={() => { setGrams(x); Haptics.selectionAsync().catch(() => {}); }} style={[st.wbox, on && { borderColor: red, backgroundColor: '#FFF1F2' }]} accessibilityRole="radio" accessibilityState={{ checked: on }}>
                      <Text style={[st.wboxBig, on && { color: red }]}>{nice(x)}</Text>
                      <Text style={st.wboxSmall}>{money(Math.round(perKg * x / 1000))}</Text>
                    </Pressable>
                  );
                })}
              </View>
              <View style={st.wstep}>
                <Pressable onPress={() => stepBy(-1)} style={st.wbtn} accessibilityLabel="Menos"><Text style={st.wbtnText}>−</Text></Pressable>
                <Text style={st.wnow}>{scale(g)}</Text>
                <Pressable onPress={() => stepBy(1)} style={st.wbtn} accessibilityLabel="Más"><Text style={st.wbtnText}>+</Text></Pressable>
              </View>
            </View>
          )}

          {p.groups.map(gr => {
            const isMissing = missing.includes(gr);
            const tag = gr.required || gr.min_select ? 'Obligatorio' : gr.max_select > 1 ? `Hasta ${gr.max_select}` : 'Opcional';
            return (
              <View key={gr.id} style={{ marginTop: 18 }}>
                <View style={st.rowBetween}>
                  <Text style={[st.gTitle, dk && { color: '#fff' }]}>{gr.name}</Text>
                  <View style={[st.tag, dk && { backgroundColor: D.card }, tag === 'Obligatorio' && { backgroundColor: isMissing ? '#FEF3C7' : '#E6F8EE' }]}>
                    <Text style={[st.tagText, tag === 'Obligatorio' && { color: isMissing ? '#92400E' : colors.good }]}>{tag === 'Obligatorio' && !isMissing ? 'Listo' : tag}</Text>
                  </View>
                </View>
                {gr.display === 'without' ? (
                  <View style={st.chips}>
                    {gr.options.map(o => {
                      const on = !!picked[gr.id]?.includes(o.id);
                      return (
                        <Pressable key={o.id} onPress={() => toggle(gr, o.id)} style={[st.chip, st.chipNo, on && st.chipNoOn]} accessibilityRole="checkbox" accessibilityState={{ checked: on }}>
                          <Text style={[st.chipText, { color: on ? colors.brand : colors.muted }]}>{on ? '✕ ' : ''}{o.name}</Text>
                        </Pressable>
                      );
                    })}
                  </View>
                ) : gr.display === 'flavors' ? (
                  <FlavorPicker group={gr} sel={picked[gr.id] ?? []} onToggle={oid => toggle(gr, oid)} />
                ) : gr.display === 'sizes' ? (
                  <SizeCards group={gr} sel={picked[gr.id] ?? []} base={p.price} onPick={oid => toggle(gr, oid)}
                    e={p.rubro === 'bar' ? '🍺' : p.rubro === 'cafeteria' ? '☕' : p.emoji} accent={btn} night={dk} />
                ) : isPriceChips(gr, p.rubro) ? (
                  <PriceChips group={gr} sel={picked[gr.id] ?? []} onToggle={oid => toggle(gr, oid)} dark={p.rubro === 'cafeteria' ? '#3B2416' : colors.ink} night={dk} />
                ) : isChips(gr) ? (
                  <View style={st.chips}>
                    {gr.options.map(o => {
                      const on = !!picked[gr.id]?.includes(o.id);
                      return (
                        <Pressable key={o.id} onPress={() => toggle(gr, o.id)} style={[st.chip, on && st.chipOn]} accessibilityRole="radio" accessibilityState={{ checked: on }}>
                          <Text style={[st.chipText, on && { color: '#fff' }]}>{o.name}</Text>
                        </Pressable>
                      );
                    })}
                  </View>
                ) : gr.options.map(o => {
                  const on = !!picked[gr.id]?.includes(o.id);
                  const radio = gr.max_select === 1;
                  return (
                    <Pressable key={o.id} onPress={() => toggle(gr, o.id)} style={st.option} accessibilityRole={radio ? 'radio' : 'checkbox'} accessibilityState={{ checked: on }}>
                      <Text style={[st.optName, dk && { color: '#fff' }]}>{o.name}</Text>
                      {o.price_extra > 0 && <Text style={st.optPrice}>+{money(o.price_extra)}</Text>}
                      <View style={[radio ? st.radio : st.check, on && st.on]}>{on && (radio ? <View style={st.radioDot} /> : <Ionicons name="checkmark" size={15} color="#fff" />)}</View>
                    </Pressable>
                  );
                })}
              </View>
            );
          })}

          {shownComp.length > 0 && (
            <View style={[st.combo, dk && { backgroundColor: D.card, borderWidth: 1, borderColor: D.line }]}>
              <Text style={[st.comboTitle, dk && { color: '#fff' }]}>{p.rubro === 'bar' ? '¿Le sumás algo?' : '¿Lo hacés menú?'}</Text>
              <Text style={[st.comboSub, dk && { color: D.sub }]}>{p.rubro === 'bar' ? 'Para acompañar, del mismo local' : 'Sumale bebida y postre del mismo local'}</Text>
              {shownComp.map(c => (
                <View key={c.title} style={{ marginTop: 10 }}>
                  <Text style={[st.gTitle, dk && { color: '#fff' }]}>{c.title}</Text>
                  <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8, paddingTop: 8 }}>
                    {c.items.map(x => {
                      const on = sides.includes(x.id);
                      return (
                        <Pressable key={x.id} onPress={() => toggleSide(x.id)} style={[st.side, dk && { backgroundColor: D.bg, borderColor: D.line }, on && st.sideOn, on && dk && { borderColor: D.yellow, backgroundColor: '#3A2C14' }]} accessibilityRole="checkbox" accessibilityState={{ checked: on }} accessibilityLabel={`${x.name}, ${money(x.price)}`}>
                          <View style={[st.sideImg, dk && { backgroundColor: D.card }, on && !dk && { backgroundColor: '#fff' }]}>{x.image_url ? <Image source={{ uri: x.image_url }} style={StyleSheet.absoluteFill} contentFit="cover" /> : <Ill e={x.emoji} size={34} />}</View>
                          <Text style={[st.sideName, dk && { color: '#fff' }]} numberOfLines={2}>{x.name}</Text>
                          <Text style={[st.sidePrice, dk && { color: D.yellow }]}>+{money(x.price)}</Text>
                        </Pressable>
                      );
                    })}
                  </ScrollView>
                </View>
              ))}
            </View>
          )}

          {!!w && (
            <View style={st.approx}>
              <Ill e="⚖" size={22} />
              <Text style={st.approxText}><Text style={{ fontWeight: '900', color: '#92400E' }}>Precio aproximado.</Text> Se pesa al prepararlo; si pagás en efectivo o transferencia y cambia, ajustamos el total (hasta ±10 %) y te avisamos. Con Mercado Pago se cobra este precio.</Text>
            </View>
          )}
        </View>
      </ScrollView>

      <View style={[st.footer, { paddingBottom: insets.bottom + 12 }, dk && { backgroundColor: D.bg, borderTopColor: D.line }]}>
        {!w && (
          <View style={[st.qty, dk && { backgroundColor: D.card }]}>
            <Pressable onPress={() => setQty(n => Math.max(1, n - 1))} hitSlop={6} accessibilityLabel="Quitar uno"><Text style={[st.qtyBtn, dk && { color: '#fff' }]}>−</Text></Pressable>
            <Text style={[st.qtyText, dk && { color: '#fff' }]}>{qty}</Text>
            <Pressable onPress={() => setQty(n => Math.min(99, n + 1))} hitSlop={6} accessibilityLabel="Agregar uno"><Text style={[st.qtyBtn, dk && { color: '#fff' }]}>+</Text></Pressable>
          </View>
        )}
        <Pressable onPress={add} disabled={missing.length > 0 || p.sold_out} style={[st.addBtn, { backgroundColor: btn, shadowColor: btn }, (missing.length > 0 || p.sold_out) && { opacity: 0.5 }]} accessibilityRole="button">
          <Text style={[st.addText, dk && { color: colors.ink }]}>{p.sold_out ? 'Sin stock' : missing.length ? `Elegí ${missing[0].name.toLowerCase()}` : w ? 'Agregar al pedido' : sides.length ? (p.rubro === 'bar' ? `Agregar con ${sides.length} más` : 'Agregar menú') : 'Agregar'}</Text>
          {!p.sold_out && !missing.length && <Text style={[st.addText, dk && { color: colors.ink }]}>{w ? '≈ ' : ''}{money(unit * qty + sidesTotal)}</Text>}
        </Pressable>
      </View>
    </View>
  );
}

const st = StyleSheet.create({
  hero: { height: 330, paddingHorizontal: 16 },
  heroTop: { flexDirection: 'row', justifyContent: 'space-between', zIndex: 2 },
  heroArt: { flex: 1, alignItems: 'center', justifyContent: 'center', marginBottom: 26 },
  photo: { width: 230, height: 190, borderRadius: 24 },
  round: { width: 42, height: 42, borderRadius: 21, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center', shadowColor: '#000', shadowOpacity: 0.12, shadowRadius: 6, shadowOffset: { width: 0, height: 2 }, elevation: 3 },
  kgPill: { position: 'absolute', left: 16, bottom: 40, flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: '#fff', borderRadius: 99, paddingHorizontal: 12, paddingVertical: 6 },
  kgPillText: { fontWeight: '900', color: '#BE123C', fontSize: 13 },
  sheet: { marginTop: -26, backgroundColor: '#fff', borderTopLeftRadius: 28, borderTopRightRadius: 28, paddingHorizontal: 18, paddingTop: 20, gap: 6 },
  name: { fontSize: 26, fontWeight: '900', color: colors.ink, letterSpacing: -0.7 },
  hot: { backgroundColor: '#FFE4E6', borderRadius: 99, paddingHorizontal: 10, paddingVertical: 5, marginTop: 4 },
  hotText: { color: '#BE123C', fontWeight: '900', fontSize: 12.5 },
  desc: { color: colors.muted, fontSize: 15, lineHeight: 21 },
  price: { fontSize: 26, fontWeight: '900', color: colors.ink, letterSpacing: -0.6 },
  perKg: { fontSize: 14, color: colors.muted, fontWeight: '700' },
  prev: { fontSize: 15, color: colors.muted, textDecorationLine: 'line-through' },
  unitText: { color: colors.muted, fontSize: 12.5 },
  rowBetween: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 },
  gTitle: { fontSize: 17, fontWeight: '900', color: colors.ink },
  gHint: { color: colors.muted, fontWeight: '700', fontSize: 13 },
  tag: { backgroundColor: '#F1EFF5', borderRadius: 99, paddingHorizontal: 10, paddingVertical: 4 },
  tagText: { fontWeight: '800', fontSize: 12, color: colors.muted },
  wboxes: { flexDirection: 'row', gap: 8 },
  wbox: { flex: 1, borderWidth: 1.5, borderColor: colors.line, borderRadius: 16, paddingVertical: 10, alignItems: 'center', backgroundColor: '#fff' },
  wboxBig: { fontWeight: '900', color: colors.ink, fontSize: 16 },
  wboxSmall: { color: colors.muted, fontSize: 11.5, fontWeight: '700', marginTop: 2 },
  wstep: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', backgroundColor: '#F4F3F8', borderRadius: 18, padding: 6, marginTop: 10 },
  wbtn: { width: 46, height: 46, borderRadius: 14, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center' },
  wbtnText: { fontSize: 24, fontWeight: '800', color: colors.ink },
  wnow: { fontSize: 22, fontWeight: '900', color: colors.ink, letterSpacing: -0.5 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: { paddingHorizontal: 15, paddingVertical: 9, borderRadius: 99, borderWidth: 1.5, borderColor: colors.line, backgroundColor: '#fff' },
  chipOn: { backgroundColor: colors.ink, borderColor: colors.ink },
  pill: { position: 'absolute', maxWidth: 150, backgroundColor: 'rgba(255,255,255,.14)', borderWidth: 1, borderColor: 'rgba(255,255,255,.25)', borderRadius: 99, paddingHorizontal: 10, paddingVertical: 4 },
  pillText: { color: '#fff', fontWeight: '900', fontSize: 12 },
  chipNo: { borderStyle: 'dashed' },
  chipNoOn: { backgroundColor: '#F1EAFF', borderColor: colors.brand },
  combo: { marginTop: 18, borderRadius: 20, padding: 14, backgroundColor: '#FFF6D6' },
  comboTitle: { fontSize: 19, fontWeight: '900', color: colors.ink, letterSpacing: -0.4 },
  comboSub: { color: '#92400E', fontSize: 13 },
  side: { width: 104, backgroundColor: '#fff', borderRadius: 16, padding: 8, borderWidth: 2, borderColor: 'transparent' },
  sideOn: { borderColor: colors.brand, backgroundColor: '#F1EAFF' },
  sideImg: { height: 56, borderRadius: 12, backgroundColor: '#F4F3F8', alignItems: 'center', justifyContent: 'center', overflow: 'hidden' },
  sideName: { fontWeight: '800', fontSize: 12.5, color: colors.ink, marginTop: 6 },
  sidePrice: { fontWeight: '900', fontSize: 13, color: colors.ink },
  chipText: { fontWeight: '800', color: colors.ink, fontSize: 14.5 },
  option: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 13, borderBottomWidth: 1, borderBottomColor: '#F1EFF5' },
  optName: { flex: 1, color: colors.ink, fontSize: 15.5, fontWeight: '600' },
  optPrice: { color: colors.ink, fontWeight: '700' },
  radio: { width: 24, height: 24, borderRadius: 12, borderWidth: 2, borderColor: '#D3CEDD', alignItems: 'center', justifyContent: 'center' },
  check: { width: 24, height: 24, borderRadius: 7, borderWidth: 2, borderColor: '#D3CEDD', alignItems: 'center', justifyContent: 'center' },
  on: { borderColor: colors.brand, backgroundColor: colors.brand },
  radioDot: { width: 9, height: 9, borderRadius: 5, backgroundColor: '#fff' },
  approx: { flexDirection: 'row', gap: 10, alignItems: 'flex-start', marginTop: 18, padding: 12, borderRadius: 16, backgroundColor: '#FFFBEB' },
  approxText: { flex: 1, color: '#78350F', fontSize: 13, lineHeight: 19 },
  footer: { flexDirection: 'row', gap: 12, alignItems: 'center', paddingHorizontal: 16, paddingTop: 12, backgroundColor: '#fff', borderTopWidth: 1, borderTopColor: colors.line },
  qty: { flexDirection: 'row', alignItems: 'center', gap: 14, backgroundColor: '#F4F3F8', borderRadius: 16, paddingHorizontal: 16, height: 54 },
  qtyBtn: { fontSize: 22, fontWeight: '800', color: colors.ink },
  qtyText: { fontWeight: '900', fontSize: 17, color: colors.ink },
  addBtn: { flex: 1, height: 56, borderRadius: 18, backgroundColor: colors.brand, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 18,
    shadowColor: colors.brand, shadowOpacity: 0.4, shadowRadius: 12, shadowOffset: { width: 0, height: 6 }, elevation: 5 },
  addText: { color: '#fff', fontWeight: '900', fontSize: 16.5 },
});
