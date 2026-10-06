from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional

from sqlalchemy import Boolean, Date, DateTime, Enum as SAEnum, Float, ForeignKey, Index, Integer, Numeric, String, Text, false, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


class Role(str, Enum):
    SUPERADMIN = "SUPERADMIN"
    STORE_ADMIN = "STORE_ADMIN"
    REPARTIDOR = "REPARTIDOR"
    CLIENTE = "CLIENTE"


class StoreStatus(str, Enum):
    ACTIVA = "ACTIVA"
    INACTIVA = "INACTIVA"
    CERRADA = "CERRADA"


class ProductStatus(str, Enum):
    ACTIVO = "ACTIVO"
    INACTIVO = "INACTIVO"
    SIN_STOCK = "SIN_STOCK"


class OrderStatus(str, Enum):
    PENDIENTE = "PENDIENTE"
    CONFIRMADO = "CONFIRMADO"
    PREPARANDO = "PREPARANDO"
    LISTO = "LISTO"
    EN_CAMINO = "EN_CAMINO"
    ENTREGADO = "ENTREGADO"
    CANCELADO = "CANCELADO"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(SAEnum(Role, name="role_enum"), default=Role.STORE_ADMIN, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    store_id: Mapped[Optional[int]] = mapped_column(ForeignKey("stores.id"), nullable=True, index=True)
    store: Mapped[Optional["Store"]] = relationship(back_populates="admins")


class City(TimestampMixin, Base):
    """Ciudad donde opera Trappi. Comercios, repartidores de la flota, zonas y pedidos son de una ciudad.
    Lo que no tiene ciudad (lo anterior a multi-ciudad) se comparte entre todas."""
    __tablename__ = "cities"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    province: Mapped[Optional[str]] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)  # apagada: no se muestra a los clientes
    center_lat: Mapped[float] = mapped_column(Float)
    center_lng: Mapped[float] = mapped_column(Float)
    radius_km: Mapped[float] = mapped_column(Float, default=25.0, nullable=False)  # alcance para reconocer la ciudad por la ubicacion
    whatsapp: Mapped[Optional[str]] = mapped_column(String(40))  # contacto comercial de la ciudad ("Sumá tu comercio")
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class StoreCategory(Base):
    __tablename__ = "store_categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    stores: Mapped[List["Store"]] = relationship(back_populates="store_category")


