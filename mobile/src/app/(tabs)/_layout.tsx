import Ionicons from '@expo/vector-icons/Ionicons';
import { Tabs } from 'expo-router/js-tabs';
import type { ColorValue } from 'react-native';

import { colors } from '@/lib/theme';

type IconName = React.ComponentProps<typeof Ionicons>['name'];
// con la pestaña elegida el ícono va lleno y violeta; las otras, de línea
const icon = (name: IconName) => {
  const TabIcon = ({ color, size, focused }: { color: ColorValue; size: number; focused: boolean }) =>
    <Ionicons name={(focused ? name : `${name}-outline`) as IconName} size={size} color={color} />;
  return TabIcon;
};

export default function TabsLayout() {
  return (
    <Tabs screenOptions={{ tabBarActiveTintColor: colors.brand, tabBarInactiveTintColor: '#9A93A8', headerTitleStyle: { fontWeight: '800', color: colors.ink }, headerTitleAlign: 'center',
      tabBarLabelStyle: { fontWeight: '700', fontSize: 11.5 }, tabBarStyle: { height: 66, paddingTop: 6, paddingBottom: 9, borderTopColor: colors.line, backgroundColor: '#fff' } }}>
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
