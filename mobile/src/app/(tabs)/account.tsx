import { Image } from 'expo-image';
import { useState } from 'react';
import { useFetch } from '@/lib/useFetch';
import { Alert, KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Switch, Text, TextInput, View, type TextInputProps } from 'react-native';

import { LoginCard } from '@/components/login-card';
import { Button } from '@/components/ui';
import { api } from '@/lib/api';
import { openWebPage } from '@/lib/auth';
import { colors, radius } from '@/lib/theme';
import { useApp } from '@/state/app-state';

export default function AccountScreen() {
  const { account, setAccount, signOut } = useApp();
  const [form, setForm] = useState({ first_name: '', last_name: '', phone: '', address: '', reference: '' });
  const [saving, setSaving] = useState(false);
  const points = useFetch(() => (account ? api.myPoints().catch(() => null) : Promise.resolve(null)), [account?.id]);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const set = (k: keyof typeof form) => (v: string) => setForm(f => ({ ...f, [k]: v }));

  // el formulario arranca con los datos de la cuenta (y se vuelve a llenar si llegan datos nuevos del servidor)
  const [filledWith, setFilledWith] = useState<typeof account>(null);
  if (account && filledWith !== account) {
    setFilledWith(account);
    setForm({ first_name: account.first_name, last_name: account.last_name, phone: account.phone, address: account.address, reference: account.reference });
  }

  const legal = (
    <View style={st.legal}>
      <Text style={st.link} onPress={() => openWebPage('/terminos')}>Términos y condiciones</Text>
      <Text style={st.link} onPress={() => openWebPage('/privacidad')}>Política de privacidad</Text>
      <Text style={st.link} onPress={() => openWebPage('/arrepentimiento')}>Botón de arrepentimiento</Text>
    </View>
  );

  if (!account) {
    return <ScrollView style={{ backgroundColor: colors.bg }} contentContainerStyle={{ padding: 16, gap: 16 }}><LoginCard />{legal}</ScrollView>;
  }

  const save = async () => {
    setSaving(true); setMessage(null);
    try {
      const res = await api.updateMe(form);
      setAccount(res.account);
      setMessage({ ok: true, text: 'Datos guardados.' });
    } catch (e) {
      setMessage({ ok: false, text: e instanceof Error ? e.message : 'No se pudo guardar.' });
    } finally {
      setSaving(false);
    }
  };

  const toggle = async (data: { personalize?: boolean; marketing_opt_in?: boolean }) => {
    try {
      const res = await api.updateMe(data);
      setAccount(res.account);
    } catch (e) {
      Alert.alert('No se pudo cambiar', e instanceof Error ? e.message : 'Probá de nuevo.');
    }
  };

  const logout = (everywhere: boolean) => {
    api.logout(everywhere).catch(() => {}).finally(signOut);
  };

  const remove = () => Alert.alert('Eliminar mi cuenta', 'Borramos tu cuenta y tus datos de contacto. Los pedidos que ya hiciste se guardan solo el tiempo que exigen las normas contables. No se puede deshacer.', [
    { text: 'Cancelar', style: 'cancel' },
    { text: 'Eliminar', style: 'destructive', onPress: () => {
      api.deleteMe().then(() => { signOut(); Alert.alert('Cuenta eliminada', 'Eliminamos tu cuenta. ¡Gracias por haber usado Trappi!'); })
        .catch(e => Alert.alert('No se pudo eliminar', e instanceof Error ? e.message : 'Probá de nuevo.'));
    } },
  ]);

  return (
    <KeyboardAvoidingView style={{ flex: 1, backgroundColor: colors.bg }} behavior={Platform.OS === 'ios' ? 'padding' : undefined} keyboardVerticalOffset={90}>
      <ScrollView contentContainerStyle={{ padding: 16, gap: 16 }} keyboardShouldPersistTaps="handled">
        <View style={[st.card, st.head]}>
          {account.picture_url ? <Image source={{ uri: account.picture_url }} style={st.avatar} /> : <View style={[st.avatar, { backgroundColor: colors.brandSoft }]} />}
          <View style={{ flex: 1 }}>
            <Text style={st.name} numberOfLines={1}>{account.name || account.email}</Text>
            <Text style={st.muted} numberOfLines={1}>{account.email}</Text>
          </View>
        </View>

        {points.data?.enabled && (
          <View style={[st.card, { backgroundColor: colors.brandSoft, borderColor: colors.brandSoft }]}>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
              <View style={{ flex: 1 }}>
                <Text style={st.title}>Puntos Trappi</Text>
                <Text style={st.muted}>Ganás 1 punto cada ${points.data.rules.pesos_per_point.toLocaleString('es-AR')} en productos al recibir tu pedido. Los usás en el checkout desde {points.data.rules.min} puntos.</Text>
              </View>
              <View style={{ alignItems: 'flex-end' }}>
                <Text style={{ fontSize: 30, fontWeight: '800', color: colors.brand }}>{points.data.points}</Text>
                <Text style={st.muted}>= ${points.data.value.toLocaleString('es-AR')}</Text>
              </View>
            </View>
            {points.data.expiring > 0 && points.data.expiring_at && (
              <Text style={{ color: colors.warn, fontWeight: '700', marginTop: 8 }}>{points.data.expiring} puntos vencen el {new Date(points.data.expiring_at).toLocaleDateString('es-AR')}.</Text>
            )}
          </View>
        )}

        <View style={st.card}>
          <Text style={st.title}>Tus datos para los pedidos</Text>
          <View style={{ flexDirection: 'row', gap: 10 }}>
            <Field style={{ flex: 1, minWidth: 0 }} placeholder="Nombre" value={form.first_name} onChangeText={set('first_name')} autoComplete="given-name" />
            <Field style={{ flex: 1, minWidth: 0 }} placeholder="Apellido" value={form.last_name} onChangeText={set('last_name')} autoComplete="family-name" />
          </View>
          <Field placeholder="Teléfono (WhatsApp)" value={form.phone} onChangeText={set('phone')} keyboardType="phone-pad" autoComplete="tel" />
          <Field placeholder="Dirección habitual" value={form.address} onChangeText={set('address')} autoComplete="street-address" />
          <Field placeholder="Referencia (portón, piso, timbre…)" value={form.reference} onChangeText={set('reference')} />
          {message && <Text style={{ color: message.ok ? colors.good : colors.bad, fontWeight: '700', marginBottom: 8 }}>{message.text}</Text>}
          <Button title="Guardar" onPress={save} loading={saving} />
        </View>

        <View style={st.card}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
            <Text style={[st.title, { flex: 1, marginBottom: 0 }]}>Recomendado para vos</Text>
            <Switch value={account.personalize !== false} onValueChange={on => toggle({ personalize: on })} trackColor={{ true: colors.brand, false: colors.line }} thumbColor="#fff"
              accessibilityLabel="Recomendaciones personalizadas" />
          </View>
          <Text style={[st.muted, { marginTop: 6 }]}>Usamos solo tus pedidos, tus favoritos y tus calificaciones para mostrarte en el inicio lo que te puede gustar. No compartimos esta información con nadie.</Text>
        </View>

        <View style={st.card}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
            <Text style={[st.title, { flex: 1, marginBottom: 0 }]}>Novedades y descuentos</Text>
            <Switch value={!!account.marketing_opt_in} onValueChange={on => toggle({ marketing_opt_in: on })} trackColor={{ true: colors.brand, false: colors.line }} thumbColor="#fff"
              accessibilityLabel="Recibir novedades y descuentos" />
          </View>
          <Text style={[st.muted, { marginTop: 6 }]}>Te avisamos por notificación o email cuando tengas un descuento o para recordarte volver a pedir. Como mucho un mensaje cada dos semanas.</Text>
        </View>

        <View style={st.card}>
          <Text style={st.title}>Sesión</Text>
          <Button title="Cerrar sesión" variant="ghost" onPress={() => logout(false)} />
          <Button title="Cerrar sesión en todos lados" variant="ghost" onPress={() => logout(true)} style={{ marginTop: 8 }} />
        </View>

        <View style={[st.card, { borderColor: '#F2C6BE' }]}>
          <Text style={st.title}>Eliminar mi cuenta</Text>
          <Text style={[st.muted, { marginBottom: 10 }]}>Podés eliminarla cuando quieras. Si después querés volver, creás una cuenta nueva.</Text>
          <Button title="Eliminar mi cuenta" variant="danger" onPress={remove} />
        </View>
        {legal}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

function Field({ style, ...props }: TextInputProps) {
  return <TextInput placeholderTextColor={colors.muted} {...props} style={[st.input, style]} />;
}

const st = StyleSheet.create({
  card: { backgroundColor: '#fff', borderRadius: radius.md, borderWidth: 1, borderColor: colors.line, padding: 16 },
  head: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  avatar: { width: 52, height: 52, borderRadius: 26 },
  name: { fontSize: 17, fontWeight: '800', color: colors.ink },
  title: { fontSize: 16, fontWeight: '800', color: colors.ink, marginBottom: 10 },
  muted: { color: colors.muted, fontSize: 13.5 },
  input: { backgroundColor: '#fff', borderWidth: 1, borderColor: colors.line, borderRadius: radius.sm, paddingHorizontal: 14, paddingVertical: 12, fontSize: 16, color: colors.ink, marginBottom: 10 },
  legal: { alignItems: 'center', gap: 10, paddingVertical: 8 },
  link: { color: colors.brand, fontWeight: '700' },
});
