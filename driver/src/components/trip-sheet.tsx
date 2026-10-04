import Ionicons from '@expo/vector-icons/Ionicons';
import { useState } from 'react';
import { Alert, Linking, Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { Button } from '@/components/ui';
import { km, money } from '@/lib/format';
import { colors, radius } from '@/lib/theme';
import type { Point, Trip } from '@/lib/types';

function navUrl(p: Point, address: string | null, app: 'google' | 'waze') {
  const has = p.lat !== undefined && p.lng !== undefined;
  if (app === 'waze') return has ? `https://waze.com/ul?ll=${p.lat},${p.lng}&navigate=yes` : `https://waze.com/ul?q=${encodeURIComponent(address || '')}&navigate=yes`;
  return `https://www.google.com/maps/dir/?api=1&travelmode=driving&destination=${has ? `${p.lat},${p.lng}` : encodeURIComponent(address || '')}`;
}

function Action({ icon, label, onPress }: { icon: React.ComponentProps<typeof Ionicons>['name']; label: string; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [st.action, pressed && { opacity: 0.7 }]} accessibilityRole="button" accessibilityLabel={label}>
      <View style={st.actionIcon}><Ionicons name={icon} size={20} color={colors.ink} /></View>
      <Text style={st.actionText}>{label}</Text>
    </Pressable>
  );
}

/** Panel inferior del viaje en curso: primero retirar en el local, después entregar al cliente. */
export function TripSheet({ trip, busy, onPickup, onDeliver, onRelease }: { trip: Trip; busy: boolean; onPickup: () => void; onDeliver: () => void; onRelease: () => void }) {
  const [open, setOpen] = useState(false);
  const pickup = trip.stage === 'pickup';
  const place = pickup ? trip.store : trip.customer;
  const contact = pickup ? trip.store.whatsapp : trip.customer.whatsapp;
  const phone = pickup ? trip.store.phone : trip.customer.phone;

  const confirm = (title: string, msg: string, go: () => void) => {
    if (Platform.OS === 'web') { if (window.confirm(`${title}\n\n${msg}`)) go(); return; } // Alert no tiene botones en la web
    Alert.alert(title, msg, [{ text: 'Cancelar', style: 'cancel' }, { text: 'Sí, confirmar', onPress: go }]);
  };

  return (
    <View style={st.sheet}>
      <View style={st.grab} />
      <View style={st.row}>
        <View style={[st.badge, !pickup && { backgroundColor: colors.money }]}><Text style={st.badgeText}>{pickup ? 'RETIRO' : 'ENTREGA'}</Text></View>
        <Text style={st.order}>Pedido #{trip.order_id}</Text>
        <Text style={st.earn}>{money(trip.earnings)}</Text>
      </View>
      <Text style={st.title} numberOfLines={1}>{pickup ? trip.store.name : trip.customer.name}</Text>
      <Text style={st.address} numberOfLines={2}>{place.address || 'Sin dirección'}{!pickup && trip.customer.reference ? ` · ${trip.customer.reference}` : ''}</Text>
      {pickup && <Text style={[st.ready, trip.ready && { color: colors.money }]}>{trip.ready ? '✓ El pedido está listo para retirar' : '⏳ El local lo está preparando'}</Text>}
      {!pickup && (
        <View style={st.collect}>
          <Text style={st.collectLabel}>Cobrar al cliente</Text>
          <Text style={st.collectValue}>{money(trip.collect)}</Text>
          <Text style={st.collectHint}>Salvo que ya haya pagado por transferencia.</Text>
        </View>
      )}

      <View style={st.actions}>
        <Action icon="navigate" label="Google Maps" onPress={() => Linking.openURL(navUrl(place, place.address, 'google'))} />
        <Action icon="car-sport-outline" label="Waze" onPress={() => Linking.openURL(navUrl(place, place.address, 'waze'))} />
        {!!contact && <Action icon="logo-whatsapp" label="WhatsApp" onPress={() => Linking.openURL(contact)} />}
        {!!phone && <Action icon="call-outline" label="Llamar" onPress={() => Linking.openURL(`tel:${phone}`)} />}
      </View>

      <Pressable onPress={() => setOpen(o => !o)} style={st.detailsToggle}>
        <Text style={st.detailsText}>{trip.items.reduce((n, i) => n + i.quantity, 0)} productos{trip.trip_km ? ` · ${km(trip.trip_km)} de viaje` : ''}</Text>
        <Ionicons name={open ? 'chevron-down' : 'chevron-up'} size={18} color={colors.muted} />
      </Pressable>
      {open && (
        <ScrollView style={{ maxHeight: 160 }}>
          {trip.items.map((it, i) => <Text key={i} style={st.item}>{it.quantity}× {it.name}{it.modifiers_text ? ` (+ ${it.modifiers_text})` : ''}</Text>)}
          {!!trip.notes && <Text style={st.notes}>💬 {trip.notes}</Text>}
        </ScrollView>
      )}

      {pickup ? (
        <>
          <Button big title="Retiré el pedido" loading={busy} onPress={() => confirm('¿Ya tenés el pedido?', `Confirmá que retiraste el pedido #${trip.order_id} de ${trip.store.name}. Al cliente le avisamos que va en camino.`, onPickup)} />
          <Pressable onPress={() => confirm('¿No podés llevarlo?', 'El pedido se le ofrece a otro repartidor.', onRelease)} style={st.release}><Text style={st.releaseText}>No puedo llevar este pedido</Text></Pressable>
        </>
      ) : (
        <Button big variant="money" title="Entregué el pedido" loading={busy} onPress={() => confirm('¿Entregaste el pedido?', `Confirmá la entrega a ${trip.customer.name}${trip.collect ? ` y que cobraste ${money(trip.collect)}` : ''}.`, onDeliver)} />
      )}
    </View>
  );
}

