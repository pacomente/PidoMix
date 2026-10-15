import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, RefreshControl, Text, View } from 'react-native';

import { api } from '@/lib/api';
import { money, timeOf } from '@/lib/format';
import { radius, themed } from '@/lib/theme';
import type { CashBox } from '@/lib/types';
import { useColors } from '@/state/prefs';

const KIND: Record<string, string> = { cash_collected: 'Cobrado', paid_to_store: 'Pagado al local', remittance_difference: 'Diferencia de rendición', adjustment: 'Ajuste' };
type Tab = 'moves' | 'remit' | 'settle';
type Row = { id: string; title: string; sub: string; amount: number; tone?: 'good' | 'bad' | 'warn'; extra?: string; extraBad?: boolean };

const dateOf = (iso: string) => `${new Date(iso).toLocaleDateString('es-AR', { day: 'numeric', month: 'short' })} ${timeOf(iso)}`;

/** Mi caja: efectivo cobrado, rendido y pendiente, y lo que Trappi le liquida. Solo lectura: lo calcula Trappi. */
export default function Caja() {
  const c = useColors(), st = useSt(c);
  const [data, setData] = useState<CashBox | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [tab, setTab] = useState<Tab>('moves');
  const loadData = useCallback(async () => {
    try { setData(await api.cashBox()); setError(null); } catch (e) { setError(e instanceof Error ? e.message : 'No pudimos cargar tu caja.'); }
  }, []);
  // cargar de la API al abrir la pantalla
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { loadData(); }, [loadData]);

  if (!data) return <View style={st.center}>{error ? <Text style={st.muted}>{error}</Text> : <ActivityIndicator color={c.ink} />}</View>;
  if (data.own_store) return <View style={st.center}><Text style={[st.muted, { textAlign: 'center' }]}>Sos repartidor de un local: el efectivo lo rendís directamente al local.</Text></View>;
  const pct = data.limit > 0 ? Math.max(0, Math.min(1, data.pending / data.limit)) : 0;

  const rows: Row[] = tab === 'moves'
    ? data.movements.map(m => ({ id: `m${m.id}`, title: m.order_id ? `Pedido #${m.order_id}` : KIND[m.kind] || m.kind, sub: `${dateOf(m.at)} · ${m.settled ? 'rendido' : 'pendiente'}`,
        amount: m.amount, tone: m.amount < 0 ? 'good' : undefined }))
    : tab === 'remit'
      ? (data.remittances ?? []).map(r => ({ id: `r${r.id}`, title: `Rendiste ${money(r.received)}`, sub: dateOf(r.at), amount: r.received,
          extraBad: r.difference < 0, extra: r.difference ? `${r.difference < 0 ? 'Faltante' : 'Sobrante'} de ${money(Math.abs(r.difference))} (esperado ${money(r.expected)})` : 'Sin diferencias' }))
      : (data.settlements ?? []).map(s => ({ id: `s${s.id}`, title: `Liquidación · ${s.status_label}`, sub: `${dateOf(s.paid_at || s.at)} · ${s.trips} ${s.trips === 1 ? 'viaje' : 'viajes'}${s.account ? ` · a ${s.account}` : ''}`,
          amount: s.total, tone: s.status === 'paid' ? 'good' : s.status === 'failed' || s.status === 'cancelled' ? 'bad' : 'warn',
          extra: [`Viajes ${money(s.earnings)}`, s.bonuses ? `bonos ${money(s.bonuses)}` : '', s.adjustments ? `ajustes ${money(s.adjustments)}` : '', s.cash_offset ? `menos efectivo sin rendir ${money(s.cash_offset)}` : ''].filter(Boolean).join(' · ') }));
  const empty = tab === 'moves' ? 'Todavía no cobraste efectivo.' : tab === 'remit' ? 'Todavía no tenés rendiciones.' : 'Todavía no tenés liquidaciones.';

  return (
    <FlatList
      style={{ backgroundColor: c.bg }}
      contentContainerStyle={{ padding: 16, paddingBottom: 40 }}
      data={rows}
      keyExtractor={r => r.id}
      refreshControl={<RefreshControl refreshing={refreshing} tintColor={c.ink} onRefresh={async () => { setRefreshing(true); await loadData(); setRefreshing(false); }} />}
      ListHeaderComponent={
        <View style={{ gap: 12, marginBottom: 14 }}>
          <View style={[st.hero, data.blocked && { backgroundColor: c.hotBg }]}>
            <Text style={st.heroLabel}>{data.pending < 0 ? 'Trappi te debe (pusiste plata de tu bolsillo)' : 'Efectivo pendiente de rendir'}</Text>
            <Text style={st.heroValue}>{money(Math.abs(data.pending))}</Text>
            {data.pending < 0 && <Text style={st.heroSub}>Le pagaste al local y todavía no cobraste al cliente: se compensa cuando cobrás.</Text>}
            <View style={st.bar}><View style={[st.barFill, { width: `${pct * 100}%` }, pct >= 0.9 && { backgroundColor: c.danger }]} /></View>
            <Text style={st.heroSub}>Límite {money(data.limit)} · disponible {money(data.available)}</Text>
            {data.blocked && <Text style={st.blocked}>BLOQUEADO PARA PEDIDOS EN EFECTIVO{data.online_orders_enabled ? '\nSeguís recibiendo pedidos pagados online.' : ''}</Text>}
          </View>
          <View style={{ flexDirection: 'row', gap: 12 }}>
            <View style={st.box}><Text style={st.boxLabel}>Ganancias a cobrar</Text><Text style={[st.boxValue, { color: c.moneyText }]}>{money(data.earnings_pending)}</Text></View>
            <View style={st.box}><Text style={st.boxLabel}>Ya te pagamos</Text><Text style={st.boxValue}>{money(data.earnings_paid)}</Text></View>
          </View>
          <View style={{ flexDirection: 'row', gap: 12 }}>
            <View style={st.box}><Text style={st.boxLabel}>Cobrado</Text><Text style={st.boxValue}>{money(data.collected)}</Text></View>
            <View style={st.box}><Text style={st.boxLabel}>Rendido</Text><Text style={st.boxValue}>{money(data.remitted)}</Text></View>
            <View style={st.box}><Text style={st.boxLabel}>Diferencias</Text><Text style={[st.boxValue, data.differences < 0 && { color: c.dangerText }]}>{money(data.differences)}</Text></View>
          </View>
          <Text style={st.muted}>Estos valores los calcula Trappi a partir de tus entregas y rendiciones. Si ves algo raro, avisá al administrador.</Text>
          <View style={st.tabs}>
            {([['moves', 'Movimientos'], ['remit', 'Rendiciones'], ['settle', 'Liquidaciones']] as const).map(([k, l]) => (
              <Pressable key={k} onPress={() => setTab(k)} style={[st.tab, tab === k && st.tabOn]} accessibilityRole="tab" accessibilityState={{ selected: tab === k }}>
                <Text style={[st.tabText, tab === k && st.tabTextOn]}>{l}</Text>
              </Pressable>
            ))}
          </View>
        </View>
      }
      ListEmptyComponent={<Text style={[st.muted, { textAlign: 'center', marginTop: 20 }]}>{empty}</Text>}
      renderItem={({ item }) => (
        <View style={st.row}>
          <View style={{ flex: 1, gap: 2 }}>
            <Text style={st.rowTitle}>{item.title}</Text>
            <Text style={st.muted}>{item.sub}</Text>
            {!!item.extra && <Text style={[st.extra, item.extraBad && { color: c.dangerText }]}>{item.extra}</Text>}
          </View>
          <Text style={[st.rowMoney, item.tone === 'good' && { color: c.moneyText }, item.tone === 'bad' && { color: c.dangerText }, item.tone === 'warn' && { color: c.cashText }]}>{money(item.amount)}</Text>
        </View>
      )}
    />
  );
}

