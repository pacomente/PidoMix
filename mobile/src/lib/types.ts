// Tipos de la API /api/v1 de Trappi (ver app/routers/mobile_api.py en el backend)

export type Coverage = {
  zoned: boolean;
  covered: boolean | null; // null: falta saber dónde está el cliente
  delivers: boolean;
  distance_km: number | null;
  cost: number | null;
  from_cost: number | null;
  max_km: number | null;
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
  delivery_cost: number;
  minimum_order: number;
  coverage: Coverage;
  transfer_alias?: string | null;
  address?: string | null;
  lat?: number | null;
  lng?: number | null;
  whatsapp?: string | null;
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

export type ProductDetail = Product & { groups: ModifierGroup[]; store: { slug: string; name: string } };

export type Review = { id: number; rating: number; comment: string | null; reply: string | null; created_at: string; author: string };

export type StoreDetail = {
  store: Store;
  menu: { key: string; title: string; products: Product[] }[];
  reviews: Review[];
  rating_summary: { count: number; avg: number; bars: { stars: number; count: number; pct: number }[] };
};

export type Home = {
  banners: { id: number; title: string | null; subtitle: string | null; image_url: string | null; button_text: string | null; link: string | null }[];
  store_categories: { id: number; name: string; emoji: string }[];
  categories: { id: number; slug: string; name: string; image_url: string | null; emoji: string; hue: number }[];
  promos: Product[];
  stores: Store[];
};

export type CartLine = { product_id: number; quantity: number; modifiers: number[]; name: string; unit_price: number; modifiers_text: string | null; store_slug: string; store_name: string };

export type Quote = {
  store: Store | null;
  items: { product_id: number; name: string; quantity: number; unit_price: number; line_total: number; modifiers: number[]; modifiers_text: string | null; line_key: string }[];
  dropped: number;
  subtotal: number;
  shipping: number;
  discount: number;
  coupon_error: string | null;
  total: number;
  minimum_order: number;
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
  items: { name: string; quantity: number; line_total: number; modifiers_text: string | null }[];
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
};

export type PaymentMethod = 'efectivo' | 'transferencia';

export type OrderPayment = {
  method: PaymentMethod | string;
  label: string;
  paid: boolean;
  transfer_alias: string | null;
  cash_with: number | null;
  change: number | null;
};

export type UserLocation = { lat: number; lng: number; label: string };
