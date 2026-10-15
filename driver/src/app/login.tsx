import { Redirect } from 'expo-router';
import { useState } from 'react';
import { KeyboardAvoidingView, Platform, Text, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Button } from '@/components/ui';
import { radius, themed } from '@/lib/theme';
import { useColors } from '@/state/prefs';
import { useSession } from '@/state/session';

export default function Login() {
  const insets = useSafeAreaInsets();
  const c = useColors(), st = useSt(c);
  const { loggedIn, login, busy, error } = useSession();
  const [phone, setPhone] = useState('');
  const [pin, setPin] = useState('');
  if (loggedIn) return <Redirect href="/" />;

  return (
    <KeyboardAvoidingView style={[st.wrap, { paddingTop: insets.top + 40, paddingBottom: insets.bottom + 20 }]} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <View style={{ flex: 1 }}>
        <View style={st.logo}><Text style={st.logoT}>T</Text></View>
        <Text style={st.brand}>Trappi</Text>
        <Text style={st.title}>Repartidores</Text>
        <Text style={st.sub}>Entrá con tu teléfono y el PIN que te dio el local o Trappi.</Text>
        <Text style={st.label}>Teléfono</Text>
        <TextInput style={st.input} value={phone} onChangeText={setPhone} keyboardType="phone-pad" placeholder="291 456-7890" placeholderTextColor={c.muted} autoComplete="tel" textContentType="telephoneNumber" />
        <Text style={st.label}>PIN</Text>
        <TextInput style={[st.input, st.pin]} value={pin} onChangeText={t => setPin(t.replace(/\D/g, '').slice(0, 6))} keyboardType="number-pad" secureTextEntry placeholder="••••" placeholderTextColor={c.muted} maxLength={6} />
        {!!error && <Text style={st.error}>{error}</Text>}
      </View>
      <Button big variant="go" title="Entrar" loading={busy} disabled={phone.replace(/\D/g, '').length < 8 || pin.length < 4} onPress={() => login(phone, pin).catch(() => {})} />
    </KeyboardAvoidingView>
  );
}

const useSt = themed(c => ({
  wrap: { flex: 1, backgroundColor: c.bg, paddingHorizontal: 24 },
  logo: { width: 56, height: 56, borderRadius: 14, backgroundColor: c.violet, alignItems: 'center', justifyContent: 'center' },
  logoT: { color: '#fff', fontSize: 32, fontWeight: '900' },
  brand: { color: c.ink, fontSize: 34, fontWeight: '900', marginTop: 18, letterSpacing: -0.8 },
  title: { color: c.moneyText, fontSize: 34, fontWeight: '900', letterSpacing: -0.8, marginTop: -6 },
  sub: { color: c.muted, fontSize: 16, marginTop: 10, marginBottom: 26 },
  label: { color: c.ink, fontWeight: '700', marginBottom: 6, marginTop: 12 },
  input: { backgroundColor: c.card2, color: c.ink, borderRadius: radius.sm, paddingHorizontal: 16, paddingVertical: 14, fontSize: 18 },
  pin: { letterSpacing: 8, fontSize: 22 },
  error: { color: c.dangerText, fontWeight: '700', marginTop: 16 },
}));
