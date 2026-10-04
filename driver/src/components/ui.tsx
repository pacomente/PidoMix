import { ActivityIndicator, Pressable, StyleSheet, Text, type StyleProp, type ViewStyle } from 'react-native';

import { colors, radius } from '@/lib/theme';

type Variant = 'primary' | 'go' | 'money' | 'light' | 'danger' | 'ghost';
const V: Record<Variant, { bg: string; fg: string; border?: string }> = {
  primary: { bg: colors.ink, fg: '#fff' },
  go: { bg: colors.go, fg: '#fff' },
  money: { bg: colors.money, fg: '#fff' },
  light: { bg: '#EEEEEE', fg: colors.ink },
  danger: { bg: '#FFF0EE', fg: colors.danger },
  ghost: { bg: 'transparent', fg: colors.ink, border: colors.line },
};

export function Button({ title, onPress, variant = 'primary', disabled, loading, style, big }: {
  title: string; onPress?: () => void; variant?: Variant; disabled?: boolean; loading?: boolean; style?: StyleProp<ViewStyle>; big?: boolean;
}) {
  const v = V[variant];
  return (
    <Pressable accessibilityRole="button" onPress={onPress} disabled={disabled || loading}
      style={({ pressed }) => [s.btn, big && s.big, { backgroundColor: v.bg, borderColor: v.border ?? v.bg }, (disabled || loading) && { opacity: 0.5 }, pressed && { opacity: 0.85, transform: [{ scale: 0.99 }] }, style]}>
      {loading ? <ActivityIndicator color={v.fg} /> : <Text style={[s.txt, big && s.bigTxt, { color: v.fg }]}>{title}</Text>}
    </Pressable>
  );
}

const s = StyleSheet.create({
  btn: { minHeight: 52, borderRadius: radius.sm, borderWidth: 1.5, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 18 },
  big: { minHeight: 60 },
  txt: { fontSize: 16, fontWeight: '700' },
  bigTxt: { fontSize: 18, fontWeight: '800' },
});
