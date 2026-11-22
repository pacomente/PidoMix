import Ionicons from '@expo/vector-icons/Ionicons';
import { Stack, router } from 'expo-router';
import { useState } from 'react';
import { Pressable, RefreshControl, ScrollView, Share, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Grad, Ill } from '@/components/kit';
import { LoginCard } from '@/components/login-card';
import { TierCard } from '@/components/tier-card';
import { api } from '@/lib/api';
import { money } from '@/lib/format';
import { colors, radius } from '@/lib/theme';
import { useFetch } from '@/lib/useFetch';
import { useApp } from '@/state/app-state';

type Filter = 'todos' | 'ganados' | 'usados';

// qué fue cada movimiento de puntos (el servidor manda el tipo)
const KIND: Record<string, { e: string; label: string }> = {
  earn: { e: '🛍', label: 'Pedido entregado' }, redeem: { e: '🧾', label: 'Usaste puntos' }, gift: { e: '🎂', label: 'Regalo de Trappi' },
  referral: { e: '🤝', label: 'Invitaste a un amigo' }, restore: { e: '↩', label: 'Te devolvimos puntos' }, reverse: { e: '↩', label: 'Se descontaron puntos' },
  adjust: { e: '✏', label: 'Ajuste' },
};

const dateOf = (iso: string) => new Date(iso).toLocaleDateString('es-AR', { day: 'numeric', month: 'short' });

