import { Camera, Map, ViewAnnotation, type CameraRef } from '@maplibre/maplibre-react-native';
import { useEffect, useRef } from 'react';
import { StyleSheet, Text, View, type StyleProp, type ViewStyle } from 'react-native';

import { colors } from '@/lib/theme';

type P = { lat: number; lng: number };
const ll = (p: P): [number, number] => [p.lng, p.lat];

/** Mapa de un viaje: dónde te buscan, a dónde vas y el conductor (mapa gratis de OpenFreeMap). */
export function RideMap({ mapStyle, origin, dest, driver, vehicle = 'auto', style, fitKey = '' }: {
  mapStyle: string; origin: P | null; dest: P | null; driver?: P | null; vehicle?: string; style?: StyleProp<ViewStyle>; fitKey?: string;
}) {
  const camera = useRef<CameraRef>(null);
  const pts = [driver, origin, dest].filter(Boolean) as P[];
  const key = `${fitKey}|${pts.length}|${origin?.lat}|${dest?.lat}`;  // se encuadra al cambiar de etapa, no con cada movimiento

  useEffect(() => {
    if (!camera.current || !pts.length) return;
    if (pts.length === 1) { camera.current.easeTo({ center: ll(pts[0]), zoom: 15, duration: 500 }); return; }
    const lngs = pts.map(p => p.lng), lats = pts.map(p => p.lat);
    camera.current.fitBounds([Math.min(...lngs), Math.min(...lats), Math.max(...lngs), Math.max(...lats)], { padding: { top: 70, bottom: 70, left: 50, right: 50 }, duration: 600 });
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  const start = pts[0] ?? { lat: -38.7183, lng: -62.2663 };
  return (
    <View style={[st.wrap, style]} accessible accessibilityLabel="Mapa del viaje">
      <Map style={StyleSheet.absoluteFill} mapStyle={mapStyle} logo={false} compass={false} attributionPosition={{ bottom: 4, right: 4 }}>
        <Camera ref={camera} initialViewState={{ center: ll(start), zoom: 14 }} />
        {!!origin && <ViewAnnotation id="origen" lngLat={ll(origin)} anchor="center"><View style={st.dotA} /></ViewAnnotation>}
        {!!dest && <ViewAnnotation id="destino" lngLat={ll(dest)} anchor="center"><View style={st.dotB} /></ViewAnnotation>}
        {!!driver && <ViewAnnotation id="conductor" lngLat={ll(driver)} anchor="center"><View style={st.car}><Text style={{ fontSize: 17 }}>{vehicle === 'moto' ? '🏍' : '🚗'}</Text></View></ViewAnnotation>}
      </Map>
    </View>
  );
}

const st = StyleSheet.create({
  wrap: { overflow: 'hidden', backgroundColor: '#E8E5DE' },
  dotA: { width: 18, height: 18, borderRadius: 9, backgroundColor: colors.ink, borderWidth: 4, borderColor: '#fff', elevation: 3 },
  dotB: { width: 16, height: 16, backgroundColor: colors.brand, borderWidth: 3, borderColor: '#fff', elevation: 3 },
  car: { width: 38, height: 38, borderRadius: 19, backgroundColor: '#17112B', borderWidth: 3, borderColor: '#fff', alignItems: 'center', justifyContent: 'center', elevation: 5 },
});
