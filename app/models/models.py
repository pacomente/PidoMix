from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional

from sqlalchemy import Boolean, Date, DateTime, Enum as SAEnum, Float, ForeignKey, Index, Integer, Numeric, String, Text, false
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
    store_category: Mapped[Optional[StoreCategory]] = relationship(back_populates="stores")
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
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    online: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    lat: Mapped[Optional[float]] = mapped_column(Float)
    lng: Mapped[Optional[float]] = mapped_column(Float)
    location_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    token_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # al cambiar el PIN se cierran las sesiones
    push_token: Mapped[Optional[str]] = mapped_column(String(512))  # para avisarle de ofertas nuevas
    store: Mapped[Optional["Store"]] = relationship()
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