/** Billetera: tus puntos (y cuánta plata son), cuándo vencen, de dónde salieron, tu nivel, tus sellos e invitar amigos. */
export default function WalletScreen() {
  const insets = useSafeAreaInsets();
  const { account } = useApp();
  const points = useFetch(() => (account ? api.myPoints() : Promise.resolve(null)), [account?.id]);
  const stamps = useFetch(() => (account ? api.myStamps().catch(() => null) : Promise.resolve(null)), [account?.id]);
  const invite = useFetch(() => (account ? api.myInvite().catch(() => null) : Promise.resolve(null)), [account?.id]);
  const [filter, setFilter] = useState<Filter>('todos');
  const p = points.data?.enabled ? points.data : null;
  const history = (p?.history ?? []).filter(h => filter === 'todos' || (filter === 'ganados' ? h.points > 0 : h.points < 0));
  const earned = (p?.history ?? []).filter(h => h.points > 0).reduce((n, h) => n + h.points, 0);
  const used = (p?.history ?? []).filter(h => h.points < 0).reduce((n, h) => n - h.points, 0);
  const refresh = () => { points.refresh(); stamps.refresh(); invite.refresh(); };

  return (
    <View style={{ flex: 1, backgroundColor: colors.bg }}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={[st.top, { paddingTop: insets.top + 8 }]}>
        <Pressable onPress={() => router.back()} style={st.back} accessibilityLabel="Volver"><Ionicons name="arrow-back" size={22} color={colors.ink} /></Pressable>
        <Text style={st.h1}>Billetera</Text>
        {!!p?.tier && <Text style={st.tierChip}>{p.tier.emoji} {p.tier.label}</Text>}
      </View>
      {!account ? (
        <ScrollView contentContainerStyle={{ padding: 16 }}>
          <LoginCard title="Entrá para ver tu billetera" text="Tus puntos, tu nivel, tus sellos y tus cupones quedan en tu cuenta. Te mandamos un código por email: sin contraseñas." onDone={refresh} />
        </ScrollView>
      ) : (
        <ScrollView contentContainerStyle={{ padding: 16, gap: 12, paddingBottom: insets.bottom + 24 }}
          refreshControl={<RefreshControl refreshing={points.refreshing} onRefresh={refresh} tintColor={colors.brand} />}>
          {points.data && !p && (
            <View style={st.card}><Text style={st.h3}>Los Puntos Trappi todavía no están activos</Text><Text style={st.muted}>Cuando se prendan, vas a ver acá tus puntos y cuánto valen.</Text></View>
          )}
          {!!p && (
            <>
              <Grad colors={['#6C2BD9', '#3A1585']} style={st.balance}>
                <View style={st.glow} />
                <Text style={st.balanceSmall}>Puntos Trappi disponibles</Text>
                <Text style={st.balanceBig}>{p.points.toLocaleString('es-AR')}<Text style={st.balancePts}> pts</Text></Text>
                <Text style={st.balanceEq}>= {money(p.value)} de descuento</Text>
                <View style={st.balanceRow}>
                  <Text style={st.balanceNote}>+{earned.toLocaleString('es-AR')} ganados</Text>
                  <Text style={st.balanceNote}>{p.expiring ? `${p.expiring.toLocaleString('es-AR')} vencen el ${p.expiring_at ? dateOf(p.expiring_at) : 'pronto'}` : 'Nada por vencer'}</Text>
                </View>
              </Grad>

              <View style={st.quick}>
                <Pressable style={st.qbtn} onPress={() => router.push('/scan')} accessibilityRole="button"><Ill e="📷" size={28} /><Text style={st.qText}>Pagar en un local</Text></Pressable>
                <Pressable style={st.qbtn} onPress={() => router.push('/')} accessibilityRole="button"><Ill e="🛵" size={28} /><Text style={st.qText}>Usarlos en un pedido</Text></Pressable>
                {invite.data?.enabled && (
                  <Pressable style={st.qbtn} onPress={() => invite.data?.enabled && Share.share({ message: invite.data.share_text }).catch(() => {})} accessibilityRole="button">
                    <Ill e="🤝" size={28} /><Text style={st.qText}>Invitar (+{invite.data.inviter_points})</Text>
                  </Pressable>
                )}
              </View>

              {!!p.tier && <TierCard tier={p.tier} points={p.points} />}

              <View style={st.card}>
                <View style={st.rowBetween}><Text style={st.h3}>Movimientos</Text><Text style={st.muted}>Usaste {used.toLocaleString('es-AR')}</Text></View>
                <View style={st.chips}>
                  {(['todos', 'ganados', 'usados'] as Filter[]).map(f => (
                    <Pressable key={f} onPress={() => setFilter(f)} style={[st.chip, filter === f && st.chipOn]} accessibilityRole="radio" accessibilityState={{ selected: filter === f }}>
                      <Text style={[st.chipText, filter === f && { color: '#fff' }]}>{f[0].toUpperCase() + f.slice(1)}</Text>
                    </Pressable>
                  ))}
                </View>
                {!history.length && <Text style={st.muted}>{filter === 'todos' ? 'Todavía no tenés movimientos: con tu primer pedido entregado empezás a sumar.' : 'Nada por acá.'}</Text>}
                {history.map((h, i) => {
                  const k = KIND[h.kind] ?? { e: h.points > 0 ? '➕' : '➖', label: 'Movimiento' };
                  return (
                    <View key={i} style={[st.mv, i > 0 && st.mvLine]}>
                      <View style={[st.mvIco, { backgroundColor: h.points > 0 ? '#E8F8EE' : '#FDECEC' }]}><Ill e={k.e} size={20} /></View>
                      <View style={{ flex: 1 }}>
                        <Text style={st.mvTitle} numberOfLines={1}>{h.note || k.label}</Text>
                        <Text style={st.muted}>{dateOf(h.created_at)}{h.order_id ? ` · Pedido #${h.order_id}` : ''}</Text>
                      </View>
                      <Text style={[st.mvPts, { color: h.points > 0 ? colors.good : colors.bad }]}>{h.points > 0 ? '+' : '−'}{Math.abs(h.points).toLocaleString('es-AR')}</Text>
                    </View>
                  );
                })}
              </View>
            </>
          )}

          {!!stamps.data?.cards.length && (
            <View style={st.card}>
              <Text style={st.h3}>Tus sellos</Text>
              {stamps.data.cards.map(c => (
                <View key={c.store.slug} style={{ gap: 6 }}>
                  <View style={st.rowBetween}><Text style={st.mvTitle}>{c.store.name}</Text><Text style={st.muted}>{c.stamps} de {c.goal}</Text></View>
                  <View style={st.stamps}>
                    {Array.from({ length: c.goal }, (_, i) => <View key={i} style={[st.stamp, i < c.stamps && st.stampOn]}>{i < c.stamps && <Ionicons name="checkmark" size={14} color="#fff" />}</View>)}
                  </View>
                  {!!c.reward && <Text style={st.muted}>Premio: {c.reward}</Text>}
                  {c.rewards.map(r => <Text key={r.code} style={st.coupon}>🎟 Cupón {r.code}{r.expires_at ? ` · vence el ${dateOf(r.expires_at)}` : ''}</Text>)}
                </View>
              ))}
            </View>
          )}

          {!!p && (
            <Text style={[st.muted, { textAlign: 'center' }]}>
              Sumás 1 punto cada {money(p.rules.pesos_per_point)} · cada punto vale {money(p.rules.point_value)} · vencen a los {p.rules.months} meses · se usan desde {p.rules.min} puntos (hasta el {p.rules.max_percent}% del pedido).
            </Text>
          )}
        </ScrollView>
      )}
    </View>
  );
}

