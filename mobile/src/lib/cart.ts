import type { CartLine, Quote, UserLocation } from './types';

/** Cuerpo para /cart/quote y /orders a partir del carrito guardado en el teléfono. */
export function quoteBody(cart: CartLine[], location: UserLocation | null, extra: { delivery_method?: string; coupon?: string } = {}) {
  return {
    items: cart.map(l => ({ product_id: l.product_id, quantity: l.quantity, modifiers: l.modifiers })),
    lat: location?.lat ?? null,
    lng: location?.lng ?? null,
    delivery_method: extra.delivery_method ?? 'delivery',
    coupon: extra.coupon ?? '',
  };
}

const key = (productId: number, modifiers: number[]) => `${productId}:${[...modifiers].sort((a, b) => a - b).join('-')}`;

/** Actualiza precios con lo que dice el servidor y saca lo que ya no se puede pedir. */
export function syncCart(cart: CartLine[], quote: Quote): CartLine[] {
  const fresh = new Map(quote.items.map(i => [key(i.product_id, i.modifiers), i]));
  return cart.flatMap(l => {
    const q = fresh.get(key(l.product_id, l.modifiers));
    return q ? [{ ...l, name: q.name, unit_price: q.unit_price, modifiers_text: q.modifiers_text }] : [];
  });
}
