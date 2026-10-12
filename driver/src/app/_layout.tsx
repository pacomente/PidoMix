import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { wrapRoot } from '@/lib/monitoring';
import { colors } from '@/lib/theme';
import { ConfigGate } from '@/state/config';
import { SessionProvider } from '@/state/session';

function RootLayout() {
  return (
    <SafeAreaProvider>
      <StatusBar style="dark" />
      <ConfigGate>
        <SessionProvider>
          <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.bg } }}>
            <Stack.Screen name="index" />
            <Stack.Screen name="login" options={{ animation: 'fade' }} />
            <Stack.Screen name="earnings" options={{ headerShown: true, title: 'Ganancias', headerStyle: { backgroundColor: '#000' }, headerTintColor: '#fff', headerTitleStyle: { fontWeight: '800' } }} />
            <Stack.Screen name="caja" options={{ headerShown: true, title: 'Mi caja', headerStyle: { backgroundColor: '#000' }, headerTintColor: '#fff', headerTitleStyle: { fontWeight: '800' } }} />
            <Stack.Screen name="menu" options={{ presentation: 'transparentModal', animation: 'fade' }} />
          </Stack>
        </SessionProvider>
      </ConfigGate>
    </SafeAreaProvider>
  );
}

export default wrapRoot(RootLayout);
