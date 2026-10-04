import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { wrapRoot } from '@/lib/monitoring';
import { colors } from '@/lib/theme';
import { SessionProvider } from '@/state/session';

function RootLayout() {
  return (
    <SafeAreaProvider>
      <SessionProvider>
        <StatusBar style="dark" />
        <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.bg } }}>
          <Stack.Screen name="index" />
          <Stack.Screen name="login" options={{ animation: 'fade' }} />
          <Stack.Screen name="earnings" options={{ headerShown: true, title: 'Ganancias', headerStyle: { backgroundColor: '#000' }, headerTintColor: '#fff', headerTitleStyle: { fontWeight: '800' } }} />
          <Stack.Screen name="menu" options={{ presentation: 'transparentModal', animation: 'fade' }} />
        </Stack>
      </SessionProvider>
    </SafeAreaProvider>
  );
}

export default wrapRoot(RootLayout);
