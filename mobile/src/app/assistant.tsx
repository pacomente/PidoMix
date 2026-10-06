import { router } from 'expo-router';
import { useRef, useState } from 'react';
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Button, ProductRow, StoreCard } from '@/components/ui';
import { api } from '@/lib/api';
import { colors, radius } from '@/lib/theme';
import type { AiCard } from '@/lib/types';
import { useFetch } from '@/lib/useFetch';
import { useApp } from '@/state/app-state';

type Msg = { id: number; role: 'me' | 'bot'; text: string; cards?: AiCard[]; cartChanged?: boolean; error?: boolean };
const HINTS = ['Buscame hamburguesas cerca', '¿Qué está abierto ahora?', 'Opciones por menos de $15.000', '¿Dónde está mi pedido?'];

/**
 * Trappi AI: el chat le manda al servidor el mensaje, el carrito y la ubicación. El servidor (y solo él)
 * busca en Trappi con herramientas validadas y devuelve la respuesta, tarjetas reales y el carrito actualizado.
 */
export default function AssistantScreen() {
  const insets = useSafeAreaInsets();
  const { cart, replaceCart, location, account } = useApp();
  const config = useFetch(() => api.config(), []);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const state = useRef<string | null>(null);
  const scroll = useRef<ScrollView>(null);
  const nextId = useRef(1);

  const send = async (raw: string) => {
    const message = raw.trim();
    if (!message || busy) return;
    setText('');
    setMessages(m => [...m, { id: nextId.current++, role: 'me', text: message }]);
    setBusy(true);
    try {
      const res = await api.aiChat(message, state.current, cart, location);
      state.current = res.state;
      if (res.cart_changed && res.cart) replaceCart(res.cart);
      setMessages(m => [...m, { id: nextId.current++, role: 'bot', text: res.reply, cards: res.cards, cartChanged: res.cart_changed }]);
    } catch (e) {
      setMessages(m => [...m, { id: nextId.current++, role: 'bot', text: e instanceof Error ? e.message : 'No pude responder. Probá de nuevo.', error: true }]);
    } finally {
      setBusy(false);
      setTimeout(() => scroll.current?.scrollToEnd({ animated: true }), 50);
    }
  };

  const welcome = config.data?.ai?.welcome || '¡Hola! Soy Trappi AI 🤖 Contame qué buscás y te ayudo a encontrarlo.';
  return (
    <KeyboardAvoidingView style={{ flex: 1, backgroundColor: colors.bg }} behavior={Platform.OS === 'ios' ? 'padding' : undefined} keyboardVerticalOffset={90}>
      <ScrollView ref={scroll} contentContainerStyle={{ padding: 16, gap: 10 }} keyboardShouldPersistTaps="handled"
        onContentSizeChange={() => scroll.current?.scrollToEnd({ animated: true })}>
        <Bubble role="bot" text={welcome} />
        {!messages.length && (
          <View style={st.hints}>
            {HINTS.map(h => <Pressable key={h} style={st.hint} onPress={() => send(h)}><Text style={st.hintText}>{h}</Text></Pressable>)}
          </View>
        )}
        {messages.map(m => (
          <View key={m.id} style={{ gap: 8 }}>
            <Bubble role={m.role} text={m.text} error={m.error} />
            {m.cards?.map(c => c.type === 'store'
              ? <StoreCard key={`s${c.id}`} store={c.store} />
              : <ProductRow key={`p${c.id}`} product={c.product} onAdd={() => router.push({ pathname: '/product/[id]', params: { id: String(c.id) } })} />)}
            {m.cartChanged && <Button title={`Ver mi pedido (${cart.reduce((n, l) => n + l.quantity, 0)})`} variant="secondary" onPress={() => router.navigate('/cart')} />}
          </View>
        ))}
        {busy && <View style={[st.bubble, st.bot, { flexDirection: 'row', gap: 8 }]}><ActivityIndicator color={colors.brand} /><Text style={{ color: colors.muted }}>Buscando en Trappi…</Text></View>}
        <Text style={st.fine}>
          {!location ? '📍 Marcá tu ubicación para ver distancias y envíos. ' : ''}{!account ? 'Entrá con tu cuenta para consultar tus pedidos. ' : ''}
          El asistente usa solo información de Trappi y no hace ni paga pedidos: los confirmás vos en Mi pedido.
        </Text>
      </ScrollView>
      <View style={[st.footer, { paddingBottom: insets.bottom + 10 }]}>
        <TextInput style={st.input} value={text} onChangeText={setText} placeholder="Escribí lo que buscás…" placeholderTextColor={colors.muted}
          maxLength={600} onSubmitEditing={() => send(text)} returnKeyType="send" editable={!busy} />
        <Button title="Enviar" onPress={() => send(text)} disabled={busy || !text.trim()} style={{ minHeight: 48 }} />
      </View>
    </KeyboardAvoidingView>
  );
}

function Bubble({ role, text, error }: { role: 'me' | 'bot'; text: string; error?: boolean }) {
  // *negrita* como en WhatsApp
  const parts = text.split(/(\*[^*\n]+\*)/g);
  return (
    <View style={[st.bubble, role === 'me' ? st.me : st.bot, error && { backgroundColor: colors.badSoft }]}>
      <Text style={[st.text, role === 'me' && { color: '#fff' }, error && { color: colors.bad }]}>
        {parts.map((p, i) => (p.startsWith('*') && p.endsWith('*') && p.length > 2 ? <Text key={i} style={{ fontWeight: '800' }}>{p.slice(1, -1)}</Text> : p))}
      </Text>
    </View>
  );
}

const st = StyleSheet.create({
  bubble: { maxWidth: '88%', paddingHorizontal: 14, paddingVertical: 10, borderRadius: radius.md },
  me: { alignSelf: 'flex-end', backgroundColor: colors.brand, borderBottomRightRadius: 4 },
  bot: { alignSelf: 'flex-start', backgroundColor: '#fff', borderWidth: 1, borderColor: colors.line, borderBottomLeftRadius: 4 },
  text: { fontSize: 15.5, color: colors.ink, lineHeight: 22 },
  hints: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  hint: { borderWidth: 1, borderColor: colors.line, backgroundColor: '#fff', borderRadius: radius.pill, paddingHorizontal: 12, paddingVertical: 8 },
  hintText: { color: colors.brand, fontWeight: '700' },
  fine: { fontSize: 12.5, color: colors.muted, marginTop: 8, lineHeight: 18 },
  footer: { flexDirection: 'row', gap: 8, paddingHorizontal: 12, paddingTop: 10, backgroundColor: '#fff', borderTopWidth: 1, borderTopColor: colors.line },
  input: { flex: 1, minWidth: 0, backgroundColor: colors.bg, borderRadius: radius.pill, paddingHorizontal: 16, fontSize: 16, color: colors.ink, minHeight: 48 },
});
