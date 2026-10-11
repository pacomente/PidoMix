import Ionicons from '@expo/vector-icons/Ionicons';
import { router, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, FlatList, Image, KeyboardAvoidingView, Platform, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { api, authImage } from '@/lib/api';
import { takePhoto } from '@/lib/camera';
import { colors, radius } from '@/lib/theme';
import type { ChatMessage } from '@/lib/types';

type Thread = 'cliente' | 'local';
const POLL_MS = 5000;

/** Chat del pedido: con el cliente o con el local, con fotos. Sin pasarse los teléfonos. */
export default function ChatScreen() {
  const insets = useSafeAreaInsets();
  const params = useLocalSearchParams<{ order: string; thread?: string }>();
  const orderId = Number(params.order);
  const [thread, setThread] = useState<Thread>(params.thread === 'local' ? 'local' : 'cliente');
  const [msgs, setMsgs] = useState<Record<Thread, ChatMessage[]>>({ cliente: [], local: [] });
  const [canWrite, setCanWrite] = useState(true);
  const [text, setText] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const list = useRef<FlatList<ChatMessage>>(null);
  const lastId = useRef<Record<Thread, number>>({ cliente: 0, local: 0 });

  const add = useCallback((t: Thread, items: ChatMessage[]) => {
    if (!items.length) return;
    lastId.current[t] = Math.max(lastId.current[t], ...items.map(m => m.id));
    setMsgs(m => ({ ...m, [t]: [...m[t], ...items.filter(n => !m[t].some(o => o.id === n.id))] }));
  }, []);

  const poll = useCallback(async () => {
    try {
      const c = await api.chat(orderId, thread, lastId.current[thread]);
      add(thread, c.messages);
      setCanWrite(c.can_write);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No se pudo cargar el chat.');
    } finally {
      setLoaded(true);
    }
  }, [orderId, thread, add]);

  useEffect(() => {
    poll();
    const t = setInterval(poll, POLL_MS);
    return () => clearInterval(t);
  }, [poll]);

  const send = async () => {
    const value = text.trim();
    if (!value || sending) return;
    setSending(true);
    try {
      const r = await api.chatSend(orderId, thread, value);
      add(thread, [r.message]);
      setText('');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No se pudo mandar.');
    } finally { setSending(false); }
  };

  const sendPhoto = async () => {
    const uri = await takePhoto();
    if (!uri) return;
    setSending(true);
    try {
      add(thread, [(await api.chatPhoto(orderId, thread, uri)).message]);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No se pudo mandar la foto.');
    } finally { setSending(false); }
  };

  const quick = thread === 'cliente'
    ? ['Ya estoy llegando 🛵', 'Estoy en la puerta', 'No encuentro la dirección, ¿me ayudás?', '¿Podés bajar?']
    : ['Ya estoy en camino al local', 'Llegué, ¿está listo?', 'Falta un producto', 'El cliente no responde'];

  return (
    <KeyboardAvoidingView style={{ flex: 1, backgroundColor: '#fff' }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <View style={[st.head, { paddingTop: insets.top + 8 }]}>
        <Pressable onPress={() => router.back()} style={st.back} accessibilityLabel="Volver"><Ionicons name="chevron-back" size={26} color="#fff" /></Pressable>
        <Text style={st.headTitle}>Pedido #{orderId}</Text>
      </View>
      <View style={st.tabs}>
        {(['cliente', 'local'] as Thread[]).map(t => (
          <Pressable key={t} onPress={() => setThread(t)} style={[st.tab, thread === t && st.tabOn]} accessibilityRole="tab" accessibilityState={{ selected: thread === t }}>
            <Text style={[st.tabText, thread === t && st.tabTextOn]}>{t === 'cliente' ? 'Cliente' : 'Local'}</Text>
          </Pressable>
        ))}
      </View>
      {!loaded ? <ActivityIndicator style={{ marginTop: 40 }} /> : (
        <FlatList
          ref={list}
          data={msgs[thread]}
          keyExtractor={m => String(m.id)}
          contentContainerStyle={{ padding: 12, gap: 8, flexGrow: 1 }}
          onContentSizeChange={() => list.current?.scrollToEnd({ animated: true })}
          ListEmptyComponent={<Text style={st.empty}>{thread === 'cliente' ? 'Escribile al cliente si no encontrás la dirección o para avisarle que llegaste. No hace falta pasarse los teléfonos.' : 'Hablá con el local si falta algo o el pedido no está listo.'}</Text>}
          renderItem={({ item }) => {
            const mine = item.sender === 'courier', sys = item.sender === 'system';
            return (
              <View style={[st.bubble, mine ? st.mine : sys ? st.sys : st.theirs]}>
                {!!item.photo && <Image source={authImage(item.photo)} style={st.photo} resizeMode="cover" accessibilityLabel="Foto" />}
                {!!item.text && <Text style={[st.text, mine && { color: '#fff' }, sys && st.sysText]}>{item.text}</Text>}
                <Text style={[st.time, mine && { color: '#DDE' }]}>{new Date(item.at).toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' })}</Text>
              </View>
            );
          }}
        />
      )}
      {!!error && <Text style={st.error}>{error}</Text>}
      {canWrite ? (
        <View style={{ paddingBottom: insets.bottom + 6 }}>
          <FlatList horizontal data={quick} keyExtractor={q => q} showsHorizontalScrollIndicator={false} contentContainerStyle={{ paddingHorizontal: 10, gap: 6 }}
            renderItem={({ item }) => <Pressable onPress={() => setText(item)} style={st.chip}><Text style={st.chipText}>{item}</Text></Pressable>} />
          <View style={st.inputRow}>
            <Pressable onPress={sendPhoto} disabled={sending} style={st.iconBtn} accessibilityLabel="Mandar una foto"><Ionicons name="camera" size={24} color={colors.ink} /></Pressable>
            <TextInput value={text} onChangeText={setText} placeholder="Escribí un mensaje" placeholderTextColor="#999" style={st.input} multiline maxLength={600} accessibilityLabel="Mensaje" />
            <Pressable onPress={send} disabled={sending || !text.trim()} style={[st.send, (!text.trim() || sending) && { opacity: 0.4 }]} accessibilityLabel="Enviar">
              {sending ? <ActivityIndicator color="#fff" /> : <Ionicons name="send" size={20} color="#fff" />}
            </Pressable>
          </View>
        </View>
      ) : <Text style={[st.closed, { paddingBottom: insets.bottom + 12 }]}>El chat se cerró: el pedido ya terminó.</Text>}
    </KeyboardAvoidingView>
  );
}

const st = StyleSheet.create({
  head: { backgroundColor: '#000', flexDirection: 'row', alignItems: 'center', paddingHorizontal: 8, paddingBottom: 10 },
  back: { padding: 6 },
  headTitle: { color: '#fff', fontWeight: '900', fontSize: 18 },
  tabs: { flexDirection: 'row', borderBottomWidth: 1, borderBottomColor: colors.line },
  tab: { flex: 1, alignItems: 'center', paddingVertical: 12 },
  tabOn: { borderBottomWidth: 3, borderBottomColor: colors.ink },
  tabText: { fontWeight: '700', color: colors.muted, fontSize: 15 },
  tabTextOn: { color: colors.ink },
  empty: { color: colors.muted, textAlign: 'center', marginTop: 30, paddingHorizontal: 20 },
  bubble: { maxWidth: '82%', borderRadius: radius.md, padding: 10, gap: 4 },
  mine: { alignSelf: 'flex-end', backgroundColor: colors.ink },
  theirs: { alignSelf: 'flex-start', backgroundColor: '#F0F0F0' },
  sys: { alignSelf: 'center', backgroundColor: '#FFF6DD' },
  text: { fontSize: 15.5, color: colors.ink },
  sysText: { color: '#7A5300', fontWeight: '700', textAlign: 'center' },
  time: { fontSize: 11, color: colors.muted, alignSelf: 'flex-end' },
  photo: { width: 220, height: 220, borderRadius: radius.sm, backgroundColor: '#ddd' },
  error: { color: colors.danger, textAlign: 'center', paddingHorizontal: 12, fontWeight: '700' },
  chip: { backgroundColor: '#F2F2F2', borderRadius: radius.pill, paddingHorizontal: 12, paddingVertical: 7, marginVertical: 6 },
  chipText: { fontWeight: '600', color: colors.ink },
  inputRow: { flexDirection: 'row', alignItems: 'flex-end', gap: 8, paddingHorizontal: 10 },
  iconBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: '#F2F2F2', alignItems: 'center', justifyContent: 'center' },
  input: { flex: 1, minHeight: 44, maxHeight: 110, borderRadius: 22, backgroundColor: '#F2F2F2', paddingHorizontal: 14, paddingVertical: 10, fontSize: 15.5, color: colors.ink },
  send: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.money, alignItems: 'center', justifyContent: 'center' },
  closed: { textAlign: 'center', color: colors.muted, paddingTop: 12 },
});