const useSt = themed(c => ({
  center: { flex: 1, backgroundColor: c.bg, alignItems: 'center', justifyContent: 'center', padding: 24 },
  muted: { color: c.muted, fontSize: 13.5 },
  hero: { backgroundColor: c.card, borderRadius: radius.md, padding: 20, alignItems: 'center', gap: 4 },
  heroLabel: { color: c.muted, fontWeight: '700', textAlign: 'center' },
  heroValue: { color: c.ink, fontSize: 40, fontWeight: '900', fontVariant: ['tabular-nums'] },
  heroSub: { color: c.muted, textAlign: 'center' },
  bar: { alignSelf: 'stretch', height: 8, borderRadius: 4, backgroundColor: c.card2, overflow: 'hidden', marginVertical: 6 },
  barFill: { height: 8, backgroundColor: c.money },
  blocked: { color: c.dangerText, fontWeight: '900', textAlign: 'center', marginTop: 8 },
  box: { flex: 1, backgroundColor: c.card, borderRadius: radius.md, padding: 14, gap: 2 },
  boxLabel: { color: c.muted, fontWeight: '700', fontSize: 12.5 },
  boxValue: { color: c.ink, fontSize: 19, fontWeight: '900' },
  tabs: { flexDirection: 'row', backgroundColor: c.card2, borderRadius: radius.pill, padding: 4, marginTop: 4 },
  tab: { flex: 1, paddingVertical: 9, borderRadius: radius.pill, alignItems: 'center' },
  tabOn: { backgroundColor: c.inverse },
  tabText: { color: c.muted, fontWeight: '800', fontSize: 13.5 },
  tabTextOn: { color: c.onInverse },
  row: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: c.line },
  rowTitle: { color: c.ink, fontWeight: '800' },
  rowMoney: { color: c.ink, fontWeight: '900', fontSize: 16 },
  extra: { color: c.muted, fontSize: 12.5, fontWeight: '600' },
}));
