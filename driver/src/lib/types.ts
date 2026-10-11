// Tipos de la API /api/courier/v1 (ver app/routers/courier_api.py en el backend)

export type Point = { lat?: number; lng?: number };

export type CashStatus = { pending: number; limit: number; available: number; blocked: boolean; online_enabled: boolean };

export type Courier = { id: number; name: string; phone: string; vehicle: string; online: boolean; fleet: 'local' | 'trappi'; store: string | null; cash?: CashStatus };

/** lo que gana por un viaje y de donde sale (base, km, bonos...) */
export type Payout = { total: number; lines: { label: string; amount: number }[]; distance_km?: number | null; multiplier?: number | null };

/** zona con pedidos esperando repartidor (se pinta en rojo en el mapa) */
export type Hotspot = { lat: number; lng: number; orders: number; name: string; radius_m: number };

/** demanda de la ciudad: la calcula el backend en cada pulso */
export type Demand = {
  level: 'normal' | 'alta' | 'muy_alta';
  label: string;
  multiplier: number;
  /** "x1,5" si hay multiplicador; null si no */
  multiplier_text: string | null;
  waiting: number;
  hotspots: Hotspot[];
  /** a qué zona le conviene ir si está libre */
  suggestion: { lat: number; lng: number; km: number; orders: number; text: string } | null;
};

export type RouteStep = { text: string; distance_m: number; lat: number; lng: number; type?: string; modifier?: string };
export type Directions = { km: number; minutes: number; geometry: [number, number][]; steps: RouteStep[]; source: string };
export type RouteInfo = { kind: 'store' | 'customer' | 'hotspot'; to: { lat: number; lng: number } | null; directions: Directions | null };

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
  /** "x1,5" si el viaje tiene multiplicador por demanda */
  multiplier_text?: string | null;
  store: { name: string; address: string | null } & Point;
  dropoff: { address: string | null } & Point;
  to_store_km: number | null;
  trip_km: number | null;
  items: number;
  own_store: boolean;
  paid_online?: boolean;
  /** lo que va a cobrar al cliente (0 si ya pago) */
  collect?: number;
  /** efectivo que le paga al local al retirar (cadetes de Trappi, pedidos en efectivo) */
  pay_store?: number;
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
  /** hay que cargar el código de retiro que te dicta el local (lo tiene en la comanda) */
  pickup_code_required?: boolean;
  /** efectivo que le pagás al local al retirar (0 si no corresponde) */
  pay_store?: number;
  /** reportaste que no pudiste entregar (motivo); null si no */
  failed?: string | null;
  /** motivos para "No pude entregar" (solo en camino) */
  fail_reasons?: { code: string; label: string }[];
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

export type State = { courier: Courier; trip: Trip | null; offer: Offer | null; earnings: Earnings; delivered?: Delivered; demand?: Demand | null };

export type Delivered = { order_id: number; earnings: number; collected?: number };

export type History = Earnings & {
  month: number;
  trips_month: number;
  trips: { order_id: number; store: string; address: string | null; earnings: number; delivered_at: string; km: number | null; payout?: Payout }[];
};
