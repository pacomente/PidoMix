import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { AppState, Linking, StyleSheet, Text, View } from 'react-native';

import { Button } from '@/components/ui';
import { api, onMaintenance, type AppConfig } from '@/lib/api';
import { colors } from '@/lib/theme';
import { APP_VERSION, isOutdated } from '@/lib/version';

const CHECK_EVERY_MS = 2 * 60 * 1000;

/**
 * Lo que configura el superadmin: si la app está apagada por mantenimiento se muestra el aviso,
 * y si la versión instalada es más vieja que la mínima, se pide actualizar. Se revisa al abrir,
 * al volver a la app y cada 2 minutos.
 */
export function AppGate({ children }: { children: ReactNode }) {
  const [cfg, setCfg] = useState<AppConfig | null>(null);
  const check = useCallback(() => { api.config().then(setCfg).catch(() => {}); }, []);

  useEffect(() => {
    check();
    const t = setInterval(check, CHECK_EVERY_MS);
    const sub = AppState.addEventListener('change', s => s === 'active' && check());
    const off = onMaintenance(check);
    return () => { clearInterval(t); sub.remove(); off(); };
  }, [check]);

  if (cfg && !cfg.app.enabled) {
    return (
      <View style={st.wrap}>
        <Text style={st.icon}>🛠️</Text>
        <Text style={st.title}>Estamos en mantenimiento</Text>
        <Text style={st.text}>{cfg.app.message}</Text>
        <Button title="Reintentar" variant="secondary" onPress={check} style={{ marginTop: 20, alignSelf: 'stretch' }} />
      </View>
    );
  }
  if (cfg && isOutdated(APP_VERSION, cfg.app.min_version)) {
    return (
      <View style={st.wrap}>
        <Text style={st.icon}>⬆️</Text>
        <Text style={st.title}>Hay una versión nueva</Text>
        <Text style={st.text}>Para seguir pidiendo en Trappi actualizá la app (tenés la {APP_VERSION}, la mínima es la {cfg.app.min_version}).</Text>
        <Button title="Actualizar" onPress={() => Linking.openURL(cfg.app.download_url)} style={{ marginTop: 20, alignSelf: 'stretch' }} />
      </View>
    );
  }
  return <>{children}</>;
}

const st = StyleSheet.create({
  wrap: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32, backgroundColor: colors.bg, gap: 8 },
  icon: { fontSize: 64 },
  title: { fontSize: 24, fontWeight: '800', color: colors.ink, textAlign: 'center' },
  text: { fontSize: 16, color: colors.muted, textAlign: 'center' },
});
