import { Image } from 'expo-image';
import { LinearGradient } from 'expo-linear-gradient';
import type { ReactNode } from 'react';
import { StyleSheet, Text, View, type StyleProp, type ViewStyle } from 'react-native';

import { ILL } from '@/lib/ill';

/** Ilustración 3D de un emoji (Fluent); si no la tenemos, el emoji común. */
export function Ill({ e, size = 40, style }: { e?: string | null; size?: number; style?: StyleProp<ViewStyle> }) {
  const src = e ? ILL[e.replace(/️/g, '')] : undefined;
  if (src) return <Image source={src} style={[{ width: size, height: size }, style as object]} contentFit="contain" />;
  return <Text style={[{ fontSize: size * 0.82, lineHeight: size, width: size, textAlign: 'center' }, style as object]}>{e || '🛍️'}</Text>;
}

/** Cada rubro con su degradado y sus ilustraciones (portadas, tarjetas y la página del rubro). */
export const RUBRO_LOOK: Record<string, { grad: [string, string]; ills: string[]; soft: string }> = {
  restaurante: { grad: ['#FB923C', '#EA580C'], ills: ['🥤', '🍟', '🍔'], soft: '#FFF3E2' },
  super: { grad: ['#34D399', '#15803D'], ills: ['🥕', '🍌', '🧺', '🥛'], soft: '#E6F8EE' },
  carniceria: { grad: ['#FDA4AF', '#E11D48'], ills: ['🍗', '🥩'], soft: '#FFE4EC' },
  kiosco: { grad: ['#DB2777', '#2A1638'], ills: ['🍭', '🍫', '🥤'], soft: '#FCE7F3' },
  verduleria: { grad: ['#4ADE80', '#16A34A'], ills: ['🥑', '🥕', '🍅'], soft: '#E6F8EE' },
  farmacia: { grad: ['#38BDF8', '#2563EB'], ills: ['🧴', '💊'], soft: '#E0F2FE' },
  heladeria: { grad: ['#F9A8D4', '#DB2777'], ills: ['🍨', '🍦'], soft: '#FCE7F3' },
  bebidas: { grad: ['#A78BFA', '#6D28D9'], ills: ['🧊', '🍺', '🥤'], soft: '#F3E8FF' },
  panaderia: { grad: ['#FCD34D', '#D97706'], ills: ['🥖', '🥐'], soft: '#FEF6C3' },
  cafeteria: { grad: ['#D6A77A', '#92400E'], ills: ['🥐', '☕'], soft: '#FFF3E2' },
  fiambreria: { grad: ['#FDE68A', '#D97706'], ills: ['🥓', '🧀'], soft: '#FEF6C3' },
};
const DEFAULT_LOOK = { grad: ['#8B5CF6', '#6C2BD9'] as [string, string], ills: ['🛍️'], soft: '#F3E8FF' };
export const lookOf = (key?: string | null, emoji?: string | null) => {
  const l = (key && RUBRO_LOOK[key]) || DEFAULT_LOOK;
  // un restaurante muestra lo suyo (la hamburguesería, la hamburguesa; la pizzería, la pizza)
  if ((!key || key === 'restaurante') && emoji && emoji !== '🍽️' && emoji !== '🏪') return { ...l, ills: [...l.ills.slice(0, -1), emoji] };
  return l;
};

/** Degradado (de arriba a la izquierda hacia abajo a la derecha). */
export function Grad({ colors, style, children }: { colors: [string, string]; style?: StyleProp<ViewStyle>; children?: ReactNode }) {
  return <LinearGradient colors={colors} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={style}>{children}</LinearGradient>;
}

/** Portada con el degradado del rubro y sus ilustraciones flotando a la derecha. */
export function RubroCover({ rubro, emoji, style, children, big = 64, lift = 0 }: { rubro?: string | null; emoji?: string | null; style?: StyleProp<ViewStyle>; children?: ReactNode; big?: number; lift?: number }) {
  const l = lookOf(rubro, emoji);
  const n = l.ills.length;
  return (
    <Grad colors={l.grad} style={[{ overflow: 'hidden' }, style]}>
      <View style={st.glow} pointerEvents="none" />
      <View style={[st.ills, { bottom: 6 + lift }]} pointerEvents="none">
        {l.ills.map((e, i) => {
          const size = i === n - 1 ? big * 1.35 : big * (0.62 + (i % 2) * 0.12);
          return <Ill key={i} e={e} size={size} style={{ marginLeft: -size * 0.12, marginBottom: i % 2 ? 6 : 0, transform: [{ rotate: `${(i % 2 ? 1 : -1) * 8}deg` }] }} />;
        })}
      </View>
      {children}
    </Grad>
  );
}

const st = StyleSheet.create({
  glow: { position: 'absolute', right: -60, top: -70, width: 240, height: 240, borderRadius: 120, backgroundColor: '#fff', opacity: 0.14 },
  ills: { position: 'absolute', right: 10, bottom: 6, flexDirection: 'row', alignItems: 'flex-end' },
});
