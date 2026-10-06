import Ionicons from '@expo/vector-icons/Ionicons';
import { Tabs } from 'expo-router/js-tabs';
import type { ColorValue } from 'react-native';

import { colors } from '@/lib/theme';

type IconName = React.ComponentProps<typeof Ionicons>['name'];
const icon = (name: IconName) => {
  const TabIcon = ({ color, size }: { color: ColorValue; size: number }) => <Ionicons name={name} size={size} color={color} />;
  return TabIcon;
};

export default function TabsLayout() {
  return (
    <Tabs screenOptions={{ tabBarActiveTintColor: colors.ink, tabBarInactiveTintColor: colors.muted, headerTitleStyle: { fontWeight: '800', color: colors.ink }, headerTitleAlign: 'center',
      tabBarLabelStyle: { fontWeight: '600', fontSize: 12 }, tabBarStyle: { height: 64, paddingTop: 6, paddingBottom: 8, borderTopColor: colors.line } }}>
      <Tabs.Screen name="index" options={{ title: 'Inicio', headerShown: false, tabBarIcon: icon('home') }} />
      <Tabs.Screen name="search" options={{ title: 'Buscar', headerShown: false, tabBarIcon: icon('search') }} />
      <Tabs.Screen name="promos" options={{ title: 'Promos', headerShown: false, tabBarIcon: icon('pricetags') }} />
      <Tabs.Screen name="orders" options={{ title: 'Pedidos', headerShown: false, tabBarIcon: icon('receipt') }} />
      <Tabs.Screen name="account" options={{ title: 'Mi perfil', tabBarIcon: icon('person') }} />
      {/* el carrito se abre desde el ícono de arriba (y la barra de "Ver mi pedido"); sigue siendo una pestaña oculta */}
      <Tabs.Screen name="cart" options={{ title: 'Mi pedido', href: null }} />
    </Tabs>
  );
}