const st = StyleSheet.create({
  sheet: { backgroundColor: '#fff', borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, padding: 18, paddingTop: 10, gap: 6, shadowColor: '#000', shadowOpacity: 0.25, shadowRadius: 16, elevation: 12 },
  grab: { alignSelf: 'center', width: 40, height: 5, borderRadius: 3, backgroundColor: '#DDD', marginBottom: 8 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  badge: { backgroundColor: colors.ink, paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6 },
  badgeText: { color: '#fff', fontWeight: '800', fontSize: 11.5, letterSpacing: 0.6 },
  order: { color: colors.muted, fontWeight: '700', flex: 1 },
  earn: { fontWeight: '900', fontSize: 18, color: colors.money },
  title: { fontSize: 24, fontWeight: '900', color: colors.ink, letterSpacing: -0.4, marginTop: 4 },
  address: { fontSize: 15.5, color: '#333' },
  ready: { fontWeight: '700', color: '#9A6A00', marginTop: 2 },
  collect: { marginTop: 6, padding: 12, borderRadius: radius.sm, backgroundColor: '#F2FBF6', borderWidth: 1, borderColor: '#CDEFDB' },
  collectLabel: { color: '#0B6B45', fontWeight: '700' },
  collectValue: { fontSize: 28, fontWeight: '900', color: colors.ink },
  collectHint: { color: colors.muted, fontSize: 12.5 },
  actions: { flexDirection: 'row', justifyContent: 'space-around', marginVertical: 10 },
  action: { alignItems: 'center', gap: 4, minWidth: 70 },
  actionIcon: { width: 46, height: 46, borderRadius: 23, backgroundColor: '#F1F1F1', alignItems: 'center', justifyContent: 'center' },
  actionText: { fontSize: 12.5, fontWeight: '600', color: colors.ink },
  detailsToggle: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: 8, borderTopWidth: 1, borderTopColor: colors.line },
  detailsText: { color: colors.muted, fontWeight: '600' },
  item: { fontSize: 15, color: colors.ink, paddingVertical: 2 },
  notes: { marginTop: 6, padding: 10, borderRadius: 8, backgroundColor: '#FFF4D6', color: '#6B4A00', fontWeight: '700' },
  release: { alignItems: 'center', paddingVertical: 10 },
  releaseText: { color: colors.danger, fontWeight: '700' },
});
