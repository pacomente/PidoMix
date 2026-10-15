import Ionicons from '@expo/vector-icons/Ionicons';
import { useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, Animated, PanResponder, Pressable, StyleSheet, Text, View, type StyleProp, type ViewStyle } from 'react-native';

import { radius, themed, type Palette } from '@/lib/theme';
import { useColors } from '@/state/prefs';

type Variant = 'primary' | 'go' | 'money' | 'light' | 'danger' | 'ghost';
const variants = (c: Palette): Record<Variant, { bg: string; fg: string; border?: string }> => ({
  primary: { bg: c.inverse, fg: c.onInverse },
  go: { bg: c.go, fg: '#fff' },
  money: { bg: c.money, fg: '#fff' },
  light: { bg: c.card2, fg: c.ink },
  danger: { bg: c.failBg, fg: c.dangerText },
  ghost: { bg: 'transparent', fg: c.ink, border: c.line },
});

export function Button({ title, onPress, variant = 'primary', disabled, loading, style, big, icon }: {
  title: string; onPress?: () => void; variant?: Variant; disabled?: boolean; loading?: boolean; style?: StyleProp<ViewStyle>; big?: boolean;
  icon?: React.ComponentProps<typeof Ionicons>['name'];
}) {
  const v = variants(useColors())[variant];
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={title} onPress={onPress} disabled={disabled || loading}
      style={({ pressed }) => [s.btn, big && s.big, { backgroundColor: v.bg, borderColor: v.border ?? v.bg }, (disabled || loading) && { opacity: 0.5 }, pressed && { opacity: 0.85, transform: [{ scale: 0.99 }] }, style]}>
      {loading ? <ActivityIndicator color={v.fg} /> : (
        <View style={s.row}>
          {icon && <Ionicons name={icon} size={big ? 22 : 18} color={v.fg} />}
          <Text style={[s.txt, big && s.bigTxt, { color: v.fg }]}>{title}</Text>
        </View>
      )}
    </Pressable>
  );
}

/** Botón redondo flotante sobre el mapa (menú, recentrar...). */
export function RoundButton({ icon, onPress, label, active, style }: {
  icon: React.ComponentProps<typeof Ionicons>['name']; onPress: () => void; label: string; active?: boolean; style?: StyleProp<ViewStyle>;
}) {
  const c = useColors(), st = useRound(c);
  return (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityLabel={label} hitSlop={6}
      style={({ pressed }) => [st.round, active && { backgroundColor: c.go }, pressed && { transform: [{ scale: 0.94 }] }, style]}>
      <Ionicons name={icon} size={24} color={active ? '#fff' : c.ink} />
    </Pressable>
  );
}

const KNOB = 56;

/**
 * Deslizar para confirmar (como Uber): evita marcar "retiré" o "entregué" con un toque sin querer en el bolsillo.
 * Con lector de pantalla se confirma con la acción "activar".
 */
export function SlideButton({ title, onConfirm, variant = 'go', loading, disabled }: {
  title: string; onConfirm: () => void; variant?: 'go' | 'money'; loading?: boolean; disabled?: boolean;
}) {
  const c = useColors();
  const bg = variant === 'money' ? c.money : c.go;
  const [width, setWidth] = useState(0);
  const [x] = useState(() => new Animated.Value(0));
  const max = Math.max(0, width - KNOB - 8);
  const live = useRef({ max, onConfirm, off: !!(disabled || loading) });
  useEffect(() => { live.current = { max, onConfirm, off: !!(disabled || loading) }; }, [max, onConfirm, disabled, loading]);

  // los handlers leen live.current recién cuando el repartidor desliza (en el evento), no al dibujar
  // eslint-disable-next-line react-hooks/refs
  const pan = useMemo(() => PanResponder.create({
    onStartShouldSetPanResponder: () => !live.current.off,
    onMoveShouldSetPanResponder: (_, g) => !live.current.off && Math.abs(g.dx) > 4,
    onPanResponderTerminationRequest: () => false,
    onPanResponderMove: (_, g) => x.setValue(Math.max(0, Math.min(live.current.max, g.dx))),
    onPanResponderRelease: (_, g) => {
      const { max: m, onConfirm: go } = live.current;
      if (m > 0 && g.dx >= m * 0.8) {
        Animated.timing(x, { toValue: m, duration: 90, useNativeDriver: false }).start(() => { go(); x.setValue(0); });
      } else {
        Animated.spring(x, { toValue: 0, useNativeDriver: false, bounciness: 8 }).start();
      }
    },
  }), [x]);

  const fade = max > 0 ? x.interpolate({ inputRange: [0, max * 0.6], outputRange: [1, 0], extrapolate: 'clamp' }) : 1;
  return (
    <View style={[s.slide, { backgroundColor: bg }, disabled && { opacity: 0.5 }]} onLayout={e => setWidth(e.nativeEvent.layout.width)}
      accessible accessibilityRole="button" accessibilityLabel={title} accessibilityHint="Deslizá hacia la derecha para confirmar"
      accessibilityActions={[{ name: 'activate' }]} onAccessibilityAction={() => !disabled && !loading && onConfirm()}>
      {loading ? <ActivityIndicator color="#fff" /> : (
        <>
          <Animated.Text style={[s.slideTxt, { opacity: fade }]} numberOfLines={1}>{title}</Animated.Text>
          <Animated.View {...pan.panHandlers} style={[s.knob, { transform: [{ translateX: x }] }]}>
            <Ionicons name="chevron-forward" size={30} color={bg} />
          </Animated.View>
        </>
      )}
    </View>
  );
}

const useRound = themed(c => ({
  round: { width: 50, height: 50, borderRadius: 25, backgroundColor: c.card, alignItems: 'center', justifyContent: 'center', shadowColor: '#000', shadowOpacity: c.shadow, shadowRadius: 8, elevation: 6 },
}));

const s = StyleSheet.create({
  btn: { minHeight: 52, borderRadius: radius.sm, borderWidth: 1.5, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 18 },
  big: { minHeight: 60 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  txt: { fontSize: 16, fontWeight: '700' },
  bigTxt: { fontSize: 18, fontWeight: '800' },
  slide: { height: KNOB + 8, borderRadius: (KNOB + 8) / 2, justifyContent: 'center', alignItems: 'center', overflow: 'hidden' },
  slideTxt: { color: '#fff', fontSize: 17, fontWeight: '900', paddingLeft: KNOB + 8, paddingRight: 16 },
  knob: { position: 'absolute', left: 4, top: 4, width: KNOB, height: KNOB, borderRadius: KNOB / 2, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center' },
});
