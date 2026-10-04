import { Redirect } from 'expo-router';
import { useState } from 'react';
import { KeyboardAvoidingView, Platform, StyleSheet, Text, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Button } from '@/components/ui';
import { colors, radius } from '@/lib/theme';
import { useSession } from '@/state/session';

export default function Login() {
  const insets = useSafeAreaInsets();
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
        <TextInput style={st.input} value={phone} onChangeText={setPhone} keyboardType="phone-pad" placeholder="291 456-7890" placeholderTextColor="#666" autoComplete="tel" textContentType="telephoneNumber" />
        <Text style={st.label}>PIN</Text>
        <TextInput style={[st.input, st.pin]} value={pin} onChangeText={t => setPin(t.replace(/\D/g, '').slice(0, 6))} keyboardType="number-pad" secureTextEntry placeholder="••••" placeholderTextColor="#666" maxLength={6} />
        {!!error && <Text style={st.error}>{error}</Text>}
      </View>
      <Button big variant="go" title="Entrar" loading={busy} disabled={phone.replace(/\D/g, '').length < 8 || pin.length < 4} onPress={() => login(phone, pin).catch(() => {})} />
    </KeyboardAvoidingView>
  );
}

const st = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: '#000', paddingHorizontal: 24 },
  logo: { width: 56, height: 56, borderRadius: 14, backgroundColor: '#6C2BD9', alignItems: 'center', justifyContent: 'center' },
  logoT: { color: '#fff', fontSize: 32, fontWeight: '900' },
  brand: { color: '#fff', fontSize: 34, fontWeight: '900', marginTop: 18, letterSpacing: -0.8 },
  title: { color: colors.money, fontSize: 34, fontWeight: '900', letterSpacing: -0.8, marginTop: -6 },
  sub: { color: '#AAA', fontSize: 16, marginTop: 10, marginBottom: 26 },
  label: { color: '#fff', fontWeight: '700', marginBottom: 6, marginTop: 12 },
  input: { backgroundColor: colors.dark2, color: '#fff', borderRadius: radius.sm, paddingHorizontal: 16, paddingVertical: 14, fontSize: 18 },
  pin: { letterSpacing: 8, fontSize: 22 },
  error: { color: '#FF6B57', fontWeight: '700', marginTop: 16 },
});