class Store(TimestampMixin, Base):
    __tablename__ = "stores"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    slug: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    phone: Mapped[Optional[str]] = mapped_column(String(40))
    whatsapp: Mapped[Optional[str]] = mapped_column(String(40))
    transfer_alias: Mapped[Optional[str]] = mapped_column(String(120))  # alias/CBU que ve el cliente si paga por transferencia
    address: Mapped[Optional[str]] = mapped_column(String(255))
    logo_url: Mapped[Optional[str]] = mapped_column(String(1000))
    logo_public_id: Mapped[Optional[str]] = mapped_column(String(255))
    cover_url: Mapped[Optional[str]] = mapped_column(String(1000))
    cover_public_id: Mapped[Optional[str]] = mapped_column(String(255))
    delivery_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    delivery_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    minimum_order: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    status: Mapped[StoreStatus] = mapped_column(SAEnum(StoreStatus, name="store_status_enum"), default=StoreStatus.ACTIVA, nullable=False)
    featured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rating_avg: Mapped[Decimal] = mapped_column(Numeric(3, 2), default=0, nullable=False)
    rating_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # ubicacion del local (para distancias y zonas de entrega); sin ubicacion se usa el envio fijo
    lat: Mapped[Optional[float]] = mapped_column(Float)
    lng: Mapped[Optional[float]] = mapped_column(Float)
    store_category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("store_categories.id"))
    city_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cities.id"), index=True)  # vacio: comercio anterior a multi-ciudad
    # ---- modelo comercial (lo define solo el superadmin; ver services/plans.py) ----
    plan: Mapped[Optional[str]] = mapped_column(String(30))  # TRAPPI_COMERCIO | TRAPPI_DELIVERY (vacio: comercio anterior sin plan)
    monthly_fee: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))  # abono mensual acordado
    commission_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))  # % de comision por venta acordado
    logistics: Mapped[Optional[str]] = mapped_column(String(10))  # propia | mixta | trappi (vacio: propios primero y despues la flota)
    account_status: Mapped[str] = mapped_column(String(20), default="activo", server_default="activo", nullable=False)  # pendiente | activo | suspendido | desactivado
    plan_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    next_due_date: Mapped[Optional[date]] = mapped_column(Date)  # proximo vencimiento del abono
    owner_name: Mapped[Optional[str]] = mapped_column(String(160))
    contact_email: Mapped[Optional[str]] = mapped_column(String(255))
    commercial_notes: Mapped[Optional[str]] = mapped_column(Text)  # lo acordado por WhatsApp
    # ---- logistica y pagos (lo define el superadmin; ver services/logistics.py y services/finance.py) ----
    fleet_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)  # puede elegir la flota Trappi
    delivery_fee_payer: Mapped[Optional[str]] = mapped_column(String(10))  # CUSTOMER | MERCHANT | TRAPPI | SHARED (vacio: el de la configuracion)
    fee_share_mode: Mapped[Optional[str]] = mapped_column(String(10))  # SHARED: percent (el cliente paga X %) | amount (el cliente paga $X)
    fee_share_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    commission_fixed: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))  # comision fija por venta (ademas del %)
    commission_min: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    commission_max: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    store_category: Mapped[Optional[StoreCategory]] = relationship(back_populates="stores")
    city: Mapped[Optional[City]] = relationship()
    admins: Mapped[List[User]] = relationship(back_populates="store")
    products: Mapped[List["Product"]] = relationship(back_populates="store", cascade="all, delete-orphan")
    hours: Mapped[List["StoreHour"]] = relationship(back_populates="store", cascade="all, delete-orphan")
    orders: Mapped[List["Order"]] = relationship(back_populates="store")
    coupons: Mapped[List["Coupon"]] = relationship(back_populates="store", cascade="all, delete-orphan")
    reviews: Mapped[List["Review"]] = relationship(back_populates="store", cascade="all, delete-orphan")
    sections: Mapped[List["StoreSection"]] = relationship(back_populates="store", cascade="all, delete-orphan", order_by="StoreSection.display_order")
    zones: Mapped[List["DeliveryZone"]] = relationship(back_populates="store", cascade="all, delete-orphan", order_by="DeliveryZone.max_km")


class DeliveryZone(Base):
    """Anillo de cobertura: hasta `max_km` del local el envio cuesta `cost`."""
    __tablename__ = "delivery_zones"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    max_km: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    store: Mapped["Store"] = relationship(back_populates="zones")


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    slug: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    image_url: Mapped[Optional[str]] = mapped_column(String(1000))
    image_public_id: Mapped[Optional[str]] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    products: Mapped[List["Product"]] = relationship(back_populates="category")


class Product(TimestampMixin, Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(180), index=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    previous_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    image_url: Mapped[Optional[str]] = mapped_column(String(1000))
    image_public_id: Mapped[Optional[str]] = mapped_column(String(255))
    status: Mapped[ProductStatus] = mapped_column(SAEnum(ProductStatus, name="product_status_enum"), default=ProductStatus.ACTIVO, nullable=False)
    stock: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    featured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # eliminado por el local: no se muestra en ningun lado, pero queda para los pedidos viejos que lo tienen
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("categories.id"), index=True)
    section_id: Mapped[Optional[int]] = mapped_column(ForeignKey("store_sections.id"), index=True)
    store: Mapped[Store] = relationship(back_populates="products")
    section: Mapped[Optional["StoreSection"]] = relationship(back_populates="products")
    modifier_groups: Mapped[List["ModifierGroup"]] = relationship(back_populates="product", cascade="all, delete-orphan", order_by="ModifierGroup.display_order")
    category: Mapped[Optional[Category]] = relationship(back_populates="products")


class Banner(TimestampMixin, Base):
    __tablename__ = "banners"
    id: Mapped[int] = mapped_column(primary_key=True)
    image_url: Mapped[Optional[str]] = mapped_column(String(1000))
    image_public_id: Mapped[Optional[str]] = mapped_column(String(255))
    title: Mapped[Optional[str]] = mapped_column(String(180))
    subtitle: Mapped[Optional[str]] = mapped_column(String(255))
    button_text: Mapped[Optional[str]] = mapped_column(String(80))
    link: Mapped[Optional[str]] = mapped_column(String(500))
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class StoreHour(Base):
    __tablename__ = "store_hours"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    weekday: Mapped[int] = mapped_column(Integer)
    open_time: Mapped[str] = mapped_column(String(5))
    close_time: Mapped[str] = mapped_column(String(5))
    closed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    store: Mapped[Store] = relationship(back_populates="hours")


