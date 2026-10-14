import Ionicons from '@expo/vector-icons/Ionicons';
import { CameraView, useCameraPermissions } from 'expo-camera';
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

import { LoginCard } from '@/components/login-card';
import { Button } from '@/components/ui';
import { api } from '@/lib/api';
import { colors, radius } from '@/lib/theme';
import { useApp } from '@/state/app-state';

/**
 * Escanear QR de Puntos Trappi en un local (programa Trappi Caja):
 *  - el del ticket (/puntos/q/CODIGO): suma los puntos de esa compra,
 *  - el del mostrador (/puntos/local/CODIGO): paga parte de la compra con puntos, poniendo el código que muestra la caja.
 * Todo lo valida el servidor; la app solo muestra lo que responde.
 */
type Target = { kind: 'claim'; code: string } | { kind: 'counter'; counter: string };

export function parseTrappiQr(raw: string): Target | null {
  const text = (raw || '').trim();
  const claim = text.match(/\/puntos\/q\/([A-Za-z0-9]{4}-?[A-Za-z0-9]{4})/);
  if (claim) return { kind: 'claim', code: claim[1].toUpperCase() };
  const counter = text.match(/\/puntos\/local\/([a-z0-9]{6,16})/i);
  if (counter) return { kind: 'counter', counter: counter[1].toLowerCase() };
  if (/^[A-Za-z0-9]{4}-[A-Za-z0-9]{4}$/.test(text)) return { kind: 'claim', code: text.toUpperCase() };  // código escrito a mano
  return null;
}

const money = (n: number) => '$' + Math.round(n).toLocaleString('es-AR');

