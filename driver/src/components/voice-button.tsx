import Ionicons from '@expo/vector-icons/Ionicons';
import { ExpoSpeechRecognitionModule, useSpeechRecognitionEvent } from 'expo-speech-recognition';
import { useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import { colors, radius } from '@/lib/theme';
import { say } from '@/lib/voice';

/** Mantené apretado y hablá: "cuánto falta", "avisale al cliente que llego en 5", "llevame a la zona con pedidos". */
export function VoiceButton({ onText, style }: { onText: (text: string) => Promise<string | null>; style?: object }) {
  const [listening, setListening] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [heard, setHeard] = useState<string | null>(null);
  const [reply, setReply] = useState<string | null>(null);

  useSpeechRecognitionEvent('start', () => setListening(true));
  useSpeechRecognitionEvent('end', () => setListening(false));
  useSpeechRecognitionEvent('error', e => {
    setListening(false);
    if (e.error !== 'no-speech' && e.error !== 'aborted') { setReply('No pude escucharte. Probá de nuevo.'); }
  });
  useSpeechRecognitionEvent('result', async e => {
    if (!e.isFinal) { setHeard(e.results[0]?.transcript ?? null); return; }
    const text = e.results[0]?.transcript?.trim();
    setHeard(text || null);
    if (!text) return;
    setThinking(true);
    try {
      const r = await onText(text);
      setReply(r);
      if (r) say(r);
    } finally { setThinking(false); }
  });

  const start = async () => {
    setReply(null); setHeard(null);
    const perm = await ExpoSpeechRecognitionModule.requestPermissionsAsync();
    if (!perm.granted) { setReply('Necesito permiso del micrófono para escucharte.'); return; }
    ExpoSpeechRecognitionModule.start({ lang: 'es-AR', interimResults: true, continuous: false, requiresOnDeviceRecognition: false });
  };
  const stop = () => ExpoSpeechRecognitionModule.stop();

  return (
    <View style={[st.wrap, style]} pointerEvents="box-none">
      {(listening || thinking || heard || reply) && (
        <Pressable onPress={() => { setHeard(null); setReply(null); }} style={st.bubble} accessibilityLabel="Cerrar">
          {!!heard && <Text style={st.heard}>“{heard}”</Text>}
          {thinking ? <ActivityIndicator color={colors.ink} /> : !!reply && <Text style={st.reply}>{reply}</Text>}
          {listening && !heard && <Text style={st.heard}>Te escucho…</Text>}
        </Pressable>
      )}
      <Pressable onPressIn={start} onPressOut={stop} style={[st.btn, listening && st.btnOn]} accessibilityRole="button"
        accessibilityLabel="Mantené apretado y hablale al asistente" accessibilityHint="Por ejemplo: cuánto falta, o avisale al cliente que llego en cinco minutos">
        <Ionicons name={listening ? 'mic' : 'mic-outline'} size={28} color="#fff" />
      </Pressable>
    </View>
  );
}

const st = StyleSheet.create({
  wrap: { alignItems: 'flex-end', gap: 8 },
  btn: { width: 60, height: 60, borderRadius: 30, backgroundColor: colors.ink, alignItems: 'center', justifyContent: 'center', shadowColor: '#000', shadowOpacity: 0.3, shadowRadius: 10, elevation: 8, borderWidth: 3, borderColor: '#fff' },
  btnOn: { backgroundColor: colors.danger, transform: [{ scale: 1.1 }] },
  bubble: { maxWidth: 280, backgroundColor: '#fff', borderRadius: radius.md, padding: 12, gap: 4, shadowColor: '#000', shadowOpacity: 0.2, shadowRadius: 10, elevation: 8 },
  heard: { color: colors.muted, fontStyle: 'italic' },
  reply: { color: colors.ink, fontWeight: '700', fontSize: 15 },
});
