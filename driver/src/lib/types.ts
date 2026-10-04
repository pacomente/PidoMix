// Tipos de la API /api/courier/v1 (ver app/routers/courier_api.py en el backend)

export type Point = { lat?: number; lng?: number };

export type Courier = { id: number; name: string; phone: string; vehicle: string; online: boolean; fleet: 'local' | 'trappi'; store: string | null };

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
};

export type Trip = {
  order_id: number;
  status: string;
  stage: 'pickup' | 'dropoff';
  ready: boolean;
  earnings: number;
  total: number;
  collect: number;
  store: { name: string; address: string | null; phone: string | null; whatsapp: string | null } & Point;
  customer: { name: string; phone: string | null; whatsapp: string | null; address: string | null; reference: string | null } & Point;
  items: { quantity: number; name: string; modifiers_text: string | null }[];
  notes: string | null;
  trip_km: number | null;
};

export type Earnings = { today: number; trips_today: number; week: number; trips_week: number };

export type State = { courier: Courier; trip: Trip | null; offer: Offer | null; earnings: Earnings; delivered?: { order_id: number; earnings: number } };

export type History = Earnings & {
  month: number;
  trips_month: number;
  trips: { order_id: number; store: string; address: string | null; earnings: number; delivered_at: string; km: number | null }[];
};
