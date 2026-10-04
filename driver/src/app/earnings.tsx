import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, FlatList, RefreshControl, StyleSheet, Text, View } from 'react-native';

import { api } from '@/lib/api';
import { km, money, timeOf } from '@/lib/format';
import { colors, radius } from '@/lib/theme';
import type { History } from '@/lib/types';

export default function Earnings() {
  const [data, setData] = useState<History | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const loadData = useCallback(async () => {
    try { setData(await api.earnings()); setError(null); } catch (e) { setError(e instanceof Error ? e.message : 'No pudimos cargar tus ganancias.'); }
  }, []);
  // cargar de la API al abrir la pantalla
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { loadData(); }, [loadData]);

  if (!data) return <View style={st.center}>{error ? <Text style={st.muted}>{error}</Text> : <ActivityIndicator color="#fff" />}</View>;
  return (
    <FlatList
      style={{ backgroundColor: '#000' }}
      contentContainerStyle={{ padding: 16, paddingBottom: 40 }}
      data={data.trips}
      keyExtractor={t => String(t.order_id)}
      refreshControl={<RefreshControl refreshing={refreshing} tintColor="#fff" onRefresh={async () => { setRefreshing(true); await loadData(); setRefreshing(false); }} />}
      ListHeaderComponent={
        <View style={{ gap: 12, marginBottom: 20 }}>
          <View style={st.hero}>
            <Text style={st.heroLabel}>Hoy</Text>
            <Text style={st.heroValue}>{money(data.today)}</Text>
            <Text style={st.heroSub}>{data.trips_today} {data.trips_today === 1 ? 'viaje' : 'viajes'}</Text>
            {!!data.cash_today && <Text style={st.heroSub}>💵 Cobraste {money(data.cash_today)} en efectivo hoy (a rendir al local)</Text>}
          </View>
          <View style={{ flexDirection: 'row', gap: 12 }}>
            <View style={st.box}><Text style={st.boxLabel}>Últimos 7 días</Text><Text style={st.boxValue}>{money(data.week)}</Text><Text style={st.muted}>{data.trips_week} {data.trips_week === 1 ? 'viaje' : 'viajes'}</Text></View>
            <View style={st.box}><Text style={st.boxLabel}>Últimos 30 días</Text><Text style={st.boxValue}>{money(data.month)}</Text><Text style={st.muted}>{data.trips_month} {data.trips_month === 1 ? 'viaje' : 'viajes'}</Text></View>
          </View>
          <Text style={st.section}>Viajes recientes</Text>
        </View>
      }
      ListEmptyComponent={<Text style={[st.muted, { textAlign: 'center', marginTop: 20 }]}>Todavía no hiciste viajes. ¡Conectate para empezar!</Text>}
      renderItem={({ item }) => (
        <View style={st.trip}>
          <View style={{ flex: 1 }}>
            <Text style={st.tripTitle}>{item.store} · #{item.order_id}</Text>
            <Text style={st.muted} numberOfLines={1}>{new Date(item.delivered_at).toLocaleDateString('es-AR')} {timeOf(item.delivered_at)}{item.km ? ` · ${km(item.km)}` : ''} · {item.address || ''}</Text>
          </View>
          <Text style={st.tripMoney}>{money(item.earnings)}</Text>
        </View>
      )}
    />
  );
}

const st = StyleSheet.create({
  center: { flex: 1, backgroundColor: '#000', alignItems: 'center', justifyContent: 'center', padding: 24 },
  muted: { color: '#999', fontSize: 13.5 },
  hero: { backgroundColor: colors.dark, borderRadius: radius.md, padding: 20, alignItems: 'center' },
  heroLabel: { color: '#AAA', fontWeight: '700' },
  heroValue: { color: '#fff', fontSize: 48, fontWeight: '900', letterSpacing: -1 },
  heroSub: { color: colors.money, fontWeight: '800' },
  box: { flex: 1, backgroundColor: colors.dark, borderRadius: radius.md, padding: 14, gap: 2 },
  boxLabel: { color: '#AAA', fontWeight: '700', fontSize: 13 },
  boxValue: { color: '#fff', fontSize: 24, fontWeight: '900' },
  section: { color: '#fff', fontSize: 18, fontWeight: '800', marginTop: 8 },
  trip: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 14, borderBottomWidth: 1, borderBottomColor: '#222' },
  tripTitle: { color: '#fff', fontWeight: '700', fontSize: 15.5 },
  tripMoney: { color: colors.money, fontWeight: '900', fontSize: 17 },
});
