import Ionicons from '@expo/vector-icons/Ionicons';
import { Tabs } from 'expo-router/js-tabs';
import type { ColorValue } from 'react-native';

import { colors } from '@/lib/theme';
import { useApp } from '@/state/app-state';

type IconName = React.ComponentProps<typeof Ionicons>['name'];
const icon = (name: IconName) => {
  const TabIcon = ({ color, size }: { color: ColorValue; size: number }) => <Ionicons name={name} size={size} color={color} />;
  return TabIcon;
};

export default function TabsLayout() {
  const { cartCount } = useApp();
  return (
    <Tabs screenOptions={{ tabBarActiveTintColor: colors.brand, tabBarInactiveTintColor: colors.muted, headerTitleStyle: { fontWeight: '800', color: colors.ink }, tabBarLabelStyle: { fontWeight: '700' } }}>
      <Tabs.Screen name="index" options={{ title: 'Inicio', headerShown: false, tabBarIcon: icon('home') }} />
      <Tabs.Screen name="search" options={{ title: 'Buscar', tabBarIcon: icon('search') }} />
      <Tabs.Screen name="orders" options={{ title: 'Mis pedidos', tabBarIcon: icon('receipt') }} />
      <Tabs.Screen name="cart" options={{ title: 'Mi pedido', tabBarIcon: icon('bag-handle'), tabBarBadge: cartCount || undefined, tabBarBadgeStyle: { backgroundColor: colors.brand } }} />
      <Tabs.Screen name="account" options={{ title: 'Cuenta', tabBarIcon: icon('person-circle') }} />
    </Tabs>
  );
}
