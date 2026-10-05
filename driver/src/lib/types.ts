// Tipos de la API /api/courier/v1 (ver app/routers/courier_api.py en el backend)

export type Point = { lat?: number; lng?: number };

export type CashStatus = { pending: number; limit: number; available: number; blocked: boolean; online_enabled: boolean };

export type Courier = { id: number; name: string; phone: string; vehicle: string; online: boolean; fleet: 'local' | 'trappi'; store: string | null; cash?: CashStatus };

/** lo que gana por un viaje y de donde sale (base, km, bonos...) */
export type Payout = { total: number; lines: { label: string; amount: number }[]; distance_km?: number | null };

export type CashBox = {
  own_store: boolean; collected: number; remitted: number; pending: number; limit: number; available: number; differences: number; blocked: boolean;
  earnings_pending: number; earnings_paid: number; cash_orders_enabled: boolean; online_orders_enabled: boolean;
  movements: { id: number; kind: string; description: string | null; amount: number; settled: boolean; order_id: number | null; at: string }[];
};

export type Offer = {
  id: number;
  order_id: number;
  expires_in: number;
  seconds: number;
  earnings: number;
  store: { name: string; address: string | null } & Point;
  dropoff: { address: string | null } & Point;
  to_store_km: number | null;
  trip_km: number | null;
  items: number;
  own_store: boolean;
  paid_online?: boolean;
  /** lo que va a cobrar al cliente (0 si ya pago) */
  collect?: number;
  payout?: Payout;
};

export type Trip = {
  order_id: number;
  status: string;
  stage: 'pickup' | 'dropoff';
  ready: boolean;
  earnings: number;
  total: number;
  /** lo que hay que cobrarle al cliente (0 si ya pagó) */
  collect: number;
  payment: TripPayment;
  pin_required: boolean;
  payout?: Payout;
  route_km?: number | null;
  zone?: string | null;
  store: { name: string; address: string | null; phone: string | null; whatsapp: string | null } & Point;
  customer: { name: string; phone: string | null; whatsapp: string | null; address: string | null; reference: string | null } & Point;
  items: { quantity: number; name: string; modifiers_text: string | null }[];
  notes: string | null;
  trip_km: number | null;
};

export type TripPayment = {
  method: 'efectivo' | 'transferencia' | string;
  label: string;
  paid: boolean;
  cash_with: number | null;
  change: number | null;
  /** eligió transferencia y el local todavía no la confirmó */
  transfer_pending: boolean;
};

export type Earnings = { today: number; trips_today: number; week: number; trips_week: number; cash_today?: number };

export type State = { courier: Courier; trip: Trip | null; offer: Offer | null; earnings: Earnings; delivered?: Delivered };

export type Delivered = { order_id: number; earnings: number; collected?: number };

export type History = Earnings & {
  month: number;
  trips_month: number;
  trips: { order_id: number; store: string; address: string | null; earnings: number; delivered_at: string; km: number | null; payout?: Payout }[];
};
