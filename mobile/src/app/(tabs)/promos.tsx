import { router } from 'expo-router';
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';

import { BrandHeader, Carousel, ProductTile, Section, StoreRow, StoreTile, Tile } from '@/components/market';
import { Empty, ErrorState, Loading } from '@/components/ui';
import { api } from '@/lib/api';
import { colors } from '@/lib/theme';
import { useFetch } from '@/lib/useFetch';
import { useApp } from '@/state/app-state';

/** Promociones: comercios con descuentos y productos en oferta (con los precios que cargan los comercios). */
export default function PromosScreen() {
  const { location, city } = useApp();
  const home = useFetch(() => api.home(location), [location?.lat, location?.lng, city]);
  if (home.loading && !home.data) return <Loading />;
  if (home.error && !home.data) return <ErrorState message={home.error} onRetry={home.reload} />;
  const d = home.data!;
  const deals = d.stores.filter(s => s.max_discount).sort((a, b) => (b.max_discount ?? 0) - (a.max_discount ?? 0));
  const freeShip = d.stores.filter(s => s.delivery_enabled && s.coverage.cost === 0);

  return (
    <ScrollView style={{ backgroundColor: '#fff' }} contentContainerStyle={{ paddingBottom: 28 }}
      refreshControl={<RefreshControl refreshing={home.refreshing} onRefresh={home.refresh} tintColor={colors.brand} />}>
      <BrandHeader title="Promociones" search={false} />
      <View style={st.tiles}>
        <Tile label="Comercios" icon="storefront-outline" onPress={() => router.navigate('/search')} />
        <Tile label="Mis pedidos" icon="receipt-outline" onPress={() => router.navigate('/orders')} />
        <Tile label="Mi pedido" icon="cart-outline" onPress={() => router.push('/cart')} />
      </View>

      {deals.length > 0 && (
        <Section title="Descubrí las promos más buscadas">
          <Carousel>{deals.map(s => <StoreTile key={s.id} store={s} />)}</Carousel>
        </Section>
      )}
      {d.promos.length > 0 && (
        <Section title="Productos en oferta">
          <Carousel>{d.promos.map(p => <ProductTile key={p.id} product={p} />)}</Carousel>
        </Section>
      )}
      {freeShip.length > 0 && (
        <Section title="Con envío gratis">
          {freeShip.map(s => <StoreRow key={s.id} store={s} />)}
        </Section>
      )}
      {!deals.length && !d.promos.length && !freeShip.length && (
        <View style={{ marginTop: 24 }}>
          <Empty emoji="🏷️" title="Por ahora no hay promociones" text="Cuando los comercios carguen ofertas las vas a ver acá." />
        </View>
      )}
      <Text style={st.fine}>Los descuentos los arma cada comercio con sus precios. El precio final lo ves antes de confirmar.</Text>
    </ScrollView>
  );
}

const st = StyleSheet.create({
  tiles: { flexDirection: 'row', justifyContent: 'space-between', paddingHorizontal: 16, marginTop: 18 },
  fine: { color: colors.muted, fontSize: 13, textAlign: 'center', paddingHorizontal: 24, marginTop: 26 },
});
