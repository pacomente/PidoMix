import Ionicons from '@expo/vector-icons/Ionicons';
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, RefreshControl, Text, View } from 'react-native';

import { api } from '@/lib/api';
import { km, money, timeOf } from '@/lib/format';
import { radius, themed, type Palette } from '@/lib/theme';
import type { History } from '@/lib/types';
import { useColors } from '@/state/prefs';

type Period = 'today' | 'week' | 'month';
type Day = NonNullable<History['days']>[number];
type St = ReturnType<typeof useSt>;
const CHART_H = 120;

/** fecha local (Argentina) de un viaje, igual que la del gráfico */
const localDate = (iso: string) => {
  const d = new Date(new Date(iso).getTime() - 3 * 3600_000);  // Argentina no tiene horario de verano
  return d.toISOString().slice(0, 10);
};

/** Barras de lo ganado por día. Tocar una barra muestra su valor y filtra los viajes de ese día. */
function DayChart({ days, picked, onPick, st, c }: { days: Day[]; picked: string | null; onPick: (d: string | null) => void; st: St; c: Palette }) {
  const max = Math.max(1, ...days.map(d => d.earnings));
  const sel = days.find(d => d.date === picked);
  const name = (d: Day) => (d.date === days[days.length - 1].date ? 'hoy' : d.label);
  return (
    <View style={st.chartCard}>
      <View style={st.chartHead}>
        <Text style={st.chartTitle}>Últimos 7 días</Text>
        <Text style={st.chartValue}>{sel ? `${name(sel)} · ${money(sel.earnings)} · ${sel.trips} ${sel.trips === 1 ? 'viaje' : 'viajes'}` : 'Tocá un día para ver el detalle'}</Text>
      </View>
      <View style={st.chart}>
        {days.map((d, i) => {
          const h = d.earnings > 0 ? Math.max(4, (d.earnings / max) * CHART_H) : 0;
          const on = d.date === picked, today = i === days.length - 1;
          return (
            <Pressable key={d.date} style={st.col} onPress={() => onPick(on ? null : d.date)} hitSlop={4}
              accessibilityRole="button" accessibilityLabel={`${d.label}: ${money(d.earnings)}, ${d.trips} viajes`} accessibilityState={{ selected: on }}>
              <View style={[st.colArea, on && st.colOn]}>
                {h > 0
                  ? <View style={[st.barFill, { height: h, backgroundColor: c.chart, opacity: picked && !on ? 0.45 : 1 }]} />
                  : <View style={st.barZero} />}
              </View>
              <Text style={[st.colLabel, (on || (today && !picked)) && st.colLabelOn]}>{name(d)}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

export default function Earnings() {
  const c = useColors(), st = useSt(c);
  const [data, setData] = useState<History | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [period, setPeriod] = useState<Period>('today');
  const [picked, setPicked] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const loadData = useCallback(async () => {
    try { setData(await api.earnings()); setError(null); } catch (e) { setError(e instanceof Error ? e.message : 'No pudimos cargar tus ganancias.'); }
  }, []);
  // cargar de la API al abrir la pantalla
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { loadData(); }, [loadData]);

  if (!data) return <View style={st.center}>{error ? <Text style={st.muted}>{error}</Text> : <ActivityIndicator color={c.ink} />}</View>;
  const hero = period === 'today' ? { v: data.today, n: data.trips_today, l: 'Hoy' }
    : period === 'week' ? { v: data.week, n: data.trips_week, l: 'Últimos 7 días' } : { v: data.month, n: data.trips_month, l: 'Últimos 30 días' };
  const trips = picked ? data.trips.filter(t => localDate(t.delivered_at) === picked) : data.trips;

  return (
    <FlatList
      style={{ backgroundColor: c.bg }}
      contentContainerStyle={{ padding: 16, paddingBottom: 40 }}
      data={trips}
      keyExtractor={t => String(t.order_id)}
      refreshControl={<RefreshControl refreshing={refreshing} tintColor={c.ink} onRefresh={async () => { setRefreshing(true); await loadData(); setRefreshing(false); }} />}
      ListHeaderComponent={
        <View style={{ gap: 12, marginBottom: 14 }}>
          <View style={st.tabs}>
            {([['today', 'Hoy'], ['week', '7 días'], ['month', '30 días']] as const).map(([k, l]) => (
              <Pressable key={k} onPress={() => setPeriod(k)} style={[st.tab, period === k && st.tabOn]} accessibilityRole="tab" accessibilityState={{ selected: period === k }}>
                <Text style={[st.tabText, period === k && st.tabTextOn]}>{l}</Text>
              </Pressable>
            ))}
          </View>
          <View style={st.hero}>
            <Text style={st.heroLabel}>{hero.l}</Text>
            <Text style={st.heroValue}>{money(hero.v)}</Text>
            <Text style={st.heroSub}>{hero.n} {hero.n === 1 ? 'viaje' : 'viajes'}{hero.n > 0 ? ` · promedio ${money(hero.v / hero.n)} por viaje` : ''}</Text>
            {period === 'today' && !!data.cash_today && <Text style={st.heroCash}>💵 Cobraste {money(data.cash_today)} en efectivo hoy</Text>}
          </View>
          {!!data.days?.length && <DayChart days={data.days} picked={picked} onPick={setPicked} st={st} c={c} />}
          <View style={st.sectionRow}>
            <Text style={st.section}>{!picked ? 'Viajes recientes' : picked === data.days?.[data.days.length - 1]?.date ? 'Viajes de hoy' : `Viajes del ${data.days?.find(d => d.date === picked)?.label ?? 'día'}`}</Text>
            {picked && <Pressable onPress={() => setPicked(null)} hitSlop={8}><Text style={st.clear}>Ver todos</Text></Pressable>}
          </View>
        </View>
      }
      ListEmptyComponent={<Text style={[st.muted, { textAlign: 'center', marginTop: 20 }]}>{picked ? 'Ese día no hiciste viajes.' : 'Todavía no hiciste viajes. ¡Conectate para empezar!'}</Text>}
      renderItem={({ item }) => {
        const isOpen = open === item.order_id, lines = item.payout?.lines ?? [];
        return (
          <Pressable style={st.trip} onPress={() => setOpen(isOpen ? null : item.order_id)} disabled={!lines.length}
            accessibilityRole="button" accessibilityLabel={`Pedido ${item.order_id}, ${money(item.earnings)}`}>
            <View style={st.tripRow}>
              <View style={{ flex: 1 }}>
                <Text style={st.tripTitle}>{item.store} · #{item.order_id}</Text>
                <Text style={st.muted} numberOfLines={1}>{new Date(item.delivered_at).toLocaleDateString('es-AR', { day: 'numeric', month: 'short' })} {timeOf(item.delivered_at)}{item.km ? ` · ${km(item.km)}` : ''} · {item.address || ''}</Text>
              </View>
              <Text style={st.tripMoney}>{money(item.earnings)}</Text>
              {!!lines.length && <Ionicons name={isOpen ? 'chevron-up' : 'chevron-down'} size={16} color={c.muted} />}
            </View>
            {isOpen && (
              <View style={st.breakdown}>
                {lines.map((l, i) => <View key={i} style={st.bLine}><Text style={st.muted}>{l.label}</Text><Text style={st.bAmt}>{money(l.amount)}</Text></View>)}
              </View>
            )}
          </Pressable>
        );
      }}
    />
  );
}

const useSt = themed(c => ({
  center: { flex: 1, backgroundColor: c.bg, alignItems: 'center', justifyContent: 'center', padding: 24 },
  muted: { color: c.muted, fontSize: 13.5 },
  tabs: { flexDirection: 'row', backgroundColor: c.card2, borderRadius: radius.pill, padding: 4 },
  tab: { flex: 1, paddingVertical: 9, borderRadius: radius.pill, alignItems: 'center' },
  tabOn: { backgroundColor: c.inverse },
  tabText: { color: c.muted, fontWeight: '800' },
  tabTextOn: { color: c.onInverse },
  hero: { backgroundColor: c.card, borderRadius: radius.md, padding: 20, alignItems: 'center', gap: 2 },
  heroLabel: { color: c.muted, fontWeight: '700' },
  heroValue: { color: c.ink, fontSize: 48, fontWeight: '900', letterSpacing: -1, fontVariant: ['tabular-nums'] },
  heroSub: { color: c.muted, fontWeight: '700' },
  heroCash: { color: c.cashText, fontWeight: '800', marginTop: 4 },
  chartCard: { backgroundColor: c.card, borderRadius: radius.md, padding: 16, gap: 12 },
  chartHead: { gap: 2 },
  chartTitle: { color: c.ink, fontWeight: '900', fontSize: 16 },
  chartValue: { color: c.muted, fontWeight: '600', fontSize: 13 },
  chart: { flexDirection: 'row', alignItems: 'flex-end', gap: 2 },
  col: { flex: 1, alignItems: 'center', gap: 6 },
  colArea: { height: CHART_H, alignSelf: 'stretch', justifyContent: 'flex-end', alignItems: 'center', borderRadius: 6, borderBottomWidth: 1, borderBottomColor: c.line },
  colOn: { backgroundColor: c.card2 },
  barFill: { width: '62%', borderTopLeftRadius: 4, borderTopRightRadius: 4 },
  barZero: { width: '62%', height: 2, backgroundColor: c.line },
  colLabel: { color: c.muted, fontSize: 12, fontWeight: '600' },
  colLabelOn: { color: c.ink, fontWeight: '900' },
  sectionRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 4 },
  section: { color: c.ink, fontSize: 18, fontWeight: '900' },
  clear: { color: c.go, fontWeight: '800' },
  trip: { paddingVertical: 14, borderBottomWidth: 1, borderBottomColor: c.line },
  tripRow: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  tripTitle: { color: c.ink, fontWeight: '700', fontSize: 15.5 },
  tripMoney: { color: c.moneyText, fontWeight: '900', fontSize: 17 },
  breakdown: { marginTop: 10, backgroundColor: c.card, borderRadius: radius.sm, padding: 12, gap: 6 },
  bLine: { flexDirection: 'row', justifyContent: 'space-between' },
  bAmt: { color: c.ink, fontWeight: '800' },
}));
