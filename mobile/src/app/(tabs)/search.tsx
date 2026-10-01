import Ionicons from '@expo/vector-icons/Ionicons';
import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { ScrollView, StyleSheet, TextInput, View } from 'react-native';

import { Empty, ErrorState, Loading, ProductRow, SectionTitle, StoreCard } from '@/components/ui';
import { api } from '@/lib/api';
import { colors, radius } from '@/lib/theme';
import type { Product, Store } from '@/lib/types';
import { useApp } from '@/state/app-state';

export default function SearchScreen() {
  const { location } = useApp();
  const [q, setQ] = useState('');
  const [found, setResult] = useState<{ stores: Store[]; products: Product[] } | null>(null);
  const [failed, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [attempt, setAttempt] = useState(0);

  // búsqueda con espera corta para no consultar en cada tecla
  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) return;
    let alive = true;
    const t = setTimeout(() => {
      setLoading(true);
      api.search(term, location)
        .then(r => { if (alive) { setResult(r); setError(null); } })
        .catch(e => { if (alive) setError(e.message); })
        .finally(() => { if (alive) setLoading(false); });
    }, 300);
    return () => { alive = false; clearTimeout(t); };
  }, [q, location, attempt]);

  // con menos de 2 letras no se busca y no se muestra un resultado viejo
  const active = q.trim().length >= 2;
  const result = active ? found : null;
  const error = active ? failed : null;
  const empty = result && !result.stores.length && !result.products.length;

  return (
    <ScrollView style={{ backgroundColor: colors.bg }} contentContainerStyle={{ padding: 16, paddingBottom: 32 }} keyboardShouldPersistTaps="handled">
      <View style={st.box}>
        <Ionicons name="search" size={18} color={colors.muted} />
        <TextInput value={q} onChangeText={setQ} placeholder="Pizza, helado, farmacia…" placeholderTextColor={colors.muted} style={st.input}
          autoFocus returnKeyType="search" autoCorrect={false} clearButtonMode="while-editing" accessibilityLabel="Buscar" />
      </View>
      {active && loading && !result && <Loading />}
      {error && <ErrorState message={error} onRetry={() => setAttempt(a => a + 1)} />}
      {!active && <Empty emoji="🔎" title="¿Qué tenés ganas de pedir?" text="Buscá por comercio, producto o rubro." />}
      {empty && <Empty emoji="🤷" title="No encontramos nada" text={`Nada coincide con "${q.trim()}". Probá con otra palabra.`} />}
      {!!result?.stores.length && (<><SectionTitle>Comercios</SectionTitle>{result.stores.map(s => <StoreCard key={s.id} store={s} />)}</>)}
      {!!result?.products.length && (
        <>
          <SectionTitle>Productos</SectionTitle>
          {result.products.map(p => (
            <ProductRow key={p.id} product={{ ...p, description: p.store ? `en ${p.store.name}` : p.description }} disabled={p.sold_out}
              onAdd={() => router.push({ pathname: '/product/[id]', params: { id: String(p.id) } })} />
          ))}
        </>
      )}
    </ScrollView>
  );
}

const st = StyleSheet.create({
  box: { flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: '#fff', borderRadius: radius.pill, paddingHorizontal: 16, borderWidth: 1, borderColor: colors.line },
  input: { flex: 1, paddingVertical: 13, fontSize: 16, color: colors.ink },
});
