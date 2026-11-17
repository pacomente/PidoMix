import { router } from 'expo-router';
import { Alert } from 'react-native';

import { confirmReplace } from '@/components/ui';
import { weightLabel } from '@/lib/cart';
import { money } from '@/lib/format';
import type { CartLine, Order } from '@/lib/types';
import { useApp } from '@/state/app-state';

/** «Repetir»: arma el carrito con un pedido anterior (lo usan Mis pedidos y «Pedí de nuevo» del inicio). */
export function useRepeat() {
  const { cart, replaceCart, customer, setCustomer } = useApp();
  // repetir: se arma el carrito con los precios de hoy y la misma dirección; avisa qué ya no está o cambió de precio
  const repeat = (o: Order) => {
    const ok = o.items.filter(i => i.available && i.product_id);
    const lines: CartLine[] = ok.map(i => ({
      product_id: i.product_id!, quantity: i.quantity, modifiers: [], name: i.name,
      unit_price: i.current_price ?? i.unit_price ?? i.line_total / i.quantity,
      modifiers_text: i.grams ? weightLabel(i.grams) : null, store_slug: o.store.slug, store_name: o.store.name, grams: i.grams ?? null,
    }));
    if (!lines.length) { router.push({ pathname: '/store/[slug]', params: { slug: o.store.slug } }); return; }
    const missing = o.items.filter(i => !(i.available && i.product_id)).map(i => i.name);
    const changed = ok.filter(i => i.current_price != null && i.unit_price != null && i.current_price !== i.unit_price)
      .map(i => `${i.name}: ${money(i.unit_price)} → ${money(i.current_price)}`);
    const withOptions = ok.filter(i => i.modifiers_text && !(i.grams && i.modifiers_text === weightLabel(i.grams))).map(i => i.name);
    const go = () => {
      replaceCart(lines);
      if (o.delivery_method === 'delivery' && o.address) setCustomer({ ...customer, address: o.address });
      router.push('/cart');
    };
    const notes = [
      missing.length ? `Ya no están: ${missing.join(', ')}.` : '',
      changed.length ? `Cambiaron de precio:\n${changed.join('\n')}` : '',
      withOptions.length ? `Volvé a elegir las opciones de: ${withOptions.join(', ')}.` : '',
    ].filter(Boolean).join('\n\n');
    const start = () => (notes ? Alert.alert('Repetir pedido', notes, [{ text: 'Cancelar', style: 'cancel' }, { text: 'Seguir', onPress: go }]) : go());
    if (cart.length && cart[0].store_slug !== o.store.slug) confirmReplace(cart[0].store_name, start); else start();
  };
  return repeat;
}
