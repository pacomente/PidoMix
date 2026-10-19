import { StyleSheet, Text, View, type StyleProp, type ViewStyle } from 'react-native';

type P = { lat: number; lng: number };

/** En la web de prueba no hay mapa nativo: se muestra un fondo con el resumen. */
export function RideMap({ driver, style }: { mapStyle: string; origin: P | null; dest: P | null; driver?: P | null; vehicle?: string; style?: StyleProp<ViewStyle>; fitKey?: string }) {
  return (
    <View style={[st.wrap, style]}>
      <Text style={st.txt}>{driver ? `🚗 ${driver.lat.toFixed(4)}, ${driver.lng.toFixed(4)}` : 'Mapa (solo en el celular)'}</Text>
    </View>
  );
}

const st = StyleSheet.create({
  wrap: { backgroundColor: '#E8E5DE', alignItems: 'center', justifyContent: 'center' },
  txt: { color: '#777', fontWeight: '600' },
});
