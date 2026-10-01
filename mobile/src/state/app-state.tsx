import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import { load, save } from '@/lib/storage';
import type { CartLine, UserLocation } from '@/lib/types';

export type Customer = { first_name: string; last_name: string; phone: string; address: string; reference: string };
export type SavedOrder = { id: number; token: string; store_name: string; created_at: string };

type AddResult = 'added' | 'other_store';

type AppState = {
  ready: boolean;
  location: UserLocation | null;
  setLocation: (loc: UserLocation | null) => void;
  cart: CartLine[];
  cartCount: number;
  addToCart: (line: CartLine, replaceOtherStore?: boolean) => AddResult;
  setQuantity: (index: number, quantity: number) => void;
  clearCart: () => void;
  replaceCart: (lines: CartLine[]) => void;
  orders: SavedOrder[];
  rememberOrder: (order: SavedOrder) => void;
  customer: Customer;
  setCustomer: (c: Customer) => void;
};

const EMPTY_CUSTOMER: Customer = { first_name: '', last_name: '', phone: '', address: '', reference: '' };
const Ctx = createContext<AppState | null>(null);
const sameLine = (a: CartLine, b: CartLine) => a.product_id === b.product_id && [...a.modifiers].sort().join('-') === [...b.modifiers].sort().join('-');

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [location, setLocationState] = useState<UserLocation | null>(null);
  const [cart, setCart] = useState<CartLine[]>([]);
  const [orders, setOrders] = useState<SavedOrder[]>([]);
  const [customer, setCustomerState] = useState<Customer>(EMPTY_CUSTOMER);

  useEffect(() => {
    Promise.all([load<UserLocation | null>('location', null), load<CartLine[]>('cart', []), load<SavedOrder[]>('orders', []), load<Customer>('customer', EMPTY_CUSTOMER)])
      .then(([loc, c, o, cu]) => { setLocationState(loc); setCart(c); setOrders(o); setCustomerState({ ...EMPTY_CUSTOMER, ...cu }); })
      .finally(() => setReady(true));
  }, []);

  // persistencia: cada cambio se guarda en el teléfono
  useEffect(() => { if (ready) save('cart', cart); }, [cart, ready]);
  useEffect(() => { if (ready) save('orders', orders); }, [orders, ready]);

  const setLocation = useCallback((loc: UserLocation | null) => { setLocationState(loc); save('location', loc); }, []);
  const setCustomer = useCallback((c: Customer) => { setCustomerState(c); save('customer', c); }, []);

  const addToCart = useCallback((line: CartLine, replaceOtherStore = false): AddResult => {
    if (!replaceOtherStore && cart.length && cart[0].store_slug !== line.store_slug) return 'other_store';
    setCart(current => {
      const base = current.length && current[0].store_slug !== line.store_slug ? [] : current;
      const i = base.findIndex(x => sameLine(x, line));
      if (i === -1) return [...base, line];
      return base.map((x, j) => (j === i ? { ...x, quantity: Math.min(99, x.quantity + line.quantity) } : x));
    });
    return 'added';
  }, [cart]);

  const setQuantity = useCallback((index: number, quantity: number) => {
    setCart(current => (quantity <= 0 ? current.filter((_, i) => i !== index) : current.map((x, i) => (i === index ? { ...x, quantity: Math.min(99, quantity) } : x))));
  }, []);

  const rememberOrder = useCallback((order: SavedOrder) => setOrders(current => [order, ...current.filter(o => o.id !== order.id)].slice(0, 30)), []);

  const value = useMemo<AppState>(() => ({
    ready, location, setLocation, cart, cartCount: cart.reduce((n, x) => n + x.quantity, 0), addToCart, setQuantity,
    clearCart: () => setCart([]), replaceCart: setCart, orders, rememberOrder, customer, setCustomer,
  }), [ready, location, setLocation, cart, addToCart, setQuantity, orders, rememberOrder, customer, setCustomer]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useApp(): AppState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error('useApp debe usarse dentro de <AppStateProvider>');
  return ctx;
}