class Customer(TimestampMixin, Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    phone: Mapped[str] = mapped_column(String(40))
    email: Mapped[Optional[str]] = mapped_column(String(255))
    address: Mapped[Optional[str]] = mapped_column(String(255))
    reference: Mapped[Optional[str]] = mapped_column(String(255))
    orders: Mapped[List["Order"]] = relationship(back_populates="customer")


class Order(TimestampMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_store_created", "store_id", "created_at"),
        Index("ix_orders_created_at", "created_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("customers.id"), index=True)
    delivery_method: Mapped[str] = mapped_column(String(30))
    payment_method: Mapped[str] = mapped_column(String(30), default="efectivo")  # efectivo | transferencia
    cash_with: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))  # "paga con" (para llevar el vuelto)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime)  # cuando quedo pagado
    paid_by: Mapped[Optional[str]] = mapped_column(String(20))  # local (lo confirmo el comercio) | repartidor (lo cobro al entregar)
    delivery_pin: Mapped[Optional[str]] = mapped_column(String(6))  # el cliente se lo dice al repartidor al recibir
    city_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cities.id"), index=True)  # la del comercio al hacer el pedido
    pickup_code: Mapped[Optional[str]] = mapped_column(String(6))  # el cadete se lo muestra al local para retirar (sale en la comanda)
    pickup_paid: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))  # efectivo que el cadete de la flota le pago al local al retirar
    delivery_failed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)  # el cadete reporto que no pudo entregar
    delivery_fail_reason: Mapped[Optional[str]] = mapped_column(String(160))
    cancel_resolution: Mapped[Optional[str]] = mapped_column(String(20))  # cancelado despues de retirar: returned | store_keeps
    address: Mapped[Optional[str]] = mapped_column(String(255))
    reference: Mapped[Optional[str]] = mapped_column(String(255))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    shipping: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    coupon_id: Mapped[Optional[int]] = mapped_column(ForeignKey("coupons.id"))
    discount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    platform_commission: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    store_commission: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    status: Mapped[OrderStatus] = mapped_column(SAEnum(OrderStatus, name="order_status_enum"), default=OrderStatus.PENDIENTE, nullable=False)
    whatsapp_url: Mapped[Optional[str]] = mapped_column(String(2000))
    lat: Mapped[Optional[float]] = mapped_column(Float)  # donde entregar (si el cliente marco su ubicacion)
    lng: Mapped[Optional[float]] = mapped_column(Float)
    distance_km: Mapped[Optional[float]] = mapped_column(Float)
    # repartidor que lleva el pedido (solo delivery)
    courier_id: Mapped[Optional[int]] = mapped_column(ForeignKey("couriers.id"), index=True)
    courier_assigned_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    courier_pay: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))  # lo que gana el repartidor (se fija al asignarlo)
    # ---- condiciones comerciales vigentes al crear el pedido (no cambian si despues cambia el plan) ----
    plan: Mapped[Optional[str]] = mapped_column(String(30))
    commission_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))  # % aplicado; el importe va en platform_commission
    logistics: Mapped[Optional[str]] = mapped_column(String(10))
    store_net: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))  # lo que le queda al comercio
    trappi_income: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))  # comision + margen de envio si reparte la flota
    # ---- snapshot logistico y financiero (se calcula en el backend al crear el pedido) ----
    delivery_mode: Mapped[Optional[str]] = mapped_column(String(10))  # store | trappi | pickup
    zone_id: Mapped[Optional[int]] = mapped_column(Integer)
    zone_name: Mapped[Optional[str]] = mapped_column(String(120))
    route_km: Mapped[Optional[float]] = mapped_column(Float)  # distancia facturada local -> cliente (por ruta)
    route_minutes: Mapped[Optional[float]] = mapped_column(Float)
    route_source: Mapped[Optional[str]] = mapped_column(String(20))  # osrm | estimate | straight
    operational_km: Mapped[Optional[float]] = mapped_column(Float)  # recorrido real del cadete (analisis interno)
    pricing_snapshot: Mapped[Optional[str]] = mapped_column(Text)  # JSON: tarifa, comision y reglas usadas
    delivery_fee: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))  # costo real del envio
    delivery_fee_customer: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    delivery_fee_merchant: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    delivery_fee_trappi: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    operating_cost: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))  # costo operativo estimado de la flota
    courier_pay_breakdown: Mapped[Optional[str]] = mapped_column(Text)  # JSON: base, km, entrega, bonos, adicionales
    payment_processing_fee: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))  # comision de Mercado Pago
    payment_status: Mapped[Optional[str]] = mapped_column(String(20))  # online: pending | approved | rejected | ...
    cash_pending: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))  # efectivo cobrado sin rendir
    courier_start_lat: Mapped[Optional[float]] = mapped_column(Float)  # donde estaba el cadete al tomar el viaje
    courier_start_lng: Mapped[Optional[float]] = mapped_column(Float)
    courier: Mapped[Optional["Courier"]] = relationship(back_populates="orders")
    customer: Mapped[Optional[Customer]] = relationship(back_populates="orders")
    store: Mapped[Store] = relationship(back_populates="orders")
    items: Mapped[List["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")
    coupon: Mapped[Optional["Coupon"]] = relationship(back_populates="orders")
    review: Mapped[Optional["Review"]] = relationship(back_populates="order", uselist=False, cascade="all, delete-orphan")
    events: Mapped[List["OrderEvent"]] = relationship(back_populates="order", cascade="all, delete-orphan", order_by="OrderEvent.id")

    def status_time(self, status) -> Optional[datetime]:
        """Cuando entro el pedido a un estado (ultima vez), segun el historial."""
        value = getattr(status, "value", status)
        return next((e.created_at for e in reversed(self.events) if e.status == value), None)


class OrderEvent(Base):
    """Historial de cambios de estado: permite ver tiempos por etapa y quien hizo cada cambio."""
    __tablename__ = "order_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    status: Mapped[str] = mapped_column(String(20))
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    order: Mapped[Order] = relationship(back_populates="events")
    user: Mapped[Optional[User]] = relationship()


class Courier(TimestampMixin, Base):
    """Repartidor. Sin store_id es de la flota de Trappi (toma pedidos de cualquier local);
    con store_id es propio de ese local (le llegan primero sus pedidos y solo esos)."""
    __tablename__ = "couriers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(40), unique=True, index=True)  # solo digitos, es el usuario para entrar
    pin_hash: Mapped[str] = mapped_column(String(255))
    vehicle: Mapped[str] = mapped_column(String(20), default="moto")
    store_id: Mapped[Optional[int]] = mapped_column(ForeignKey("stores.id"), index=True)
    city_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cities.id"), index=True)  # flota: en que ciudad trabaja (vacio: cualquiera)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    online: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    lat: Mapped[Optional[float]] = mapped_column(Float)
    lng: Mapped[Optional[float]] = mapped_column(Float)
    location_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    token_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # al cambiar el PIN se cierran las sesiones
    push_token: Mapped[Optional[str]] = mapped_column(String(512))  # para avisarle de ofertas nuevas
    cash_limit: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))  # efectivo maximo sin rendir (vacio: el general)
    cash_orders_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true(), nullable=False)
    online_orders_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true(), nullable=False)
    store: Mapped[Optional["Store"]] = relationship()
    city: Mapped[Optional["City"]] = relationship()
    orders: Mapped[List["Order"]] = relationship(back_populates="courier")


