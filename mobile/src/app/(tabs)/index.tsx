import Ionicons from '@expo/vector-icons/Ionicons';
import { Link, router } from 'expo-router';
import { useMemo, useState } from 'react';
import { FlatList, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Empty, ErrorState, Loading, Price, SectionTitle, StoreCard, Thumb, s as ui } from '@/components/ui';
import { api } from '@/lib/api';
import { colors, radius } from '@/lib/theme';
import { useFetch } from '@/lib/useFetch';
import { useApp } from '@/state/app-state';

export default function HomeScreen() {
  const insets = useSafeAreaInsets();
  const { location, ready, city, setCity } = useApp();
  const [rubro, setRubro] = useState<number | null>(null);
  const [pickCity, setPickCity] = useState(false);
  const home = useFetch(() => api.home(location), [location?.lat, location?.lng, city]);
  const config = useFetch(() => api.config(), []);
  const filtered = useFetch(() => (rubro ? api.stores(location, { category_id: rubro }) : Promise.resolve(null)), [rubro, location?.lat, location?.lng, city]);
  const stores = useMemo(() => (rubro ? filtered.data?.stores ?? [] : home.data?.stores ?? []), [rubro, filtered.data, home.data]);

  if (!ready || (home.loading && !home.data)) return <Loading />;
  if (home.error && !home.data) return <ErrorState message={home.error} onRetry={home.reload} />;
  const data = home.data!;

  return (
    <FlatList
      data={stores}
      keyExtractor={st => String(st.id)}
      renderItem={({ item }) => <StoreCard store={item} />}
      contentContainerStyle={{ paddingHorizontal: 16, paddingBottom: 24 }}
      refreshControl={<RefreshControl refreshing={home.refreshing} onRefresh={home.refresh} tintColor={colors.brand} />}
      ListHeaderComponent={
        <View>
          <View style={[st.hero, { paddingTop: insets.top + 12 }]}>
            <Link href="/location" asChild>
              <Pressable style={st.locBtn} accessibilityLabel="Cambiar ubicación">
                <Ionicons name="location" size={18} color="#fff" />
                <Text style={st.locText} numberOfLines={1}>{location ? location.label : 'Elegí dónde recibís tu pedido'}</Text>
                <Ionicons name="chevron-down" size={16} color="#E9DDFF" />
              </Pressable>
            </Link>
            {!!data.cities?.length && data.city && (
              <Pressable style={st.cityBtn} onPress={() => setPickCity(v => !v)} accessibilityLabel="Cambiar de ciudad">
                <Ionicons name="business" size={15} color="#fff" />
                <Text style={st.cityText}>{data.city.name}</Text>
                <Ionicons name={pickCity ? 'chevron-up' : 'chevron-down'} size={14} color="#E9DDFF" />
              </Pressable>
            )}
            {pickCity && (
              <View style={st.cityList}>
                {data.cities!.map(c => (
                  <Pressable key={c.id} onPress={() => { setCity(c.slug); setPickCity(false); }} style={[st.cityChip, data.city?.id === c.id && st.cityChipOn]}>
                    <Text style={[st.cityChipText, data.city?.id === c.id && { color: colors.brand }]}>{c.name}</Text>
                  </Pressable>
                ))}
              </View>
            )}
            <Text style={st.heroTitle}>Pedí lo que quieras.{'\n'}Recibilo en minutos.</Text>
            <Pressable style={st.search} onPress={() => router.navigate('/search')} accessibilityRole="search">
              <Ionicons name="search" size={18} color={colors.muted} />
              <Text style={ui.muted}>Buscá comercios y productos</Text>
            </Pressable>
            {config.data?.ai?.available && (
              <Pressable style={st.ai} onPress={() => router.push('/assistant')} accessibilityRole="button" accessibilityLabel="Abrir Trappi AI">
                <Text style={st.aiText}>✨ Preguntale a Trappi AI</Text>
                <Text style={st.aiSub} numberOfLines={1}>“Buscame hamburguesas cerca”</Text>
              </Pressable>
            )}
          </View>

          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8, paddingVertical: 14 }}>
            <Pressable onPress={() => setRubro(null)} style={[st.rubro, rubro === null && st.rubroOn]}><Text style={[st.rubroText, rubro === null && { color: '#fff' }]}>Todos</Text></Pressable>
            {data.store_categories.map(c => (
              <Pressable key={c.id} onPress={() => setRubro(c.id)} style={[st.rubro, rubro === c.id && st.rubroOn]}>
                <Text style={[st.rubroText, rubro === c.id && { color: '#fff' }]}>{c.emoji} {c.name}</Text>
              </Pressable>
            ))}
          </ScrollView>

          {!location && (
            <Link href="/location" asChild>
              <Pressable style={st.locCta}>
                <Text style={{ fontSize: 22 }}>📍</Text>
                <Text style={{ flex: 1, color: colors.ink }}><Text style={{ fontWeight: '800' }}>¿Dónde estás?</Text> Marcá tu ubicación para ver qué comercios llegan y cuánto sale el envío.</Text>
              </Pressable>
            </Link>
          )}

          {!rubro && data.promos.length > 0 && (
            <>
              <SectionTitle>🔥 Ofertas</SectionTitle>
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 12 }}>
                {data.promos.map(p => (
                  <Pressable key={p.id} style={st.promo} onPress={() => p.store && router.push({ pathname: '/store/[slug]', params: { slug: p.store.slug } })}>
                    <Thumb uri={p.image_url} emoji={p.emoji} hue={p.hue} style={{ height: 100 }} />
                    <View style={{ padding: 10, gap: 2 }}>
                      <Text style={{ fontWeight: '700', color: colors.ink }} numberOfLines={1}>{p.name}</Text>
                      <Text style={ui.muted} numberOfLines={1}>{p.store?.name}</Text>
                      <Price price={p.price} previous={p.previous_price} />
                    </View>
                  </Pressable>
                ))}
              </ScrollView>
            </>
          )}
          <SectionTitle>{rubro ? data.store_categories.find(c => c.id === rubro)?.name : 'Comercios en tu zona'}</SectionTitle>
          {rubro && filtered.loading && <Loading />}
        </View>
      }
      ListEmptyComponent={rubro && filtered.loading ? null : <Empty emoji="🏪" title="Todavía no hay comercios acá" text="Probá con otro rubro o volvé más tarde." />}
    />
  );
}

