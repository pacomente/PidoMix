import { StyleSheet } from 'react-native';

// Estilo Uber Driver: negro y blanco, azul para "conectarse", verde para la plata y rojo para la demanda.
// Dos paletas: clara (de día, al sol) y oscura (de noche, no encandila). Los colores de marca son los mismos en las dos.
export const brand = {
  go: '#276EF1',
  money: '#06C167',
  danger: '#E11900',
  warn: '#FFC043',
  violet: '#6C2BD9',
};

export type Palette = typeof light;

const light = {
  dark: false,
  ...brand,
  bg: '#F3F3F3',        // fondo de las pantallas
  card: '#FFFFFF',      // tarjetas y paneles sobre el mapa
  card2: '#F1F1F1',     // botones redondos, filas, campos
  ink: '#000000',
  muted: '#6B6B6B',
  line: '#E8E8E8',
  inverse: '#000000',   // la píldora de ganancias, el botón principal
  onInverse: '#FFFFFF',
  dangerText: '#C81700',
  moneyText: '#058A4A',
  paidBg: '#E9F9EF', paidLine: '#BFEBD0',
  cashBg: '#FFF6DD', cashLine: '#F5DC9A', cashText: '#7A5300',
  failBg: '#FFF1F0', failLine: '#F3B8B2',
  infoBg: '#E8F1FF',
  hotBg: '#FFE9E5',
  navBg: '#0B3D2E',
  mapBg: '#E9E9E9',
  chart: '#058A4A',     // barras del gráfico de ganancias (validado: contraste >= 3:1 sobre la tarjeta)
  shadow: 0.2,
};

const dark: Palette = {
  dark: true,
  ...brand,
  bg: '#000000',
  card: '#161616',
  card2: '#262626',
  ink: '#FFFFFF',
  muted: '#A3A3A3',
  line: '#2A2A2A',
  inverse: '#FFFFFF',
  onInverse: '#000000',
  dangerText: '#FF6B57',
  moneyText: '#2EE08A',
  paidBg: '#0E2A1C', paidLine: '#1D5A3B',
  cashBg: '#2E2410', cashLine: '#5C4718', cashText: '#FFD27A',
  failBg: '#33110D', failLine: '#6B231B',
  infoBg: '#10213D',
  hotBg: '#3A0D08',
  navBg: '#0B3D2E',
  mapBg: '#1B1B1B',
  chart: '#05A85A',
  shadow: 0.5,
};

export const palettes = { light, dark };

export const radius = { sm: 10, md: 16, lg: 24, pill: 999 };

/** Estilos que dependen del tema: se crean una vez por paleta. */
export function themed<T extends StyleSheet.NamedStyles<T>>(fn: (c: Palette) => T) {
  const cache = new Map<Palette, T>();
  return (c: Palette): T => {
    let s = cache.get(c);
    if (!s) { s = StyleSheet.create(fn(c)); cache.set(c, s); }
    return s;
  };
}