class DeliveryOffer(Base):
    """Oferta de un viaje a un repartidor (estilo Uber): se acepta, se rechaza o vence."""
    __tablename__ = "delivery_offers"
    __table_args__ = (Index("ix_delivery_offers_courier_status", "courier_id", "status"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    courier_id: Mapped[int] = mapped_column(ForeignKey("couriers.id"))
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending, accepted, rejected, expired, cancelled
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    order: Mapped["Order"] = relationship()
    courier: Mapped["Courier"] = relationship()


class PushToken(Base):
    """Telefono que recibe notificaciones push de un pedido (token de Firebase Cloud Messaging)."""
    __tablename__ = "push_tokens"
    __table_args__ = (Index("ux_push_tokens_order_token", "order_id", "token", unique=True),)
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    token: Mapped[str] = mapped_column(String(512))
    platform: Mapped[str] = mapped_column(String(10), default="android")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    product_name: Mapped[str] = mapped_column(String(180))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    quantity: Mapped[int] = mapped_column(Integer)
    modifiers_text: Mapped[Optional[str]] = mapped_column(String(500))
    order: Mapped[Order] = relationship(back_populates="items")


class StoreSection(Base):
    __tablename__ = "store_sections"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    store: Mapped[Store] = relationship(back_populates="sections")
    products: Mapped[List["Product"]] = relationship(back_populates="section")


class ModifierGroup(Base):
    __tablename__ = "modifier_groups"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    min_select: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_select: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    product: Mapped["Product"] = relationship(back_populates="modifier_groups")
    options: Mapped[List["ModifierOption"]] = relationship(back_populates="group", cascade="all, delete-orphan", order_by="ModifierOption.display_order")


class ModifierOption(Base):
    __tablename__ = "modifier_options"
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("modifier_groups.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    price_extra: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    group: Mapped[ModifierGroup] = relationship(back_populates="options")


class Coupon(TimestampMixin, Base):
    __tablename__ = "coupons"
    __table_args__ = (Index("ix_coupons_store_code", "store_id", "code", unique=True),)
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    code: Mapped[str] = mapped_column(String(40))
    discount_type: Mapped[str] = mapped_column(String(10), default="percent")  # percent | fixed
    discount_value: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    min_order: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    max_uses: Mapped[Optional[int]] = mapped_column(Integer)
    uses_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    store: Mapped[Store] = relationship(back_populates="coupons")
    orders: Mapped[List["Order"]] = relationship(back_populates="coupon")


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), unique=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[Optional[str]] = mapped_column(Text)
    reply: Mapped[Optional[str]] = mapped_column(Text)  # respuesta publica del local
    replied_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)  # moderada: no cuenta ni se muestra
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    order: Mapped[Order] = relationship(back_populates="review")
    store: Mapped[Store] = relationship(back_populates="reviews")


class Setting(Base):
    __tablename__ = "settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True)
    value: Mapped[Optional[str]] = mapped_column(Text)


class StorePlanChange(Base):
    """Historial de planes y condiciones de cada comercio (quien y cuando los cambio)."""
    __tablename__ = "store_plan_changes"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    from_plan: Mapped[Optional[str]] = mapped_column(String(30))
    to_plan: Mapped[Optional[str]] = mapped_column(String(30))
    monthly_fee: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    commission_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    logistics: Mapped[Optional[str]] = mapped_column(String(10))
    note: Mapped[Optional[str]] = mapped_column(String(255))
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    user: Mapped[Optional[User]] = relationship()


class SubscriptionPayment(Base):
    """Abono mensual de un comercio: se registra a mano (sin cobro automatico)."""
    __tablename__ = "subscription_payments"
    __table_args__ = (Index("ux_subscription_store_period", "store_id", "period", unique=True),)
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    period: Mapped[str] = mapped_column(String(7))  # AAAA-MM
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(String(10), default="pendiente", nullable=False)  # pendiente | pagado
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    note: Mapped[Optional[str]] = mapped_column(String(255))
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


# ==================== logistica: zonas de la flota Trappi ====================

class LogisticsZone(TimestampMixin, Base):
    """Zona de cobertura de la flota Trappi (radio o poligono) con su tarifa por km."""
    __tablename__ = "logistics_zones"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[Optional[str]] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    color: Mapped[str] = mapped_column(String(9), default="#6C2BD9", nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # si se superponen, gana la de mayor prioridad
    kind: Mapped[str] = mapped_column(String(10), default="radius", nullable=False)  # radius | polygon
    center_lat: Mapped[Optional[float]] = mapped_column(Float)
    center_lng: Mapped[Optional[float]] = mapped_column(Float)
    radius_km: Mapped[Optional[float]] = mapped_column(Float)
    polygon: Mapped[Optional[str]] = mapped_column(Text)  # JSON [[lat, lng], ...]
    max_km: Mapped[Optional[float]] = mapped_column(Float)  # distancia maxima por ruta local -> cliente
    base_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    included_km: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    per_km: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    min_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    max_fee: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    rounding: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)  # redondear hacia arriba a multiplos de $X
    days: Mapped[str] = mapped_column(String(7), default="0123456", nullable=False)  # 0 = lunes
    start_time: Mapped[Optional[str]] = mapped_column(String(5))  # HH:MM (vacio: todo el dia)
    end_time: Mapped[Optional[str]] = mapped_column(String(5))
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # se borra logicamente: los pedidos la referencian
    city_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cities.id"), index=True)  # vacio: vale para todas


class LogisticsZoneVersion(Base):
    """Historial de tarifas y geometria de cada zona (cada cambio guarda una copia)."""
    __tablename__ = "logistics_zone_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    zone_id: Mapped[int] = mapped_column(ForeignKey("logistics_zones.id"), index=True)
    data: Mapped[str] = mapped_column(Text)  # JSON con la zona completa
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    user: Mapped[Optional[User]] = relationship()


# ==================== pagos online (Mercado Pago) ====================

class MercadoPagoAccount(Base):
    """Cuenta de Mercado Pago de un comercio conectada por OAuth (tokens cifrados)."""
    __tablename__ = "mp_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), unique=True, index=True)
    mp_user_id: Mapped[str] = mapped_column(String(40), index=True)
    nickname: Mapped[Optional[str]] = mapped_column(String(120))
    access_token_enc: Mapped[Optional[str]] = mapped_column(Text)
    refresh_token_enc: Mapped[Optional[str]] = mapped_column(Text)
    public_key: Mapped[Optional[str]] = mapped_column(String(120))
    live_mode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(15), default="connected", nullable=False)  # connected | disconnected | error
    connected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_error: Mapped[Optional[str]] = mapped_column(String(255))


