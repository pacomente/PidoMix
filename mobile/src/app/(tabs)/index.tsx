import Ionicons from '@expo/vector-icons/Ionicons';
import { Image } from 'expo-image';
import { router } from 'expo-router';
import { useMemo, useState } from 'react';
import { Linking, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';

import { BrandHeader, Carousel, ProductTile, Section, StoreBubble, StoreRow, StoreTile, Tile } from '@/components/market';
import { Empty, ErrorState, Loading } from '@/components/ui';
import { api } from '@/lib/api';
import { colors, radius } from '@/lib/theme';
import type { Home } from '@/lib/types';
import { useFetch } from '@/lib/useFetch';
import { useApp } from '@/state/app-state';

function Banner({ b }: { b: Home['banners'][number] }) {
  const open = () => {
    if (!b.link) return;
    if (b.link.startsWith('/tienda/')) router.push({ pathname: '/store/[slug]', params: { slug: b.link.split('/')[2] } });
    else if (/^https?:/.test(b.link)) Linking.openURL(b.link);
  };
  return (
    <Pressable style={st.banner} onPress={open} disabled={!b.link}>
      {b.image_url && <Image source={{ uri: b.image_url }} style={StyleSheet.absoluteFill} contentFit="cover" />}
      <View style={[StyleSheet.absoluteFill, { backgroundColor: b.image_url ? 'rgba(20,8,45,.35)' : 'transparent' }]} />
      <Text style={st.bannerTitle} numberOfLines={2}>{b.title || 'Descubrí Trappi'}</Text>
      {!!b.subtitle && <Text style={st.bannerSub} numberOfLines={2}>{b.subtitle}</Text>}
      {!!b.button_text && !!b.link && <Text style={st.bannerBtn}>{b.button_text}</Text>}
    </Pressable>
  );
}

export default function HomeScreen() {
  const { location, ready, city, setCity, account } = useApp();
  const [pickCity, setPickCity] = useState(false);
  const home = useFetch(() => api.home(location), [location?.lat, location?.lng, city]);
  const config = useFetch(() => api.config(), []);
  // recomendado para vos: solo con cuenta, con sus propios pedidos (lo calcula el servidor)
  const forYou = useFetch(() => (account && account.personalize !== false ? api.recommendations(location).catch(() => null) : Promise.resolve(null)),
    [account?.id, account?.personalize, location?.lat, location?.lng, city]);

  const data = home.data;
  const sections = useMemo(() => {
    const stores = data?.stores ?? [];
    return {
      deals: stores.filter(s => s.max_discount).sort((a, b) => (b.max_discount ?? 0) - (a.max_discount ?? 0)),
      best: [...stores].filter(s => s.rating !== null).sort((a, b) => (b.rating ?? 0) - (a.rating ?? 0) || b.rating_count - a.rating_count),
      fast: [...stores].filter(s => s.is_open).sort((a, b) => a.eta_min - b.eta_min),
      featured: stores.filter(s => s.featured),
    };
  }, [data]);

  if (!ready || (home.loading && !data)) return <Loading />;
  if (home.error && !data) return <ErrorState message={home.error} onRetry={home.reload} />;
  const d = data!;
  const ai = !!config.data?.ai?.available;
  const goRubro = (id: number, name: string) => router.push({ pathname: '/search', params: { rubro: String(id), rubroName: name } });

  return (
    <ScrollView style={{ backgroundColor: '#fff' }} contentContainerStyle={{ paddingBottom: 28 }}
      refreshControl={<RefreshControl refreshing={home.refreshing} onRefresh={home.refresh} tintColor={colors.brand} />}>
      <BrandHeader>
        {!!d.cities?.length && d.city && (
          <View style={{ gap: 8 }}>
            <Pressable style={st.cityBtn} onPress={() => setPickCity(v => !v)} accessibilityLabel="Cambiar de ciudad">
              <Ionicons name="business-outline" size={15} color="#fff" />
              <Text style={st.cityText}>{d.city.name}</Text>
              <Ionicons name={pickCity ? 'chevron-up' : 'chevron-down'} size={14} color="#fff" />
            </Pressable>
            {pickCity && (
              <View style={st.cityList}>
                {d.cities!.map(c => (
                  <Pressable key={c.id} onPress={() => { setCity(c.slug); setPickCity(false); }} style={[st.cityChip, d.city?.id === c.id && st.cityChipOn]}>
                    <Text style={[st.cityChipText, d.city?.id === c.id && { color: colors.brand }]}>{c.name}</Text>
                  </Pressable>
                ))}
              </View>
            )}
          </View>
        )}
      </BrandHeader>

      {d.banners.length > 0 && (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ paddingHorizontal: 16, gap: 12, paddingTop: 18 }}>
          {d.banners.map(b => <Banner key={b.id} b={b} />)}
        </ScrollView>
      )}

      {!location && (
        <Pressable style={st.locCta} onPress={() => router.push('/location')}>
          <Ionicons name="location" size={22} color={colors.brand} />
          <Text style={{ flex: 1, color: colors.ink }}><Text style={{ fontWeight: '800' }}>¿Dónde recibís el pedido?</Text> Elegí tu dirección para ver qué comercios llegan y cuánto sale el envío.</Text>
          <Ionicons name="chevron-forward" size={18} color={colors.brand} />
        </Pressable>
      )}

      <View style={st.wideRow}>
        <Tile wide label="Comercios" icon="storefront-outline" onPress={() => router.navigate('/search')} />
        {ai ? <Tile wide label="Trappi AI" icon="sparkles-outline" onPress={() => router.push('/assistant')} />
          : <Tile wide label="Promociones" icon="pricetag-outline" onPress={() => router.navigate('/promos')} />}
      </View>

      {!!forYou.data?.items.length && (
        <Section title="Recomendado para vos">
          <Carousel>{forYou.data.items.map(p => <ProductTile key={p.id} product={p} caption={p.reason} />)}</Carousel>
        </Section>
      )}

      {d.store_categories.length > 0 && (
        <View style={{ marginTop: 16 }}>
          <Carousel gap={12}>{d.store_categories.map(c => <Tile key={c.id} label={c.name} emoji={c.emoji} onPress={() => goRubro(c.id, c.name)} />)}</Carousel>
        </View>
      )}

      {sections.deals.length > 0 && (
        <Section title="Aprovechá estos descuentos" action="Ver todo" onAction={() => router.navigate('/promos')}>
          <Carousel>{sections.deals.map(s => <StoreTile key={s.id} store={s} />)}</Carousel>
        </Section>
      )}

      {d.promos.length > 0 && (
        <Section title="Ofertas de hoy" action="Ver todo" onAction={() => router.navigate('/promos')}>
          <Carousel>{d.promos.map(p => <ProductTile key={p.id} product={p} />)}</Carousel>
        </Section>
      )}

      {sections.featured.length > 0 && (
        <Section title="Destacados">
          <Carousel>{sections.featured.map(s => <StoreTile key={s.id} store={s} />)}</Carousel>
        </Section>
      )}

      {sections.best.length > 1 && (
        <Section title="Los más populares">
          <Carousel gap={12}>{sections.best.map(s => <StoreBubble key={s.id} store={s} />)}</Carousel>
        </Section>
      )}

      {!!d.popular?.length && (
        <Section title="Lo más pedido">
          <Carousel>{d.popular.map(p => <ProductTile key={p.id} product={p} />)}</Carousel>
        </Section>
      )}

      {sections.fast.length > 1 && (
        <Section title="Llegan más rápido">
          <Carousel>{sections.fast.slice(0, 8).map(s => <StoreTile key={s.id} store={s} />)}</Carousel>
        </Section>
      )}

      <Section title={location ? 'Comercios cerca tuyo' : `Comercios en ${d.city?.name ?? 'tu zona'}`}>
        {d.stores.length ? d.stores.map(s => <StoreRow key={s.id} store={s} />)
          : <Empty emoji="🏪" title="Todavía no hay comercios acá" text="Muy pronto vas a encontrar los comercios de tu zona." />}
      </Section>
    </ScrollView>
  );
}