export default function ScanScreen() {
  const { account } = useApp();
  const params = useLocalSearchParams<{ url?: string }>();
  const [permission, requestPermission] = useCameraPermissions();
  const [target, setTarget] = useState<Target | null>(() => (params.url ? parseTrappiQr(String(params.url)) : null));
  const [manual, setManual] = useState('');
  const [wrongQr, setWrongQr] = useState(false);
  const busy = useRef(false);

  if (!account) {
    return (
      <ScrollView style={{ backgroundColor: colors.bg }} contentContainerStyle={{ padding: 16, gap: 16 }}>
        <Text style={st.lead}>Entrá con tu cuenta para sumar o usar tus Puntos Trappi en los locales.</Text>
        <LoginCard />
      </ScrollView>
    );
  }

  if (target) {
    return target.kind === 'claim'
      ? <ClaimView code={target.code} onAgain={() => setTarget(null)} />
      : <CounterView counter={target.counter} onAgain={() => setTarget(null)} />;
  }

  const onScan = ({ data }: { data: string }) => {
    if (busy.current) return;
    const t = parseTrappiQr(data);
    if (!t) { setWrongQr(true); return; }
    busy.current = true;
    setTarget(t);
    setTimeout(() => { busy.current = false; }, 800);
  };

  return (
    <KeyboardAvoidingView style={{ flex: 1, backgroundColor: colors.bg }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView contentContainerStyle={{ padding: 16, gap: 14 }} keyboardShouldPersistTaps="handled">
        <Text style={st.lead}>Escaneá el QR del ticket para <Text style={st.b}>sumar puntos</Text>, o el del mostrador para <Text style={st.b}>pagar con tus puntos</Text>.</Text>
        <View style={st.cameraBox}>
          {permission?.granted ? (
            <CameraView style={StyleSheet.absoluteFill} facing="back" barcodeScannerSettings={{ barcodeTypes: ['qr'] }} onBarcodeScanned={onScan} />
          ) : (
            <View style={st.noCam}>
              <Ionicons name="camera-outline" size={40} color={colors.brand} />
              <Text style={[st.muted, { textAlign: 'center' }]}>Trappi necesita la cámara solo para leer el QR.</Text>
              {permission && !permission.canAskAgain
                ? <Text style={[st.muted, { textAlign: 'center' }]}>Activá el permiso de cámara para Trappi en los ajustes del celular.</Text>
                : <Button title="Permitir cámara" onPress={requestPermission} />}
            </View>
          )}
          {permission?.granted && <View pointerEvents="none" style={st.frame} />}
        </View>
        {wrongQr && <Text style={st.error}>Ese QR no es de Puntos Trappi. Buscá el del ticket o el del mostrador del local.</Text>}
        <View style={st.card}>
          <Text style={st.title}>¿No podés escanear?</Text>
          <Text style={st.muted}>Escribí el código que dice el ticket (por ejemplo ABCD-1234).</Text>
          <TextInput style={st.input} value={manual} onChangeText={v => setManual(v.toUpperCase())} placeholder="ABCD-1234" autoCapitalize="characters" maxLength={9} />
          <Button title="Sumar puntos" disabled={!parseTrappiQr(manual)} onPress={() => { const t = parseTrappiQr(manual); if (t) setTarget(t); }} />
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

function Done({ title, text, onAgain }: { title: string; text: string; onAgain: () => void }) {
  return (
    <View style={[st.card, { alignItems: 'center', gap: 10 }]}>
      <Ionicons name="checkmark-circle" size={64} color={colors.good} />
      <Text style={[st.title, { fontSize: 22, textAlign: 'center' }]}>{title}</Text>
      <Text style={[st.muted, { textAlign: 'center' }]}>{text}</Text>
      <Button title="Listo" onPress={() => (router.canGoBack() ? router.back() : router.replace('/'))} />
      <Text style={st.link} onPress={onAgain}>Escanear otro</Text>
    </View>
  );
}

function Problem({ text, onAgain }: { text: string; onAgain: () => void }) {
  return (
    <View style={[st.card, { alignItems: 'center', gap: 10 }]}>
      <Ionicons name="alert-circle-outline" size={56} color={colors.bad} />
      <Text style={[st.muted, { textAlign: 'center', color: colors.ink }]}>{text}</Text>
      <Button title="Escanear de nuevo" variant="secondary" onPress={onAgain} />
    </View>
  );
}

function ClaimView({ code, onAgain }: { code: string; onAgain: () => void }) {
  const [info, setInfo] = useState<{ points: number; store: string; error: string | null } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<{ points: number; balance: number | null } | null>(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    let alive = true;
    api.pointsClaimInfo(code)
      .then(r => alive && setInfo({ points: r.points, store: r.store, error: r.error }))
      .catch(e => alive && setError(e instanceof Error ? e.message : 'No se pudo leer el QR.'));
    return () => { alive = false; };
  }, [code]);
  const claim = async () => {
    setSaving(true);
    try { setDone(await api.pointsClaim(code)); } catch (e) { setError(e instanceof Error ? e.message : 'No se pudo.'); } finally { setSaving(false); }
  };
  return (
    <ScrollView style={{ backgroundColor: colors.bg }} contentContainerStyle={{ padding: 16, gap: 14 }}>
      {done ? <Done title={`¡Sumaste ${done.points} puntos!`} text={done.balance != null ? `Ahora tenés ${done.balance} Puntos Trappi para usar como descuento.` : 'Ya están en tu cuenta.'} onAgain={onAgain} />
        : error ? <Problem text={error} onAgain={onAgain} />
        : !info ? <ActivityIndicator color={colors.brand} style={{ marginTop: 40 }} />
        : info.error ? <Problem text={info.error} onAgain={onAgain} />
        : (
          <View style={[st.card, { alignItems: 'center', gap: 8 }]}>
            <Ionicons name="star" size={48} color={colors.star} />
            <Text style={[st.title, { fontSize: 24 }]}>{info.points} Puntos Trappi</Text>
            <Text style={st.muted}>Por tu compra en <Text style={st.b}>{info.store}</Text></Text>
            <Button title="Sumar a mi cuenta" loading={saving} onPress={claim} style={{ alignSelf: 'stretch', marginTop: 8 }} />
          </View>
        )}
    </ScrollView>
  );
}

type Quote = { store: string; amount: number; points: number; discount: number; rest: number; balance: number; max_percent: number; reason: string | null };

function CounterView({ counter, onAgain }: { counter: string; onAgain: () => void }) {
  const [code, setCode] = useState('');
  const [quote, setQuote] = useState<Quote | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<{ store: string; points: number; discount: number; rest: number; balance: number | null } | null>(null);

  const ask = async () => {
    setBusy(true); setError(null);
    try { setQuote(await api.pointsCounterQuote(counter, code)); } catch (e) { setError(e instanceof Error ? e.message : 'No se pudo.'); } finally { setBusy(false); }
  };
  const confirm = async () => {
    setBusy(true); setError(null);
    try { setDone(await api.pointsCounterConfirm(counter, code)); } catch (e) { setError(e instanceof Error ? e.message : 'No se pudo.'); setQuote(null); } finally { setBusy(false); }
  };

  return (
    <KeyboardAvoidingView style={{ flex: 1, backgroundColor: colors.bg }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView contentContainerStyle={{ padding: 16, gap: 14 }} keyboardShouldPersistTaps="handled">
        {done ? (
          <Done title={`Usaste ${done.points} puntos`} text={`En ${done.store} te descuentan ${money(done.discount)}. Pagá ${money(done.rest)} en la caja.${done.balance != null ? ` Te quedan ${done.balance} puntos.` : ''}`} onAgain={onAgain} />
        ) : quote ? (
          <View style={[st.card, { gap: 10 }]}>
            <Text style={st.title}>{quote.store}</Text>
            <Text style={st.muted}>Ticket de {money(quote.amount)}</Text>
            {quote.points ? (
              <>
                <View style={st.discount}>
                  <Text style={{ fontSize: 34, fontWeight: '900', color: colors.brand }}>-{money(quote.discount)}</Text>
                  <Text style={{ color: colors.ink }}>usando {quote.points} de tus {quote.balance} puntos</Text>
                  <Text style={st.muted}>Pagás {money(quote.rest)} en la caja</Text>
                </View>
                <Button title="Usar mis puntos" loading={busy} onPress={confirm} />
                <Text style={[st.muted, { fontSize: 12 }]}>Se usa hasta el {quote.max_percent}% del ticket. Si la caja cancela, los puntos vuelven a tu cuenta.</Text>
              </>
            ) : <Text style={{ color: colors.ink }}>{quote.reason}</Text>}
            <Text style={st.link} onPress={() => setQuote(null)}>Cambiar el código</Text>
          </View>
        ) : (
          <View style={[st.card, { gap: 12, alignItems: 'center' }]}>
            <Ionicons name="star" size={44} color={colors.star} />
            <Text style={[st.title, { fontSize: 20, textAlign: 'center' }]}>Pagá con Puntos Trappi</Text>
            <Text style={[st.muted, { textAlign: 'center' }]}>Poné el código de 4 números que ves en la pantalla de la caja. Si no aparece, pedile al cajero “pagar con Puntos Trappi”.</Text>
            <TextInput style={st.code} value={code} onChangeText={v => setCode(v.replace(/\D/g, '').slice(0, 4))} keyboardType="number-pad" maxLength={4} autoFocus placeholder="0000" />
            {error && <Text style={st.error}>{error}</Text>}
            <Button title="Seguir" loading={busy} disabled={code.length !== 4} onPress={ask} style={{ alignSelf: 'stretch' }} />
            <Text style={st.link} onPress={onAgain}>Escanear otro QR</Text>
          </View>
        )}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const st = StyleSheet.create({
  lead: { color: colors.ink, fontSize: 15, lineHeight: 21 },
  b: { fontWeight: '800' },
  muted: { color: colors.muted, fontSize: 14, lineHeight: 20 },
  title: { color: colors.ink, fontSize: 17, fontWeight: '800' },
  card: { backgroundColor: colors.card, borderRadius: radius.lg, padding: 16, borderWidth: 1, borderColor: colors.line, gap: 8 },
  cameraBox: { height: 320, borderRadius: radius.lg, overflow: 'hidden', backgroundColor: '#120B22', alignItems: 'center', justifyContent: 'center' },
  noCam: { position: 'absolute', left: 0, right: 0, top: 0, bottom: 0, alignItems: 'center', justifyContent: 'center', gap: 12, padding: 24, backgroundColor: colors.brandSoft },
  frame: { width: 210, height: 210, borderRadius: 24, borderWidth: 3, borderColor: 'rgba(255,255,255,0.85)' },
  input: { borderWidth: 1, borderColor: colors.line, borderRadius: radius.md, padding: 12, fontSize: 18, letterSpacing: 2, color: colors.ink, backgroundColor: '#fff' },
  code: { width: 200, textAlign: 'center', fontSize: 36, fontWeight: '900', letterSpacing: 12, borderWidth: 2, borderColor: colors.line, borderRadius: radius.md, paddingVertical: 10, color: colors.ink, backgroundColor: '#fff' },
  discount: { backgroundColor: colors.brandSoft, borderRadius: radius.md, padding: 16, alignItems: 'center', gap: 4 },
  error: { color: colors.bad, fontWeight: '600', textAlign: 'center' },
  link: { color: colors.brand, fontWeight: '700', textAlign: 'center', paddingVertical: 6 },
});
