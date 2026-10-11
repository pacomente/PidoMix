import Ionicons from '@expo/vector-icons/Ionicons';
import { Stack, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, FlatList, Image, KeyboardAvoidingView, Platform, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Empty } from '@/components/ui';
import { API_URL, api } from '@/lib/api';
import { colors, radius } from '@/lib/theme';
import type { ChatMessage } from '@/lib/types';
import { useApp } from '@/state/app-state';

const POLL_MS = 5000;

/** Chat con el repartidor del pedido: sin pasarse los teléfonos. */
export default function OrderChatScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const insets = useSafeAreaInsets();
  const { orders } = useApp();
  const saved = orders.find(o => String(o.id) === id);
  const [msgs, setMsgs] = useState<ChatMessage[]>([]);
  const [courier, setCourier] = useState<string | null>(null);
  const [canWrite, setCanWrite] = useState(true);
  const [text, setText] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const last = useRef(0);
  const list = useRef<FlatList<ChatMessage>>(null);

  const add = useCallback((items: ChatMessage[]) => {
    if (!items.length) return;
    last.current = Math.max(last.current, ...items.map(m => m.id));
    setMsgs(m => [...m, ...items.filter(n => !m.some(o => o.id === n.id))]);
  }, []);

  const poll = useCallback(async () => {
    if (!saved) return;
    try {
      const c = await api.orderChat(saved.id, saved.token, last.current);
      add(c.messages); setCourier(c.courier); setCanWrite(c.can_write); setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No se pudo cargar el chat.');
    } finally { setLoaded(true); }
  }, [saved, add]);

  useEffect(() => {
    poll();
    const t = setInterval(poll, POLL_MS);
    return () => clearInterval(t);
  }, [poll]);

  if (!saved) return <Empty emoji="💬" title="No encontramos este pedido" text="Sólo podés chatear por pedidos hechos desde este teléfono." />;

  const send = async () => {
    const value = text.trim();
    if (!value || sending) return;
    setSending(true);
    try {
      add([(await api.orderChatSend(saved.id, saved.token, value)).message]);
      setText('');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No se pudo mandar.');
    } finally { setSending(false); }
  };

  return (
    <KeyboardAvoidingView style={{ flex: 1, backgroundColor: colors.bg }} behavior={Platform.OS === 'ios' ? 'padding' : undefined} keyboardVerticalOffset={90}>
      <Stack.Screen options={{ title: courier ? `Chat con ${courier}` : 'Chat con el repartidor' }} />
      {!loaded ? <ActivityIndicator style={{ marginTop: 40 }} color={colors.brand} /> : (
        <FlatList
          ref={list}
          data={msgs}
          keyExtractor={m => String(m.id)}
          contentContainerStyle={{ padding: 12, gap: 8, flexGrow: 1 }}
          onContentSizeChange={() => list.current?.scrollToEnd({ animated: true })}
          ListEmptyComponent={<Text style={st.empty}>Escribile si querés darle una indicación (timbre, piso, por dónde entrar). No hace falta pasarse los teléfonos.</Text>}
          renderItem={({ item }) => {
            const mine = item.sender === 'customer', sys = item.sender === 'system';
            return (
              <View style={[st.bubble, mine ? st.mine : sys ? st.sys : st.theirs]}>
                {!!item.photo && <Image source={{ uri: API_URL + item.photo }} style={st.photo} resizeMode="cover" accessibilityLabel="Foto del repartidor" />}
                {!!item.text && <Text style={[st.text, mine && { color: '#fff' }, sys && st.sysText]}>{item.text}</Text>}
                <Text style={[st.time, mine && { color: '#E7DDFB' }]}>{new Date(item.at).toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' })}</Text>
              </View>
            );
          }}
        />
      )}
      {!!error && <Text style={st.error}>{error}</Text>}
      {canWrite ? (
        <View style={[st.inputRow, { paddingBottom: insets.bottom + 8 }]}>
          <TextInput value={text} onChangeText={setText} placeholder="Escribile al repartidor" placeholderTextColor={colors.muted} style={st.input} multiline maxLength={600} accessibilityLabel="Mensaje" />
          <Pressable onPress={send} disabled={sending || !text.trim()} style={[st.send, (!text.trim() || sending) && { opacity: 0.4 }]} accessibilityLabel="Enviar">
            {sending ? <ActivityIndicator color="#fff" /> : <Ionicons name="send" size={20} color="#fff" />}
          </Pressable>
        </View>
      ) : <Text style={[st.closed, { paddingBottom: insets.bottom + 12 }]}>El chat se cerró: el pedido ya terminó.</Text>}
    </KeyboardAvoidingView>
  );
}

const st = StyleSheet.create({
  empty: { color: colors.muted, textAlign: 'center', marginTop: 30, paddingHorizontal: 24 },
  bubble: { maxWidth: '82%', borderRadius: radius.md, padding: 10, gap: 4 },
  mine: { alignSelf: 'flex-end', backgroundColor: colors.brand },
  theirs: { alignSelf: 'flex-start', backgroundColor: '#fff', borderWidth: 1, borderColor: colors.line },
  sys: { alignSelf: 'center', backgroundColor: '#FFF6DD' },
  text: { fontSize: 15.5, color: colors.ink },
  sysText: { color: '#7A5300', fontWeight: '700', textAlign: 'center' },
  time: { fontSize: 11, color: colors.muted, alignSelf: 'flex-end' },
  photo: { width: 220, height: 220, borderRadius: radius.sm, backgroundColor: colors.line },
  error: { color: colors.bad, textAlign: 'center', paddingHorizontal: 12, fontWeight: '700' },
  inputRow: { flexDirection: 'row', alignItems: 'flex-end', gap: 8, paddingHorizontal: 10, paddingTop: 8, backgroundColor: '#fff', borderTopWidth: 1, borderTopColor: colors.line },
  input: { flex: 1, minHeight: 44, maxHeight: 110, borderRadius: 22, backgroundColor: colors.bg, paddingHorizontal: 14, paddingVertical: 10, fontSize: 15.5, color: colors.ink },
  send: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.brand, alignItems: 'center', justifyContent: 'center' },
  closed: { textAlign: 'center', color: colors.muted, paddingTop: 12 },
});