const st = StyleSheet.create({
  top: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 16, paddingBottom: 8 },
  back: { width: 40, height: 40, borderRadius: 20, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center' },
  h1: { flex: 1, fontSize: 24, fontWeight: '900', color: colors.ink, letterSpacing: -0.4 },
  tierChip: { backgroundColor: '#fff', borderRadius: radius.pill, paddingHorizontal: 10, paddingVertical: 5, fontWeight: '800', color: colors.ink, overflow: 'hidden' },
  h3: { fontSize: 15.5, fontWeight: '800', color: colors.ink },
  muted: { color: colors.muted, fontSize: 12.5 },
  card: { backgroundColor: '#fff', borderRadius: 20, padding: 14, gap: 10 },
  balance: { borderRadius: 24, padding: 18, overflow: 'hidden' },
  glow: { position: 'absolute', right: -40, top: -50, width: 170, height: 170, borderRadius: 85, backgroundColor: 'rgba(255,255,255,.08)' },
  balanceSmall: { color: 'rgba(255,255,255,.8)', fontWeight: '600', fontSize: 13 },
  balanceBig: { color: '#fff', fontWeight: '900', fontSize: 40, letterSpacing: -1 },
  balancePts: { fontSize: 16, color: 'rgba(255,255,255,.8)' },
  balanceEq: { alignSelf: 'flex-start', color: '#fff', fontWeight: '800', fontSize: 13, backgroundColor: 'rgba(255,255,255,.15)', paddingHorizontal: 10, paddingVertical: 4, borderRadius: 99, overflow: 'hidden' },
  balanceRow: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 14 },
  balanceNote: { color: 'rgba(255,255,255,.85)', fontWeight: '600', fontSize: 12 },
  quick: { flexDirection: 'row', gap: 8 },
  qbtn: { flex: 1, backgroundColor: '#fff', borderRadius: 16, paddingVertical: 10, paddingHorizontal: 4, alignItems: 'center', gap: 3 },
  qText: { fontSize: 11.5, fontWeight: '800', color: colors.ink, textAlign: 'center' },
  rowBetween: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  chips: { flexDirection: 'row', gap: 6 },
  chip: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: radius.pill, backgroundColor: colors.bg },
  chipOn: { backgroundColor: colors.ink },
  chipText: { fontWeight: '800', color: colors.ink, fontSize: 12.5 },
  mv: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 8 },
  mvLine: { borderTopWidth: 1, borderTopColor: colors.line },
  mvIco: { width: 38, height: 38, borderRadius: 12, alignItems: 'center', justifyContent: 'center' },
  mvTitle: { fontWeight: '800', color: colors.ink, fontSize: 14 },
  mvPts: { fontWeight: '900', fontSize: 15 },
  stamps: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  stamp: { width: 28, height: 28, borderRadius: 14, borderWidth: 2, borderStyle: 'dashed', borderColor: '#C9B3F5', backgroundColor: colors.brandSoft, alignItems: 'center', justifyContent: 'center' },
  stampOn: { backgroundColor: colors.brand, borderColor: colors.brand, borderStyle: 'solid' },
  coupon: { fontWeight: '800', color: colors.brand, fontSize: 13 },
});
