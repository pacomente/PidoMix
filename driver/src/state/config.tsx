import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { AppState, Linking, StyleSheet, Text, View } from 'react-native';

import { Button } from '@/components/ui';
import { api, onMaintenance, type DriverConfig } from '@/lib/api';
import { APP_VERSION, isOutdated } from '@/lib/version';

const DEFAULTS: DriverConfig = {
  app: { enabled: true, message: '', min_version: '1.0.0', download_url: '' },
  map_style: 'https://tiles.openfreemap.org/styles/liberty',
  pulse_seconds: 4,
  support_whatsapp: null,
};
const Ctx = createContext<DriverConfig>(DEFAULTS);
export const useConfig = () => useContext(Ctx);

/** Configuración del panel: mantenimiento, versión mínima, mapa y frecuencia del pulso. */
export function ConfigGate({ children }: { children: ReactNode }) {
  const [cfg, setCfg] = useState<DriverConfig | null>(null);
  const check = useCallback(() => { api.config().then(setCfg).catch(() => {}); }, []);

  useEffect(() => {
    check();
    const t = setInterval(check, 2 * 60 * 1000);
    const sub = AppState.addEventListener('change', s => s === 'active' && check());
    const off = onMaintenance(check);
    return () => { clearInterval(t); sub.remove(); off(); };
  }, [check]);

  if (cfg && !cfg.app.enabled) {
    return (
      <View style={st.wrap}>
        <Text style={st.icon}>🛠️</Text>
        <Text style={st.title}>App en mantenimiento</Text>
        <Text style={st.text}>{cfg.app.message}</Text>
        <Button title="Reintentar" variant="light" onPress={check} style={{ marginTop: 22, alignSelf: 'stretch' }} />
      </View>
    );
  }
  if (cfg && isOutdated(APP_VERSION, cfg.app.min_version)) {
    return (
      <View style={st.wrap}>
        <Text style={st.icon}>⬆️</Text>
        <Text style={st.title}>Actualizá la app</Text>
        <Text style={st.text}>Hay una versión nueva de Trappi Repartidor. Tenés la {APP_VERSION} y la mínima es la {cfg.app.min_version}.</Text>
        <Button title="Descargar actualización" variant="go" big onPress={() => Linking.openURL(cfg.app.download_url)} style={{ marginTop: 22, alignSelf: 'stretch' }} />
      </View>
    );
  }
  return <Ctx.Provider value={cfg ?? DEFAULTS}>{children}</Ctx.Provider>;
}

const st = StyleSheet.create({
  wrap: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32, backgroundColor: '#000', gap: 10 },
  icon: { fontSize: 64 },
  title: { fontSize: 26, fontWeight: '900', color: '#fff', textAlign: 'center' },
  text: { fontSize: 16, color: '#AAA', textAlign: 'center' },
});
