import { StyleSheet } from 'react-native';

// Estilo Trappi (1.9): violeta para "conectarse" y lo principal, verde para la plata, rojo para la demanda, menta para los avisos de ruta.
// Dos paletas: clara (de día, al sol) y oscura (de noche, no encandila). Los colores de marca son los mismos en las dos.
export const brand = {
  go: '#6C2BD9',
  mint: '#2EE59D',
  money: '#06C167',
  danger: '#E11900',
  warn: '#FFC043',
  violet: '#6C2BD9',
};

export type Palette = typeof light;

const light = {
  dark: false,
  ...brand,
  bg: '#F6F4FA',        // fondo de las pantallas
  card: '#FFFFFF',      // tarjetas y paneles sobre el mapa
  card2: '#F1EEF7',     // botones redondos, filas, campos
  ink: '#14101F',
  muted: '#6E6785',
  line: '#E8E4F0',
  inverse: '#14101F',   // la píldora de ganancias, el botón principal
  onInverse: '#FFFFFF',
  dangerText: '#C81700',
  moneyText: '#058A4A',
  paidBg: '#E9F9EF', paidLine: '#BFEBD0',
  cashBg: '#FFF6DD', cashLine: '#F5DC9A', cashText: '#7A5300',
  failBg: '#FFF1F0', failLine: '#F3B8B2',
  infoBg: '#EFE8FC',
  hotBg: '#FFE9E5',
  navBg: '#2A1660',
  mapBg: '#E9E7EE',
  chart: '#058A4A',     // barras del gráfico de ganancias (validado: contraste >= 3:1 sobre la tarjeta)
  shadow: 0.2,
};

const dark: Palette = {
  dark: true,
  ...brand,
  bg: '#111016',
  card: '#17161D',
  card2: '#211F29',
  ink: '#FFFFFF',
  muted: '#A9A3BC',
  line: '#2A2833',
  inverse: '#FFFFFF',
  onInverse: '#000000',
  dangerText: '#FF6B57',
  moneyText: '#2EE08A',
  paidBg: '#0E2A1C', paidLine: '#1D5A3B',
  cashBg: '#2E2410', cashLine: '#5C4718', cashText: '#FFD27A',
  failBg: '#33110D', failLine: '#6B231B',
  infoBg: '#1E1640',
  hotBg: '#3A0D08',
  navBg: '#2A1660',
  mapBg: '#1B1A22',
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
