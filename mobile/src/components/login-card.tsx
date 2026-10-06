import { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { Button } from '@/components/ui';
import { useFetch } from '@/lib/useFetch';
import { api } from '@/lib/api';
import { login as openLogin, openWebPage } from '@/lib/auth';
import { colors, radius } from '@/lib/theme';
import { useApp } from '@/state/app-state';

/** Entrar con un código por email (en el navegador) con el aviso legal. Al terminar deja la sesión abierta en la app. */
export function LoginCard({ title = 'Entrá a Trappi', text, onDone }: { title?: string; text?: string; onDone?: () => void }) {
  const { setSession } = useApp();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const config = useFetch(() => api.config(), []);

  const login = async () => {
    setError(null);
    setBusy(true);
    try {
      const res = await openLogin(config.data?.account?.login_path);
      if (res) { setSession(res.token, res.account); onDone?.(); }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No pudimos completar el ingreso.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={st.card}>
      <Text style={st.title}>{title}</Text>
      <Text style={st.text}>{text ?? 'Para hacer pedidos necesitás una cuenta. Así cada pedido queda a tu nombre, ves tu historial en cualquier dispositivo y nadie puede pedir haciéndose pasar por vos.'}</Text>
      <Button title="Entrar con tu email" onPress={login} loading={busy} style={{ marginTop: 12 }} />
      {error && <Text style={st.error}>{error}</Text>}
      <Text style={st.fine}>
        Al continuar aceptás los <Text style={st.link} onPress={() => openWebPage('/terminos')}>Términos y condiciones</Text> y la{' '}
        <Text style={st.link} onPress={() => openWebPage('/privacidad')}>Política de privacidad</Text>. Te mandamos un código de 6 números por email: sin contraseñas.
      </Text>
    </View>
  );
}

const st = StyleSheet.create({
  card: { backgroundColor: '#fff', borderRadius: radius.md, borderWidth: 1, borderColor: colors.line, padding: 18, gap: 4 },
  title: { fontSize: 20, fontWeight: '800', color: colors.ink },
  text: { fontSize: 15, color: colors.muted, lineHeight: 21 },
  error: { color: colors.bad, fontWeight: '700', marginTop: 8 },
  fine: { fontSize: 12.5, color: colors.muted, marginTop: 12, lineHeight: 18 },
  link: { color: colors.brand, fontWeight: '700' },
});