const st = StyleSheet.create({
  cityBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, alignSelf: 'flex-start', paddingHorizontal: 10, paddingVertical: 5, borderRadius: radius.pill, backgroundColor: 'rgba(255,255,255,.18)' },
  cityText: { color: '#fff', fontWeight: '700', fontSize: 13 },
  cityList: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  cityChip: { paddingHorizontal: 12, paddingVertical: 7, borderRadius: radius.pill, backgroundColor: 'rgba(255,255,255,.18)' },
  cityChipOn: { backgroundColor: '#fff' },
  cityChipText: { color: '#fff', fontWeight: '700' },
  banner: { width: 320, height: 160, borderRadius: radius.lg, backgroundColor: '#4A1AA0', padding: 18, justifyContent: 'flex-end', overflow: 'hidden' },
  bannerTitle: { color: '#fff', fontSize: 22, fontWeight: '800', lineHeight: 26 },
  bannerSub: { color: '#EADFFF', fontSize: 14, marginTop: 4 },
  bannerBtn: { color: '#fff', fontWeight: '800', marginTop: 8, textDecorationLine: 'underline' },
  locCta: { flexDirection: 'row', gap: 10, alignItems: 'center', marginHorizontal: 16, marginTop: 16, padding: 14, borderRadius: radius.lg, backgroundColor: colors.brandSoft },
  wideRow: { flexDirection: 'row', gap: 12, paddingHorizontal: 16, marginTop: 18 },
});
