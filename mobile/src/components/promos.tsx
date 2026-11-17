import { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Grad, Ill } from '@/components/kit';
import { colors } from '@/lib/theme';
import type { Product, StorePromo } from '@/lib/types';

/** La promo que le toca a un producto ahora (por producto o por su sección). */
export function promoFor(promos: StorePromo[] | undefined, p: Product): StorePromo | null {
  return (promos ?? []).find(x => x.on && (x.product_ids.includes(p.id) || (p.section_id != null && x.section_ids.includes(p.section_id)))) ?? null;
}

/** La más importante para el cartel: la que vale ahora y termina a una hora (happy hour), si no cualquiera de ahora, si no la que empieza más tarde. */
export function mainPromo(promos: StorePromo[] | undefined): StorePromo | null {
  const list = promos ?? [];
  return list.find(x => x.on && x.ends_at) ?? list.find(x => x.on) ?? list.find(x => !x.on) ?? null;
}

/** "0:42:18" hasta que termina (se actualiza cada segundo). */
export function useCountdown(to: string | null) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!to) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [to]);
  if (!to) return null;
  const left = Math.max(0, Math.floor((new Date(to).getTime() - now) / 1000));
  const h = Math.floor(left / 3600), m = Math.floor((left % 3600) / 60), sec = left % 60;
  return `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
}

/** Cartelito del producto: "2×1", "-20 %", "Combo". */
export function PromoTag({ promo, dark }: { promo: StorePromo | null; dark?: boolean }) {
  if (!promo) return null;
  return <Text style={[st.tag, dark && { backgroundColor: '#FFD43B', color: colors.ink }]}>{promo.kind === 'combo' ? 'COMBO' : promo.label}</Text>;
}

/** El happy hour (o la promo del día) con su cuenta regresiva. En el bar va amarillo; en el resto, oscuro con el reloj amarillo. */
export function HappyHour({ promo, bar, onPress }: { promo: StorePromo; bar?: boolean; onPress?: () => void }) {
  const left = useCountdown(promo.on ? promo.ends_at : null);
  const title = `${promo.ends_at || promo.start ? 'Happy hour' : 'Promo'} · ${promo.name}`;
  const sub = !promo.on ? `Arranca hoy a las ${promo.start}` : promo.ends_at ? 'Pedí antes de que termine' : 'Vale todo el día en la app';
  const body = (
    <>
      <Ill e={bar ? '🍻' : '🏷'} size={30} />
      <View style={{ flex: 1 }}>
        <Text style={[st.title, !bar && { color: '#fff' }]} numberOfLines={2}>{title}</Text>
        <Text style={[st.sub, !bar && { color: '#D9CFF5' }]} numberOfLines={1}>{sub}</Text>
      </View>
      <View style={[st.clock, !bar && { backgroundColor: '#FFD43B' }]}>
        <Text style={[st.clockText, !bar && { color: colors.ink }]}>{left ?? promo.label}</Text>
      </View>
    </>
  );
  return (
    <Pressable onPress={onPress} disabled={!onPress} accessibilityRole={onPress ? 'button' : undefined} accessibilityLabel={`${title}. ${sub}`}>
      {bar ? <View style={st.box}>{body}</View> : <Grad colors={['#1E143C', '#4C1D95']} style={st.box}>{body}</Grad>}
    </Pressable>
  );
}

const st = StyleSheet.create({
  box: { flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: '#FFD43B', borderRadius: 16, paddingHorizontal: 12, paddingVertical: 10, overflow: 'hidden' },
  title: { color: colors.ink, fontWeight: '900', fontSize: 14 },
  sub: { color: '#4C3D10', fontWeight: '700', fontSize: 11.5 },
  clock: { backgroundColor: colors.ink, borderRadius: 10, paddingHorizontal: 9, paddingVertical: 6 },
  clockText: { color: '#FFD43B', fontWeight: '900', fontSize: 14, fontVariant: ['tabular-nums'] },
  tag: { alignSelf: 'flex-start', backgroundColor: colors.brand, color: '#fff', fontWeight: '900', fontSize: 11, borderRadius: 7, paddingHorizontal: 6, paddingVertical: 2, overflow: 'hidden' },
});