class Payment(Base):
    """Pago online de un pedido. El estado solo lo cambia la consulta a Mercado Pago (nunca el navegador)."""
    __tablename__ = "payments"
    __table_args__ = (Index("ux_payments_provider_id", "provider", "provider_payment_id", unique=True),)
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    provider: Mapped[str] = mapped_column(String(20), default="mercadopago", nullable=False)
    provider_payment_id: Mapped[Optional[str]] = mapped_column(String(40))
    preference_id: Mapped[Optional[str]] = mapped_column(String(80))
    checkout_url: Mapped[Optional[str]] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="ARS", nullable=False)
    marketplace_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    seller_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    processing_fee: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    refunded_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    payment_method: Mapped[Optional[str]] = mapped_column(String(40))
    external_status: Mapped[Optional[str]] = mapped_column(String(60))  # status/status_detail de Mercado Pago
    live_mode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    rejected_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    refunded_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    order: Mapped["Order"] = relationship()


class PaymentEvent(Base):
    """Cada notificacion recibida (webhook), para no procesar dos veces el mismo evento."""
    __tablename__ = "payment_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(20), default="mercadopago", nullable=False)
    event_key: Mapped[str] = mapped_column(String(160), unique=True)
    topic: Mapped[Optional[str]] = mapped_column(String(40))
    resource_id: Mapped[Optional[str]] = mapped_column(String(60))
    payload: Mapped[Optional[str]] = mapped_column(Text)
    result: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


