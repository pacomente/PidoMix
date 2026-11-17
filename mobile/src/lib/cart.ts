import type { CartLine, Quote, UserLocation } from './types';

/** Cuerpo para /cart/quote y /orders a partir del carrito guardado en el teléfono. */
export function quoteBody(cart: CartLine[], location: UserLocation | null, extra: { delivery_method?: string; coupon?: string; use_points?: boolean; use_voucher?: boolean } = {}) {
  return {
    items: cart.map(l => ({ product_id: l.product_id, quantity: l.quantity, modifiers: l.modifiers, ...(l.grams ? { grams: l.grams } : {}) })),
    lat: location?.lat ?? null,
    lng: location?.lng ?? null,
    delivery_method: extra.delivery_method ?? 'delivery',
    coupon: extra.coupon ?? '',
    use_points: !!extra.use_points,
    use_voucher: extra.use_voucher ?? true,
  };
}

export const lineKey = (productId: number, modifiers: number[], grams?: number | null) =>
  `${productId}:${[...modifiers].sort((a, b) => a - b).join('-')}${grams ? `@${grams}` : ''}`;

/** Actualiza precios con lo que dice el servidor y saca lo que ya no se puede pedir. */
export function syncCart(cart: CartLine[], quote: Quote): CartLine[] {
  const fresh = new Map(quote.items.map(i => [lineKey(i.product_id, i.modifiers, i.grams), i]));
  return cart.flatMap(l => {
    const q = fresh.get(lineKey(l.product_id, l.modifiers, l.grams));
    return q ? [{ ...l, name: q.name, unit_price: q.unit_price, modifiers_text: q.modifiers_text, grams: q.grams ?? l.grams }] : [];
  });
}

/** 750 -> "750 g", 1500 -> "1,5 kg" */
export function weightLabel(grams: number): string {
  if (grams < 1000) return `${grams} g`;
  return `${String(+(grams / 1000).toFixed(3)).replace('.', ',')} kg`;
}
