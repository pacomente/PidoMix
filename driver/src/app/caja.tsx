import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, FlatList, RefreshControl, StyleSheet, Text, View } from 'react-native';

import { api } from '@/lib/api';
import { money, timeOf } from '@/lib/format';
import { colors, radius } from '@/lib/theme';
import type { CashBox } from '@/lib/types';

const KIND: Record<string, string> = { cash_collected: 'Cobrado', remittance_difference: 'Diferencia de rendición', adjustment: 'Ajuste' };

/** Mi caja: efectivo cobrado, rendido y pendiente. Solo lectura: lo calcula Trappi. */
export default function Caja() {
  const [data, setData] = useState<CashBox | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const loadData = useCallback(async () => {
    try { setData(await api.cashBox()); setError(null); } catch (e) { setError(e instanceof Error ? e.message : 'No pudimos cargar tu caja.'); }
  }, []);
  // cargar de la API al abrir la pantalla
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { loadData(); }, [loadData]);

  if (!data) return <View style={st.center}>{error ? <Text style={st.muted}>{error}</Text> : <ActivityIndicator color="#fff" />}</View>;
  if (data.own_store) return <View style={st.center}><Text style={st.muted}>Sos repartidor de un local: el efectivo lo rendís directamente al local.</Text></View>;
  const pct = data.limit > 0 ? Math.max(0, Math.min(1, data.pending / data.limit)) : 0;
  return (
    <FlatList
      style={{ backgroundColor: '#000' }}
      contentContainerStyle={{ padding: 16, paddingBottom: 40 }}
      data={data.movements}
      keyExtractor={m => String(m.id)}
      refreshControl={<RefreshControl refreshing={refreshing} tintColor="#fff" onRefresh={async () => { setRefreshing(true); await loadData(); setRefreshing(false); }} />}
      ListHeaderComponent={
        <View style={{ gap: 12, marginBottom: 20 }}>
          <View style={[st.hero, data.blocked && { backgroundColor: '#3A0D08' }]}>
            <Text style={st.heroLabel}>{data.pending < 0 ? 'Trappi te debe (pusiste plata de tu bolsillo)' : 'Efectivo pendiente de rendir'}</Text>
            <Text style={st.heroValue}>{money(Math.abs(data.pending))}</Text>
            {data.pending < 0 && <Text style={st.heroSub}>Le pagaste al local y todavía no cobraste al cliente: se compensa cuando cobrás.</Text>}
            <View style={st.bar}><View style={[st.barFill, { width: `${pct * 100}%` }, pct >= 0.9 && { backgroundColor: colors.danger }]} /></View>
            <Text style={st.heroSub}>Límite {money(data.limit)} · disponible {money(data.available)}</Text>
            {data.blocked && <Text style={st.blocked}>BLOQUEADO PARA PEDIDOS EN EFECTIVO{data.online_orders_enabled ? '\nSeguís recibiendo pedidos pagados online.' : ''}</Text>}
          </View>
          <View style={{ flexDirection: 'row', gap: 12 }}>
            <View style={st.box}><Text style={st.boxLabel}>Cobrado</Text><Text style={st.boxValue}>{money(data.collected)}</Text></View>
            <View style={st.box}><Text style={st.boxLabel}>Rendido</Text><Text style={st.boxValue}>{money(data.remitted)}</Text></View>
          </View>
          <View style={{ flexDirection: 'row', gap: 12 }}>
            <View style={st.box}><Text style={st.boxLabel}>Diferencias</Text><Text style={[st.boxValue, data.differences < 0 && { color: colors.danger }]}>{money(data.differences)}</Text></View>
            <View style={st.box}><Text style={st.boxLabel}>Ganancias a cobrar</Text><Text style={[st.boxValue, { color: colors.money }]}>{money(data.earnings_pending)}</Text></View>
          </View>
          <Text style={st.muted}>Estos valores los calcula Trappi a partir de tus entregas y rendiciones. Si ves algo raro, avisá al administrador.</Text>
          <Text style={st.section}>Movimientos</Text>
        </View>
      }
      ListEmptyComponent={<Text style={[st.muted, { textAlign: 'center', marginTop: 20 }]}>Todavía no cobraste efectivo.</Text>}
      renderItem={({ item }) => (
        <View style={st.row}>
          <View style={{ flex: 1 }}>
            <Text style={st.rowTitle}>{item.order_id ? `Pedido #${item.order_id}` : KIND[item.kind] || item.kind}</Text>
            <Text style={st.muted}>{timeOf(item.at)} · {item.settled ? 'rendido' : 'pendiente'}</Text>
          </View>
          <Text style={[st.rowMoney, item.amount < 0 && { color: colors.money }]}>{money(item.amount)}</Text>
        </View>
      )}
    />
  );
}

const st = StyleSheet.create({
  center: { flex: 1, backgroundColor: '#000', alignItems: 'center', justifyContent: 'center', padding: 24 },
  muted: { color: '#9A9A9A', fontSize: 13.5 },
  hero: { backgroundColor: colors.dark, borderRadius: radius.md, padding: 20, alignItems: 'center', gap: 4 },
  heroLabel: { color: '#BBB', fontWeight: '700' },
  heroValue: { color: '#fff', fontSize: 40, fontWeight: '900' },
  heroSub: { color: '#BBB' },
  bar: { alignSelf: 'stretch', height: 8, borderRadius: 4, backgroundColor: '#333', overflow: 'hidden', marginVertical: 6 },
  barFill: { height: 8, backgroundColor: colors.money },
  blocked: { color: '#FF8A7A', fontWeight: '900', textAlign: 'center', marginTop: 8 },
  box: { flex: 1, backgroundColor: colors.dark, borderRadius: radius.md, padding: 14, gap: 2 },
  boxLabel: { color: '#BBB', fontWeight: '700' },
  boxValue: { color: '#fff', fontSize: 22, fontWeight: '900' },
  section: { color: '#fff', fontSize: 18, fontWeight: '900', marginTop: 6 },
  row: { flexDirection: 'row', alignItems: 'center', paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: '#1d1d1d' },
  rowTitle: { color: '#fff', fontWeight: '800' },
  rowMoney: { color: '#fff', fontWeight: '900', fontSize: 16 },
});
