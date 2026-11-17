import { useState } from 'react';
import { Alert, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { api } from '@/lib/api';
import { colors, radius } from '@/lib/theme';
import type { MyPoints, Tier, TierKey } from '@/lib/types';

/** Colores de cada nivel (la tarjeta se ve como una tarjeta de socio). */
const LOOK: Record<TierKey, { bg: string; glow: string; ink: string; sub: string; bar: string }> = {
  bronce: { bg: '#C2773A', glow: '#E7A970', ink: '#2E1605', sub: '#4A2A10', bar: '#5B2E0C' },
  plata: { bg: '#9AA3B2', glow: '#E2E7EF', ink: '#1E2430', sub: '#323A48', bar: '#2B3240' },
  oro: { bg: '#F59E0B', glow: '#FFF1A8', ink: '#3D2A00', sub: '#5C3F00', bar: '#7C2D12' },
};
const MONTHS = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];

/** Nivel Bronce/Plata/Oro: puntos, % extra por pedido, cuánto falta para el siguiente. */
export function TierCard({ tier, points }: { tier: Tier; points: number }) {
  const l = LOOK[tier.key];
  const target = tier.next ? (tier.key === 'bronce' ? tier.silver : tier.gold) : tier.gold;
  const pct = Math.max(0.06, Math.min(1, tier.orders / Math.max(1, target)));
  return (
    <View style={[st.tier, { backgroundColor: l.bg, shadowColor: l.bg }]} accessibilityLabel={`Nivel ${tier.label}. ${points} Puntos Trappi.`}>
      <View style={[st.glow, { backgroundColor: l.glow }]} />
      <Text style={st.medal}>{tier.emoji}</Text>
      <Text style={[st.small, { color: l.sub }]}>TU NIVEL</Text>
      <Text style={[st.level, { color: l.ink }]}>{tier.label}</Text>
      <View style={st.stats}>
        <View><Text style={[st.statN, { color: l.ink }]}>{points.toLocaleString('es-AR')}</Text><Text style={[st.statT, { color: l.sub }]}>Puntos Trappi</Text></View>
        <View><Text style={[st.statN, { color: l.ink }]}>+{tier.bonus} %</Text><Text style={[st.statT, { color: l.sub }]}>puntos por pedido</Text></View>
        <View><Text style={[st.statN, { color: l.ink }]}>{tier.orders}</Text><Text style={[st.statT, { color: l.sub }]}>pedidos en el año</Text></View>
      </View>
      <View style={st.bar}><View style={[st.barIn, { width: `${pct * 100}%`, backgroundColor: l.bar }]} /></View>
      <Text style={[st.next, { color: l.sub }]}>
        {tier.next ? `Te ${tier.next.missing === 1 ? 'falta 1 pedido' : `faltan ${tier.next.missing} pedidos`} para ${tier.next.label} ${tier.next.emoji} (+${tier.next.bonus} % de puntos)`
          : '¡Llegaste al nivel más alto! Mantenelo pidiendo durante el año.'}
      </Text>
    </View>
  );
}

/** Regalo de cumpleaños: se carga una vez (día y mes) y en ese mes le llegan puntos. */
export function BirthdayCard({ data, onSaved }: { data: Extract<MyPoints, { enabled: true }>; onSaved: () => void }) {
  const [day, setDay] = useState('');
  const [month, setMonth] = useState('');
  const [saving, setSaving] = useState(false);
  const gift = data.tier?.birthday_points ?? 0;
  if (!data.tier || gift <= 0) return null;
  const b = data.birthday;
  const save = async () => {
    const d = Number(day), m = Number(month);
    if (!d || !m || d > 31 || m > 12) { Alert.alert('Revisá la fecha', 'Poné el día y el mes con números, por ejemplo 15 y 11.'); return; }
    setSaving(true);
    try { await api.setBirthday(d, m); onSaved(); }
    catch (e) { Alert.alert('No se pudo guardar', e instanceof Error ? e.message : 'Probá de nuevo.'); }
    finally { setSaving(false); }
  };
  return (
    <View style={st.bday}>
      <Text style={{ fontSize: 34 }}>🎂</Text>
      <View style={{ flex: 1, gap: 2 }}>
        {b ? (
          <>
            <Text style={st.bTitle}>Tu cumple: {b.day} de {MONTHS[b.month - 1]}</Text>
            <Text style={st.bText}>{data.birthday_gift ? `¡Feliz cumple! Te regalamos ${data.birthday_gift} puntos 🎉` : `Ese mes te regalamos ${gift} Puntos Trappi.`}</Text>
          </>
        ) : (
          <>
            <Text style={st.bTitle}>¿Cuándo es tu cumple?</Text>
            <Text style={st.bText}>Te regalamos {gift} puntos ese mes. Se carga una sola vez.</Text>
            <View style={st.bRow}>
              <TextInput value={day} onChangeText={setDay} placeholder="Día" keyboardType="number-pad" maxLength={2} style={st.bInput} placeholderTextColor={colors.muted} />
              <TextInput value={month} onChangeText={setMonth} placeholder="Mes" keyboardType="number-pad" maxLength={2} style={st.bInput} placeholderTextColor={colors.muted} />
              <Pressable onPress={save} disabled={saving} style={[st.bBtn, saving && { opacity: 0.6 }]} accessibilityRole="button"><Text style={st.bBtnText}>Guardar</Text></Pressable>
            </View>
          </>
        )}
      </View>
    </View>
  );
}

const st = StyleSheet.create({
  tier: { borderRadius: 24, padding: 18, overflow: 'hidden', shadowOpacity: 0.5, shadowRadius: 16, shadowOffset: { width: 0, height: 10 }, elevation: 6 },
  glow: { position: 'absolute', right: -50, top: -70, width: 220, height: 220, borderRadius: 110, opacity: 0.7 },
  medal: { position: 'absolute', right: 16, top: 12, fontSize: 64 },
  small: { fontWeight: '800', fontSize: 11.5, letterSpacing: 1 },
  level: { fontSize: 32, fontWeight: '900', letterSpacing: -0.8, lineHeight: 36 },
  stats: { flexDirection: 'row', gap: 18, marginTop: 10 },
  statN: { fontSize: 19, fontWeight: '900', letterSpacing: -0.3 },
  statT: { fontSize: 11.5, fontWeight: '700' },
  bar: { height: 7, borderRadius: 9, backgroundColor: 'rgba(255,255,255,.5)', marginTop: 12, overflow: 'hidden' },
  barIn: { height: '100%', borderRadius: 9 },
  next: { fontSize: 12.5, fontWeight: '700', marginTop: 8 },
  bday: { flexDirection: 'row', gap: 12, alignItems: 'flex-start', backgroundColor: '#fff', borderRadius: radius.lg, padding: 14, borderWidth: 1, borderColor: colors.line },
  bTitle: { fontSize: 15.5, fontWeight: '800', color: colors.ink },
  bText: { color: colors.muted, fontSize: 13.5 },
  bRow: { flexDirection: 'row', gap: 8, marginTop: 8 },
  bInput: { width: 64, height: 42, borderRadius: 12, backgroundColor: colors.bg, paddingHorizontal: 12, fontSize: 16, color: colors.ink },
  bBtn: { flex: 1, height: 42, borderRadius: 12, backgroundColor: colors.brand, alignItems: 'center', justifyContent: 'center' },
  bBtnText: { color: '#fff', fontWeight: '800' },
});