const st = StyleSheet.create({
  ai: { marginTop: 10, backgroundColor: 'rgba(255,255,255,0.16)', borderRadius: radius.md, paddingHorizontal: 14, paddingVertical: 10, borderWidth: 1, borderColor: 'rgba(255,255,255,0.35)' },
  aiText: { color: '#fff', fontWeight: '800', fontSize: 15.5 },
  aiSub: { color: '#E9DDFF', fontSize: 13, marginTop: 2 },
  hero: { backgroundColor: colors.brand, marginHorizontal: -16, paddingHorizontal: 16, paddingBottom: 20, borderBottomLeftRadius: 28, borderBottomRightRadius: 28, gap: 14 },
  locBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, alignSelf: 'flex-start', maxWidth: '100%', backgroundColor: 'rgba(255,255,255,.16)', paddingHorizontal: 12, paddingVertical: 8, borderRadius: radius.pill },
  locText: { color: '#fff', fontWeight: '700', flexShrink: 1 },
  cityBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, alignSelf: 'flex-start', marginTop: 8, paddingHorizontal: 10, paddingVertical: 5, borderRadius: radius.pill, borderWidth: 1, borderColor: 'rgba(255,255,255,.35)' },
  cityText: { color: '#fff', fontWeight: '700', fontSize: 13 },
  cityList: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 8 },
  cityChip: { paddingHorizontal: 12, paddingVertical: 7, borderRadius: radius.pill, backgroundColor: 'rgba(255,255,255,.16)' },
  cityChipOn: { backgroundColor: '#fff' },
  cityChipText: { color: '#fff', fontWeight: '700' },
  heroTitle: { color: '#fff', fontSize: 28, fontWeight: '800', lineHeight: 32, letterSpacing: -0.6 },
  search: { flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: '#fff', borderRadius: radius.pill, paddingHorizontal: 16, paddingVertical: 13 },
  rubro: { paddingHorizontal: 14, paddingVertical: 9, borderRadius: radius.pill, backgroundColor: '#fff', borderWidth: 1, borderColor: colors.line },
  rubroOn: { backgroundColor: colors.brand, borderColor: colors.brand },
  rubroText: { fontWeight: '700', color: colors.ink },
  locCta: { flexDirection: 'row', gap: 10, alignItems: 'center', padding: 14, borderRadius: radius.md, backgroundColor: colors.brandSoft, borderWidth: 1, borderColor: '#D8C7FA', borderStyle: 'dashed' },
  promo: { width: 170, backgroundColor: '#fff', borderRadius: radius.md, overflow: 'hidden', borderWidth: 1, borderColor: colors.line },
});