# ==================== dinero: movimientos, rendiciones y liquidaciones ====================

class LedgerEntry(Base):
    """Movimiento de dinero de una cuenta. Nunca se borra: los errores se corrigen con ajustes.

    Cuentas (con el signo desde el punto de vista de Trappi):
      merchant          + Trappi le debe al comercio / - el comercio le debe a Trappi
      courier_cash      + efectivo que el cadete tiene en su poder y debe rendir
      courier_earnings  + lo que Trappi le debe al cadete por sus viajes
    """
    __tablename__ = "ledger_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    account: Mapped[str] = mapped_column(String(20), index=True)
    store_id: Mapped[Optional[int]] = mapped_column(ForeignKey("stores.id"), index=True)
    courier_id: Mapped[Optional[int]] = mapped_column(ForeignKey("couriers.id"), index=True)
    order_id: Mapped[Optional[int]] = mapped_column(ForeignKey("orders.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    description: Mapped[Optional[str]] = mapped_column(String(255))
    dedupe_key: Mapped[Optional[str]] = mapped_column(String(160), unique=True)  # evita duplicar el mismo movimiento
    settled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    merchant_settlement_id: Mapped[Optional[int]] = mapped_column(ForeignKey("merchant_settlements.id"), index=True)
    courier_settlement_id: Mapped[Optional[int]] = mapped_column(ForeignKey("courier_settlements.id"), index=True)
    remittance_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cash_remittances.id"), index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    order: Mapped[Optional["Order"]] = relationship()


class CashRemittance(Base):
    """Rendicion de efectivo de un repartidor (no se puede borrar)."""
    __tablename__ = "cash_remittances"
    id: Mapped[int] = mapped_column(primary_key=True)
    courier_id: Mapped[int] = mapped_column(ForeignKey("couriers.id"), index=True)
    expected: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    received: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    difference: Mapped[Decimal] = mapped_column(Numeric(12, 2))  # recibido - esperado
    order_ids: Mapped[Optional[str]] = mapped_column(Text)  # JSON
    receipt: Mapped[Optional[str]] = mapped_column(String(1000))  # comprobante (link o referencia)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    courier: Mapped["Courier"] = relationship()
    user: Mapped[Optional[User]] = relationship()


class MerchantSettlement(Base):
    """Liquidacion a un comercio (lo cobrado en efectivo por la flota, menos comisiones)."""
    __tablename__ = "merchant_settlements"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))  # + Trappi paga al comercio / - el comercio paga a Trappi
    entries_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(12), default="pending", nullable=False)  # pending | processing | paid | failed | cancelled
    method: Mapped[Optional[str]] = mapped_column(String(40))
    receipt: Mapped[Optional[str]] = mapped_column(String(1000))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    store: Mapped["Store"] = relationship()


