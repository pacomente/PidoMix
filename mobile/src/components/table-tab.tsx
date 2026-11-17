import * as Haptics from 'expo-haptics';
import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Grad, Ill } from '@/components/kit';
import { api } from '@/lib/api';
import { money } from '@/lib/format';
import { colors } from '@/lib/theme';
import { useFetch } from '@/lib/useFetch';

const D = { bg: '#1E143C', card: '#2A1F4A', line: '#3A2A6B', yellow: '#FFD43B', sub: '#A79FC4' };

/** Pedido desde la mesa: la cuenta de toda la mesa (la arma la caja), dividirla en partes iguales y llamar al mozo. */
export function TableTabCard({ orderId, token, storeSlug }: { orderId: number; token: string; storeSlug: string }) {
  const [people, setPeople] = useState(0);
  const [sent, setSent] = useState<string | null>(null);
  const res = useFetch(() => api.orderTable(orderId, token, people), [orderId, people]);
  const tab = res.data;
  if (!tab) return null;
  const call = async (kind: 'mozo' | 'cuenta') => {
    try {
      await api.tableCall(orderId, token, kind);
      setSent(kind === 'mozo' ? 'Le avisamos al mozo: ya viene.' : 'Pediste la cuenta: el mozo te la trae.');
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
      res.refresh();
    } catch {
      setSent('No pudimos avisar. Probá de nuevo o llamalo con la mano 🙂');
    }
  };
  const btns: [string, string, () => void, boolean][] = [
    ['🍺', 'Pedir otra ronda', () => router.push({ pathname: '/store/[slug]', params: { slug: storeSlug } }), false],
    ['🔔', tab.calls.includes('mozo') ? 'Ya lo llamaste' : 'Llamar al mozo', () => call('mozo'), tab.calls.includes('mozo')],
    ['🧾', tab.calls.includes('cuenta') ? 'Cuenta pedida' : 'Pedir la cuenta', () => call('cuenta'), tab.calls.includes('cuenta')],
  ];
  return (
    <View style={{ marginTop: 14 }}>
      <Grad colors={['#6C2BD9', '#8B5CF6', '#C026D3']} style={st.hero}>
        <Text style={st.heroSmall}>ESTÁS EN LA</Text>
        <Text style={st.heroTitle}>{tab.table}</Text>
        <Text style={st.heroSub}>Lo que pidan llega a esta mesa</Text>
        <Ill e="🍻" size={56} style={{ position: 'absolute', right: 12, top: 12 }} />
      </Grad>
      <View style={st.btns}>
        {btns.map(([e, label, onPress, on]) => (
          <Pressable key={label} onPress={onPress} style={[st.btn, on && st.btnOn]} accessibilityRole="button" accessibilityLabel={label}>
            <Ill e={e} size={30} />
            <Text style={[st.btnText, on && { color: '#FFE58A' }]} numberOfLines={2}>{label}</Text>
          </Pressable>
        ))}
      </View>
      {!!sent && <Text style={st.sent}>✅ {sent}</Text>}
      <View style={st.acc}>
        {tab.items.length ? (
          <>
            {tab.items.map((i, k) => (
              <View key={k} style={st.row}>
                <Text style={st.rowName} numberOfLines={2}>{i.quantity}× {i.name}{i.modifiers_text ? <Text style={{ color: D.sub }}> · {i.modifiers_text}</Text> : null}</Text>
                <Text style={st.rowPrice}>{money(i.total)}</Text>
              </View>
            ))}
            {!!tab.promo_discount && <View style={st.row}><Text style={[st.rowName, { color: '#86EFAC' }]}>🏷 Promos</Text><Text style={[st.rowPrice, { color: '#86EFAC' }]}>-{money(tab.promo_discount)}</Text></View>}
            <View style={st.total}><Text style={{ color: D.sub }}>Cuenta de la mesa</Text><Text style={st.totalText}>{money(tab.total)}</Text></View>
            <View style={st.split}>
              <Text style={{ color: '#D9CFF5', fontSize: 13 }}>Dividir:</Text>
              {[2, 3, 4, 5, 6].map(k => (
                <Pressable key={k} onPress={() => setPeople(people === k ? 0 : k)} style={[st.dot, people === k && { backgroundColor: D.yellow }]} accessibilityRole="button" accessibilityLabel={`Dividir entre ${k}`}>
                  <Text style={[st.dotText, people === k && { color: colors.ink }]}>{k}</Text>
                </Pressable>
              ))}
            </View>
            {!!tab.split && (
              <View style={st.each}>
                <Ill e="👥" size={28} />
                <View style={{ flex: 1 }}>
                  <Text style={st.eachTitle}>Entre {tab.split.people}: {money(tab.split.each)} cada uno</Text>
                  <Text style={st.eachSub}>Cada uno paga su parte en el local al pedir la cuenta.</Text>
                </View>
              </View>
            )}
            <Text style={st.note}>La cuenta la arma la caja del local y se actualiza sola.</Text>
          </>
        ) : <Text style={{ color: '#D9CFF5' }}>Todavía no hay nada en la cuenta de la mesa. Cuando el local cargue lo que pidieron, aparece acá.</Text>}
      </View>
    </View>
  );
}

const st = StyleSheet.create({
  hero: { borderRadius: 24, padding: 16, overflow: 'hidden' },
  heroSmall: { color: '#EDE4FF', fontSize: 11, fontWeight: '900', letterSpacing: 0.8 },
  heroTitle: { color: '#fff', fontSize: 30, fontWeight: '900', letterSpacing: -0.8 },
  heroSub: { color: '#EDE4FF', fontSize: 13 },
  btns: { flexDirection: 'row', gap: 8, marginTop: 10 },
  btn: { flex: 1, alignItems: 'center', gap: 6, backgroundColor: D.bg, borderWidth: 1, borderColor: D.line, borderRadius: 18, paddingVertical: 12, paddingHorizontal: 4 },
  btnOn: { backgroundColor: '#3A2C14', borderColor: D.yellow },
  btnText: { color: '#fff', fontWeight: '800', fontSize: 12.5, textAlign: 'center' },
  sent: { color: colors.good, fontWeight: '800', marginTop: 8 },
  acc: { marginTop: 10, backgroundColor: D.bg, borderRadius: 20, padding: 14 },
  row: { flexDirection: 'row', justifyContent: 'space-between', gap: 10, paddingVertical: 7, borderBottomWidth: 1, borderBottomColor: D.line },
  rowName: { color: '#fff', flex: 1, fontSize: 14 },
  rowPrice: { color: '#fff', fontWeight: '800' },
  total: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline', marginTop: 10 },
  totalText: { color: '#fff', fontWeight: '900', fontSize: 22 },
  split: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 12 },
  dot: { width: 34, height: 34, borderRadius: 17, backgroundColor: D.card, alignItems: 'center', justifyContent: 'center' },
  dotText: { color: '#fff', fontWeight: '900' },
  each: { flexDirection: 'row', alignItems: 'center', gap: 10, marginTop: 10, backgroundColor: '#3A2C14', borderWidth: 1, borderColor: '#5B4A10', borderRadius: 14, padding: 10 },
  eachTitle: { color: D.yellow, fontWeight: '900' },
  eachSub: { color: '#FFE89A', fontSize: 12 },
  note: { color: D.sub, fontSize: 12, marginTop: 10 },
});
