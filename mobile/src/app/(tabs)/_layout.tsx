import { Tabs } from 'expo-router/js-tabs';

import { Ill } from '@/components/kit';
import { colors } from '@/lib/theme';

// íconos 3D: la pestaña elegida a color, las otras más tenues
const icon = (e: string) => {
  const TabIcon = ({ focused }: { focused: boolean }) => <Ill e={e} size={26} style={{ opacity: focused ? 1 : 0.42 }} />;
  return TabIcon;
};

export default function TabsLayout() {
  return (
    <Tabs screenOptions={{ tabBarActiveTintColor: colors.brand, tabBarInactiveTintColor: '#9A93A8', headerTitleStyle: { fontWeight: '800', color: colors.ink }, headerTitleAlign: 'center',
      tabBarLabelStyle: { fontWeight: '800', fontSize: 11.5 }, tabBarStyle: { height: 68, paddingTop: 7, paddingBottom: 9, borderTopColor: colors.line, backgroundColor: '#fff' } }}>
      <Tabs.Screen name="index" options={{ title: 'Inicio', headerShown: false, tabBarIcon: icon('🏠') }} />
      <Tabs.Screen name="search" options={{ title: 'Buscar', headerShown: false, tabBarIcon: icon('🔍') }} />
      <Tabs.Screen name="orders" options={{ title: 'Pedidos', headerShown: false, tabBarIcon: icon('📦') }} />
      <Tabs.Screen name="account" options={{ title: 'Cuenta', headerShown: false, tabBarIcon: icon('🏅') }} />
      {/* promos y el carrito se abren desde el inicio (banner, ícono de arriba y la barra «Ver mi pedido») */}
      <Tabs.Screen name="promos" options={{ title: 'Promos', headerShown: false, href: null }} />
      <Tabs.Screen name="cart" options={{ title: 'Tu pedido', href: null, headerShown: false }} />
    </Tabs>
  );
}
