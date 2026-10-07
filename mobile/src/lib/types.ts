// Tipos de la API /api/v1 de Trappi (ver app/routers/mobile_api.py en el backend)

export type Coverage = {
  zoned: boolean;
  covered: boolean | null; // null: falta saber dónde está el cliente
  delivers: boolean;
  distance_km: number | null;
  cost: number | null;
  from_cost: number | null;
  max_km: number | null;
  /** quien entrega: store = el comercio, trappi = la flota de Trappi */
  mode?: 'store' | 'trappi';
  zone?: string | null;
  route_km?: number | null;
  route_estimated?: boolean;
  eta_min?: number | null;
  eta_max?: number | null;
  reason?: string | null;
  pickup_allowed?: boolean;
};

export type Store = {
  id: number;
  slug: string;
  name: string;
  category: string | null;
  description: string | null;
  logo_url: string | null;
  cover_url: string | null;
  emoji: string;
  hue: number;
  featured: boolean;
  is_open: boolean;
  open_text: string | null;
  rating: number | null;
  rating_count: number;
  eta_min: number;
  eta_max: number;
  delivery_enabled: boolean;
  /** quién reparte: la flota de Trappi, los cadetes del local o los dos */
  fleet?: 'trappi' | 'store' | 'mixed' | null;
  delivery_cost: number;
  minimum_order: number;
  coverage: Coverage;
  transfer_alias?: string | null;
  /** medios que acepta (Trappi Delivery: sin transferencia); Mercado Pago va aparte (mp_available) */
  payment_methods?: PaymentMethod[];
  address?: string | null;
  lat?: number | null;
  lng?: number | null;
  whatsapp?: string | null;
  /** mayor descuento vigente en sus productos (para "Hasta 30% OFF"); null si no tiene */
  max_discount?: number | null;
};

export type Product = {
  id: number;
  name: string;
  description: string | null;
  price: number;
  previous_price: number | null;
  image_url: string | null;
  emoji: string;
  hue: number;
  featured: boolean;
  sold_out: boolean;
  customizable: boolean;
  store?: { slug: string; name: string };
};

export type ModifierGroup = {
  id: number;
  name: string;
  required: boolean;
  min_select: number;
  max_select: number;
  options: { id: number; name: string; price_extra: number }[];
};

/** Recomendado para vos: producto real con el motivo (sale de sus propios pedidos) */
export type Recommended = Product & { store: { slug: string; name: string }; reason: string };

export type ProductDetail = Product & { groups: ModifierGroup[]; store: { slug: string; name: string } };

export type Review = { id: number; rating: number; comment: string | null; reply: string | null; created_at: string; author: string };

export type StoreDetail = {
  store: Store;
  menu: { key: string; title: string; products: Product[] }[];
  reviews: Review[];
  rating_summary: { count: number; avg: number; bars: { stars: number; count: number; pct: number }[] };
};

export type City = { id: number; slug: string; name: string; province: string | null; center: { lat: number; lng: number } };

export type Home = {
  banners: { id: number; title: string | null; subtitle: string | null; image_url: string | null; button_text: string | null; link: string | null }[];
  store_categories: { id: number; name: string; emoji: string }[];
  categories: { id: number; slug: string; name: string; image_url: string | null; emoji: string; hue: number }[];
  promos: Product[];
  /** lo más pedido (destacados primero) */
  popular?: Product[];
  stores: Store[];
  /** ciudad del catálogo (multi-ciudad) y las ciudades para elegir (vacío si hay una sola) */
  city?: City | null;
  cities?: City[];
};

export type CartLine = { product_id: number; quantity: number; modifiers: number[]; name: string; unit_price: number; modifiers_text: string | null; store_slug: string; store_name: string };

export type Quote = {
  store: (Store & { mp_available?: boolean }) | null;
  items: { product_id: number; name: string; quantity: number; unit_price: number; line_total: number; modifiers: number[]; modifiers_text: string | null; line_key: string }[];
  dropped: number;
  subtotal: number;
  shipping: number;
  discount: number;
  coupon_error: string | null;
  total: number;
  minimum_order: number;
  /** puntos Trappi: cuántos tiene y cuántos puede usar en este pedido (lo calcula el servidor) */
  points?: { enabled: boolean; balance: number; usable: number; discount: number; reason: string | null };
  points_discount?: number;
};

export type MyPoints = { enabled: false } | {
  enabled: true; points: number; value: number; expiring: number; expiring_at: string | null;
  rules: { pesos_per_point: number; point_value: number; min: number; max_percent: number; months: number };
  history: { kind: string; points: number; note: string | null; created_at: string; order_id: number | null }[];
};

export type OrderStep = { status: string; label: string; done: boolean; current: boolean; at: string | null };

export type Order = {
  id: number;
  status: string;
  status_label: string;
  created_at: string;
  store: { slug: string; name: string; whatsapp: string | null; eta_min: number };
  delivery_method: 'delivery' | 'retiro';
  address: string | null;
  steps: OrderStep[];
  items: { product_id?: number; name: string; quantity: number; unit_price?: number; line_total: number; modifiers_text: string | null; image_url?: string | null; available?: boolean }[];
  subtotal: number;
  shipping: number;
  discount: number;
  total: number;
  whatsapp_url: string | null;
  can_review: boolean;
  review: { rating: number; comment: string | null; reply: string | null } | null;
  final: boolean;
  payment?: OrderPayment;
  /** se lo dice al repartidor al recibir (solo delivery y mientras no se entregó) */
  delivery_pin?: string | null;
  /** pago online pendiente: abrir API_URL + pay_path para ir a Mercado Pago */
  pay_path?: string | null;
};

export type PaymentMethod = 'efectivo' | 'transferencia' | 'mercadopago';

export type OrderPayment = {
  method: PaymentMethod | string;
  label: string;
  paid: boolean;
  transfer_alias: string | null;
  cash_with: number | null;
  change: number | null;
  online?: boolean;
  status?: string | null;
  status_text?: string;
};

export type UserLocation = { lat: number; lng: number; label: string };

/** Cuenta del cliente (entra con un código por email). */
export type Account = {
  id: number; email: string; name: string | null; picture_url: string | null;
  first_name: string; last_name: string; phone: string; address: string; reference: string;
  /** "Recomendado para vos" con sus pedidos (lo puede apagar) */
  personalize?: boolean;
};

/** Trappi AI: tarjetas con datos reales que salieron de las herramientas del backend. */
export type AiCard = { type: 'store'; id: number; store: Store } | { type: 'product'; id: number; product: Product & { store: { slug: string; name: string } } };
export type AiReply = { ok: true; mode: 'ai' | 'basic'; reply: string; cards: AiCard[]; cart_changed: boolean; cart: CartLine[] | null; state: string };
