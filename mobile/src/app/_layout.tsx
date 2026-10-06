import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { AppGate } from '@/components/app-gate';
import { NotificationOpener } from '@/components/notification-opener';
import { wrapRoot } from '@/lib/monitoring';
import { colors } from '@/lib/theme';
import { AppStateProvider } from '@/state/app-state';

function RootLayout() {
  return (
    <SafeAreaProvider>
      <AppGate>
        <AppStateProvider>
          <StatusBar style="dark" />
          <NotificationOpener />
          <Stack screenOptions={{ headerTintColor: colors.brand, headerTitleStyle: { color: colors.ink, fontWeight: '800' }, contentStyle: { backgroundColor: colors.bg }, headerBackTitle: 'Volver' }}>
            <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
            <Stack.Screen name="store/[slug]" options={{ title: '' }} />
            <Stack.Screen name="product/[id]" options={{ presentation: 'modal', title: 'Personalizá tu pedido' }} />
            <Stack.Screen name="checkout" options={{ title: 'Finalizar pedido' }} />
            <Stack.Screen name="assistant" options={{ title: '✨ Trappi AI' }} />
            <Stack.Screen name="order/[id]" options={{ title: 'Seguimiento' }} />
            <Stack.Screen name="location" options={{ presentation: 'modal', title: '¿Dónde recibís tu pedido?' }} />
          </Stack>
        </AppStateProvider>
      </AppGate>
    </SafeAreaProvider>
  );
}

export default wrapRoot(RootLayout);