class CourierSettlement(Base):
    """Liquidacion de ganancias a un repartidor. El pago se hace por fuera (transferencia) y se registra aca."""
    __tablename__ = "courier_settlements"
    id: Mapped[int] = mapped_column(primary_key=True)
    courier_id: Mapped[int] = mapped_column(ForeignKey("couriers.id"), index=True)
    earnings: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    bonuses: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    adjustments: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    # efectivo sin rendir que se le desconto (en vez de que lo deposite); queda como rendicion compensada
    cash_offset: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, server_default="0", nullable=False)
    remittance_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cash_remittances.id"))
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    entries_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    method: Mapped[Optional[str]] = mapped_column(String(40))
    account_masked: Mapped[Optional[str]] = mapped_column(String(120))  # CVU/CBU usado (enmascarado)
    payout_account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("courier_payout_accounts.id"))
    status: Mapped[str] = mapped_column(String(12), default="pending", nullable=False)
    receipt: Mapped[Optional[str]] = mapped_column(String(1000))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    courier: Mapped["Courier"] = relationship()


class CourierPayoutAccount(Base):
    """Datos de cobro de un repartidor. Cada cambio crea una version nueva (historial); CBU/CVU cifrados."""
    __tablename__ = "courier_payout_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    courier_id: Mapped[int] = mapped_column(ForeignKey("couriers.id"), index=True)
    holder: Mapped[str] = mapped_column(String(160))
    provider: Mapped[Optional[str]] = mapped_column(String(80))  # banco o billetera
    cbu_enc: Mapped[Optional[str]] = mapped_column(Text)
    cvu_enc: Mapped[Optional[str]] = mapped_column(Text)
    last4: Mapped[Optional[str]] = mapped_column(String(4))
    alias: Mapped[Optional[str]] = mapped_column(String(60))
    account_type: Mapped[Optional[str]] = mapped_column(String(30))  # caja de ahorro, cuenta corriente, billetera
    verification: Mapped[str] = mapped_column(String(12), default="pendiente", nullable=False)  # pendiente | verificado | rechazado
    current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class AuditLog(Base):
    """Registro de operaciones sensibles: tarifas, comisiones, cuentas de cobro, liquidaciones, rendiciones, reembolsos."""
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(60))
    entity: Mapped[str] = mapped_column(String(40), index=True)
    entity_id: Mapped[Optional[str]] = mapped_column(String(40))
    amount_old: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    amount_new: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    old_value: Mapped[Optional[str]] = mapped_column(Text)
    new_value: Mapped[Optional[str]] = mapped_column(Text)
    reason: Mapped[Optional[str]] = mapped_column(String(255))
    ip: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    user: Mapped[Optional[User]] = relationship()
