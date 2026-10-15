import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { wrapRoot } from '@/lib/monitoring';
import { ConfigGate } from '@/state/config';
import { PrefsProvider, useColors } from '@/state/prefs';
import { SessionProvider } from '@/state/session';

function Screens() {
  const c = useColors();
  const header = { headerShown: true, headerStyle: { backgroundColor: c.bg }, headerTintColor: c.ink, headerTitleStyle: { fontWeight: '800' as const }, headerShadowVisible: false };
  return (
    <>
      <StatusBar style={c.dark ? 'light' : 'dark'} />
      <ConfigGate>
        <SessionProvider>
          <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: c.bg } }}>
            <Stack.Screen name="index" />
            <Stack.Screen name="login" options={{ animation: 'fade' }} />
            <Stack.Screen name="earnings" options={{ ...header, title: 'Ganancias' }} />
            <Stack.Screen name="caja" options={{ ...header, title: 'Mi caja' }} />
            <Stack.Screen name="settings" options={{ ...header, title: 'Ajustes' }} />
            <Stack.Screen name="menu" options={{ presentation: 'transparentModal', animation: 'fade' }} />
          </Stack>
        </SessionProvider>
      </ConfigGate>
    </>
  );
}

function RootLayout() {
  return (
    <SafeAreaProvider>
      <PrefsProvider>
        <Screens />
      </PrefsProvider>
    </SafeAreaProvider>
  );
}

export default wrapRoot(RootLayout);
