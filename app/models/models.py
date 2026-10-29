from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional

from sqlalchemy import Boolean, Date, DateTime, Enum as SAEnum, Float, ForeignKey, Index, Integer, LargeBinary, Numeric, String, Text, false, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


class Role(str, Enum):
    SUPERADMIN = "SUPERADMIN"
    STORE_ADMIN = "STORE_ADMIN"
    REPARTIDOR = "REPARTIDOR"
    CLIENTE = "CLIENTE"
    RIDE_ADMIN = "RIDE_ADMIN"  # empresa de viajes (remises, taxis, motos): solo ve su panel /empresa
    STORE_STAFF = "STORE_STAFF"  # personal del local (cocina, mostrador): solo comandas y pedidos, sin plata ni configuracion


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
    ride_company_id: Mapped[Optional[int]] = mapped_column(ForeignKey("ride_companies.id"), nullable=True, index=True)  # RIDE_ADMIN
    # sube al cambiar la contrasena o la verificacion en dos pasos: cierra las sesiones abiertas en otros dispositivos
    session_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    # verificacion en dos pasos (TOTP, Google Authenticator y similares); el secreto va cifrado
    totp_secret_enc: Mapped[Optional[str]] = mapped_column(Text)
    totp_enabled_at: Mapped[Optional[datetime]] = mapped_column(DateTime)  # vacio: no activada (o a medio configurar)
    totp_last_step: Mapped[Optional[int]] = mapped_column(Integer)  # ultimo codigo usado: no se puede reusar
    recovery_codes: Mapped[Optional[str]] = mapped_column(Text)  # JSON con los hashes de los codigos de recuperacion sin usar
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
    # varios pedidos a la vez para los repartidores propios del local (lo decide el local; la flota de Trappi usa el panel general)
    own_batch: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    own_batch_max: Mapped[int] = mapped_column(Integer, default=2, server_default="2", nullable=False)
    own_batch_km: Mapped[float] = mapped_column(Float, default=1.5, server_default="1.5", nullable=False)
    # "Estoy a full": minutos de mas que ve el cliente hasta busy_until, o pedidos pausados hasta paused_until (UTC)
    busy_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    busy_until: Mapped[Optional[datetime]] = mapped_column(DateTime)
    paused_until: Mapped[Optional[datetime]] = mapped_column(DateTime)
    # avisos al dueño (notificacion al celular y, si esta conectado, WhatsApp)
    alert_new_order: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true(), nullable=False)
    alert_late: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true(), nullable=False)
    alert_summary: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true(), nullable=False)
    summary_sent_on: Mapped[Optional[date]] = mapped_column(Date)
    # dias puntuales cerrado (feriados, vacaciones): JSON [{"date": "2026-12-25", "reason": "Navidad"}]
    closed_dates: Mapped[Optional[str]] = mapped_column(Text)
    panel_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime)  # ultima vez que comandas o el panel consultaron pedidos
    unattended_warned_on: Mapped[Optional[date]] = mapped_column(Date)  # aviso "abierto pero nadie mira los pedidos"
    # ---- caja (punto de venta) ----
    pos_enabled: Mapped[Optional[bool]] = mapped_column(Boolean)  # vacio: lo que diga la configuracion general
    pos_commission_percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))  # vacio: la general
    table_commission_percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))  # pedidos desde la mesa (QR); vacio: la general
    pos_monthly_fee: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))  # vacio: la general
    pos_device_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)  # subirlo desvincula las cajas
    pos_counter_code: Mapped[Optional[str]] = mapped_column(String(16), unique=True)  # QR del mostrador para pagar con Puntos Trappi
    pos_screen_code: Mapped[Optional[str]] = mapped_column(String(16), unique=True)  # link del llamador (pantalla "pedido listo" para la tele)
    pos_features: Mapped[Optional[str]] = mapped_column(Text)  # JSON: funciones de la caja que Trappi le habilitó (mesas, llamador, promos...)
    # ---- agente de WhatsApp del local (lo habilita el superadmin; el local conecta su numero con Meta) ----
    wa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    wa_phone_id: Mapped[Optional[str]] = mapped_column(String(40), unique=True)  # phone_number_id de Meta
    wa_waba_id: Mapped[Optional[str]] = mapped_column(String(40))
    wa_number: Mapped[Optional[str]] = mapped_column(String(30))  # el numero que ve el cliente
    wa_token: Mapped[Optional[str]] = mapped_column(Text)  # cifrado (nunca se muestra)
    wa_connected_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    wa_agent_on: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true(), nullable=False)  # el dueño lo puede pausar
    wa_alerts: Mapped[Optional[str]] = mapped_column(Text)  # JSON: avisos que quiere el dueño (vacio: todos)
    wa_trappi: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)  # el numero esta en la cuenta de Trappi: Trappi le paga a Meta
    wa_message_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))  # cargo por mensaje para este local (vacio: el de la configuracion)
    # ---- menu en 3D / "Ver en tu mesa" (lo habilita el superadmin; el local sube el modelo de cada plato) ----
    ar_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    # ---- tarjeta de sellos (la paga el local): cada pedido entregado suma un sello; al completarla, un premio ----
    stamps_goal: Mapped[Optional[int]] = mapped_column(Integer)  # sellos para el premio (vacio: apagada)
    stamps_reward_type: Mapped[str] = mapped_column(String(10), default="percent", server_default="percent", nullable=False)  # percent | fixed
    stamps_reward_value: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, server_default="0", nullable=False)
    stamps_min_order: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, server_default="0", nullable=False)  # pedido minimo para sumar
    weekly_report: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true(), nullable=False)  # resumen semanal por mail
    weekly_sent_on: Mapped[Optional[date]] = mapped_column(Date)
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

    @property
    def busy_extra(self) -> int:
        """Minutos de demora que sumo el local con "Estoy a full" (0 si no esta activo)."""
        return (self.busy_minutes or 0) if self.busy_until and self.busy_until > datetime.utcnow() else 0

    @property
    def prep_minutes(self) -> int:
        """Demora que ve el cliente: la habitual mas la de "Estoy a full"."""
        return (self.estimated_minutes or 30) + self.busy_extra

    @property
    def closures(self) -> list:
        import json
        try:
            return sorted((d for d in json.loads(self.closed_dates or '[]') if d.get('date')), key=lambda d: d['date'])
        except (ValueError, TypeError, AttributeError):
            return []

    def closed_on(self, day) -> str | None:
        """El motivo si el local cierra ese dia puntual (feriado, vacaciones); None si no."""
        iso = day.isoformat() if hasattr(day, 'isoformat') else str(day)
        return next(((d.get('reason') or 'Cerrado') for d in self.closures if d['date'] == iso), None)

    @property
    def is_paused(self) -> bool:
        return bool(self.paused_until and self.paused_until > datetime.utcnow())


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
    stock_before_out: Mapped[Optional[int]] = mapped_column(Integer)  # lo que habia al marcarlo agotado desde comandas
    out_until: Mapped[Optional[datetime]] = mapped_column(DateTime)  # "agotado hasta mañana": vuelve solo a esta hora (UTC)
    featured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # eliminado por el local: no se muestra en ningun lado, pero queda para los pedidos viejos que lo tienen
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    barcode: Mapped[Optional[str]] = mapped_column(String(40), index=True)  # para el lector de la caja
    # modelo 3D del plato (Cloudinary, archivo "raw"): .glb para Android y la web, .usdz para iPhone
    model_url: Mapped[Optional[str]] = mapped_column(String(1000))
    model_public_id: Mapped[Optional[str]] = mapped_column(String(255))
    model_ios_url: Mapped[Optional[str]] = mapped_column(String(1000))
    model_ios_public_id: Mapped[Optional[str]] = mapped_column(String(255))
    model_visible: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true(), nullable=False)
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


class ClientAccount(Base):
    """Cuenta de un cliente. Entra con un codigo de un solo uso que le llega por email (asi el email queda verificado).

    Los datos de cada pedido (nombre, telefono, direccion) quedan copiados en Customer/Order:
    si la cuenta se elimina, los pedidos siguen para la contabilidad pero sin el enlace a la cuenta.
    """
    __tablename__ = "client_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    name: Mapped[Optional[str]] = mapped_column(String(160))
    first_name: Mapped[Optional[str]] = mapped_column(String(100))
    last_name: Mapped[Optional[str]] = mapped_column(String(100))
    picture_url: Mapped[Optional[str]] = mapped_column(String(1000))
    phone: Mapped[Optional[str]] = mapped_column(String(40))
    address: Mapped[Optional[str]] = mapped_column(String(255))
    reference: Mapped[Optional[str]] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true(), nullable=False)  # bloqueada por Trappi: no puede pedir
    blocked_reason: Mapped[Optional[str]] = mapped_column(String(255))
    session_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)  # sube al bloquear o salir de todos lados
    terms_version: Mapped[Optional[str]] = mapped_column(String(20))  # version de terminos y privacidad que acepto
    terms_accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    # "Recomendado para vos" con sus pedidos, favoritos y calificaciones (lo puede apagar desde su cuenta)
    personalize: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true(), nullable=False)
    # novedades y promociones por email o notificacion: las cuentas nuevas arrancan prendidas (se avisa al ingresar) y se apagan desde Mi cuenta o el link de cada email
    marketing_opt_in: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    # "Invitá a un amigo": su codigo, quien lo invito y cuando se pagaron los puntos de la invitacion
    referral_code: Mapped[Optional[str]] = mapped_column(String(12), unique=True)
    referred_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("client_accounts.id"), index=True)
    referral_rewarded_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_retention_at: Mapped[Optional[datetime]] = mapped_column(DateTime)  # ultimo recordatorio que se le mando
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class WithdrawalRequest(Base):
    """Pedido de arrepentimiento (Res. 424/2020): el cliente lo hace desde /arrepentimiento y recibe un codigo al instante."""
    __tablename__ = "withdrawal_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    email: Mapped[Optional[str]] = mapped_column(String(255))
    phone: Mapped[Optional[str]] = mapped_column(String(40))
    order_ref: Mapped[Optional[str]] = mapped_column(String(40))  # numero de pedido que indico el cliente
    detail: Mapped[Optional[str]] = mapped_column(Text)
    account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("client_accounts.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(12), default="nuevo", server_default="nuevo", nullable=False)  # nuevo | resuelto
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


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
        Index("ux_orders_pos_uuid", "store_id", "pos_uuid", unique=True),
        Index("ix_orders_created_at", "created_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("customers.id"), index=True)
    account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("client_accounts.id"), index=True)  # cuenta del cliente que lo hizo
    origin: Mapped[Optional[str]] = mapped_column(String(10))  # web | app | caja (pedido por telefono cargado en la caja) | whatsapp | mesa
    table_name: Mapped[Optional[str]] = mapped_column(String(40))  # pedido desde la mesa (QR): "Mesa 3" (se entrega en la mesa)
    pos_uuid: Mapped[Optional[str]] = mapped_column(String(40))  # pedido por telefono: id que pone la caja (no se duplica)
    wa_conversation_id: Mapped[Optional[int]] = mapped_column(ForeignKey("wa_conversations.id"), index=True)  # lo armo el agente de WhatsApp
    stamp_at: Mapped[Optional[datetime]] = mapped_column(DateTime)  # cuando sumo su sello en la tarjeta del local (una sola vez)
    ip: Mapped[Optional[str]] = mapped_column(String(64))  # IP desde la que se hizo (control de fraude; solo la ve el superadmin)
    delivery_method: Mapped[str] = mapped_column(String(30))
    payment_method: Mapped[str] = mapped_column(String(30), default="efectivo")  # efectivo | transferencia
    cash_with: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))  # "paga con" (para llevar el vuelto)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime)  # cuando quedo pagado
    paid_by: Mapped[Optional[str]] = mapped_column(String(20))  # local (lo confirmo el comercio) | repartidor (lo cobro al entregar)
    delivery_pin: Mapped[Optional[str]] = mapped_column(String(6))  # el cliente se lo dice al repartidor al recibir
    city_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cities.id"), index=True)  # la del comercio al hacer el pedido
    scheduled_for: Mapped[Optional[datetime]] = mapped_column(DateTime, index=True)  # pedido programado: lo quiere a esta hora (UTC)
    ready_minutes: Mapped[Optional[int]] = mapped_column(Integer)  # "listo en X min" que eligio el local al aceptar
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)  # cuando lo acepto (para la hora estimada)
    stock_reserved: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)  # desconto stock (vuelve si se cancela)
    store_notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime)  # se le aviso al dueño que entro el pedido
    store_alerted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)  # se le aviso al dueño que estaba sin aceptar
    pickup_code: Mapped[Optional[str]] = mapped_column(String(6))  # el cadete se lo muestra al local para retirar (sale en la comanda)
    pickup_paid: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))  # efectivo que el cadete de la flota le pago al local al retirar
    delivery_failed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)  # el cadete reporto que no pudo entregar
    delivery_fail_reason: Mapped[Optional[str]] = mapped_column(String(160))
    courier_arrived_at: Mapped[Optional[datetime]] = mapped_column(DateTime)  # el cadete marco "Llegué" en la puerta (validado por GPS)
    proof_photo_id: Mapped[Optional[int]] = mapped_column(Integer)  # foto de la entrega o de que el cliente no aparecio
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
    points_used: Mapped[Optional[int]] = mapped_column(Integer)  # puntos Trappi canjeados en este pedido
    points_discount: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))  # descuento por puntos (mitad Trappi, mitad comercio)
    voucher_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)  # RetentionVoucher usado (sin FK: se referencian entre si)
    voucher_discount: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))  # descuento de retencion (lo pone Trappi)
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
    push_channel: Mapped[Optional[str]] = mapped_column(String(30))  # canal de Android que tiene su app (vacio: el de las versiones viejas)
    cash_limit: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))  # efectivo maximo sin rendir (vacio: el general)
    cash_orders_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true(), nullable=False)
    online_orders_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true(), nullable=False)
    # conductor de una empresa de viajes: solo le llegan los viajes de esa empresa (nunca pedidos de comida)
    ride_company_id: Mapped[Optional[int]] = mapped_column(ForeignKey("ride_companies.id"), index=True)
    plate: Mapped[Optional[str]] = mapped_column(String(12))  # patente
    car_model: Mapped[Optional[str]] = mapped_column(String(80))  # marca, modelo y color
    rating_avg: Mapped[Optional[Decimal]] = mapped_column(Numeric(3, 2))
    rating_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    store: Mapped[Optional["Store"]] = relationship()
    ride_company: Mapped[Optional["RideCompany"]] = relationship()
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
    surge: Mapped[Optional[Decimal]] = mapped_column(Numeric(4, 2))  # multiplicador por demanda al ofrecerlo (se respeta al aceptar)
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
    product: Mapped[Optional["Product"]] = relationship(lazy="select")


class StoreSection(Base):
    __tablename__ = "store_sections"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # se puede pedir solo en esta franja (por ejemplo desayunos 08:00 a 12:00); vacio: todo el horario del local
    available_from: Mapped[Optional[str]] = mapped_column(String(5))
    available_to: Mapped[Optional[str]] = mapped_column(String(5))
    store: Mapped[Store] = relationship(back_populates="sections")
    products: Mapped[List["Product"]] = relationship(back_populates="section")

    def closed_text(self, at) -> str | None:
        """None si a esa hora (local) se puede pedir; si no, 'Se pide de 08:00 a 12:00'."""
        if not (self.available_from and self.available_to):
            return None
        hhmm = at.strftime('%H:%M')
        a, b = self.available_from, self.available_to
        inside = a <= hhmm <= b if a <= b else (hhmm >= a or hhmm <= b)
        return None if inside else f'Se pide de {a} a {b}'

    @property
    def window_text(self) -> str | None:
        return f'{self.available_from} a {self.available_to}' if self.available_from and self.available_to else None


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
    # automatico: se muestra en la tienda y se aplica solo en el checkout (sin escribir el codigo)
    auto_apply: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    first_order_only: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)  # solo la primera compra en el local
    account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("client_accounts.id"), index=True)  # premio personal (tarjeta de sellos): solo esa cuenta
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


class LoyaltyEntry(Base):
    """Movimiento de puntos Trappi de un cliente. Nunca se borra: los errores se corrigen con otro movimiento.
    earn (+, al entregar) | redeem (-, al pedir) | restore (+, pedido cancelado o devuelto) | reverse (-, devolucion) | adjust (superadmin)."""
    __tablename__ = "loyalty_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("client_accounts.id", ondelete="CASCADE"), index=True)
    order_id: Mapped[Optional[int]] = mapped_column(ForeignKey("orders.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    points: Mapped[int] = mapped_column(Integer)
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))  # en $ (canje)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime)  # solo los ganados
    note: Mapped[Optional[str]] = mapped_column(String(255))
    dedupe_key: Mapped[Optional[str]] = mapped_column(String(80), unique=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class RetentionVoucher(Base):
    """Descuento de Trappi para que un cliente vuelva a pedir. Lo crea el sistema (dentro del presupuesto) o el superadmin.
    activo -> usado (en un pedido) | vencido | anulado. Nunca se borra."""
    __tablename__ = "retention_vouchers"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("client_accounts.id", ondelete="CASCADE"), index=True)
    reason: Mapped[str] = mapped_column(String(20))  # segundo_pedido | te_extranamos | manual
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    min_order: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(10), default="activo", nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    order_id: Mapped[Optional[int]] = mapped_column(Integer)  # pedido donde se uso
    used_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))  # lo que realmente se desconto
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    note: Mapped[Optional[str]] = mapped_column(String(255))
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class SearchLog(Base):
    """Lo que se busco (sin datos de quien busco): para ver que piden los clientes y no encuentran."""
    __tablename__ = "search_logs"
    __table_args__ = (Index("ix_search_logs_created", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    term: Mapped[str] = mapped_column(String(100))  # normalizado (minusculas, sin acentos)
    results: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    corrected: Mapped[Optional[str]] = mapped_column(String(100))
    city_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cities.id"), index=True)
    channel: Mapped[Optional[str]] = mapped_column(String(10))  # web | app | ai
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


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


class AuthAttempt(Base):
    """Intentos fallidos de ingreso (panel, cadetes, codigos). En la base: no se pierden al desplegar y valen para todas las instancias."""
    __tablename__ = "auth_attempts"
    __table_args__ = (Index("ix_auth_attempts_key_created", "key", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)


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


class OrderPhoto(Base):
    """Foto de un pedido: prueba de entrega, prueba de que el cliente no aparecio, o del chat.
    Se guarda en la base (no en un CDN publico): solo la ven el cadete, el cliente, el local del pedido y Trappi.
    Se re-codifica al subirla (sin los datos de ubicacion de la camara) y se borra a los dias de la configuracion."""
    __tablename__ = "order_photos"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # entrega | no_aparecio | chat
    sender: Mapped[str] = mapped_column(String(10))  # courier | customer | store
    mime: Mapped[str] = mapped_column(String(30), default="image/jpeg")
    content: Mapped[bytes] = mapped_column(LargeBinary)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class OrderMessage(Base):
    """Chat de un pedido. thread: cliente (cadete <-> cliente) o local (cadete <-> local). sender system = aviso automatico."""
    __tablename__ = "order_messages"
    __table_args__ = (Index("ix_order_messages_order_thread", "order_id", "thread", "id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    thread: Mapped[str] = mapped_column(String(10))  # cliente | local
    sender: Mapped[str] = mapped_column(String(10))  # courier | customer | store | system
    text: Mapped[Optional[str]] = mapped_column(Text)
    photo_id: Mapped[Optional[int]] = mapped_column(Integer)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


# ---------- caja (punto de venta en el mostrador, programa Trappi Caja para Windows) ----------

class PosCashier(Base):
    """Cajero del local: entra a la caja con su PIN (el usuario del local vincula la compu una vez)."""
    __tablename__ = "pos_cashiers"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    pin_hash: Mapped[str] = mapped_column(String(255))
    is_owner: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # puede cerrar la caja y salir del programa
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class PosShift(Base):
    """Una caja abierta (un turno): desde que se abre con el fondo inicial hasta que se cuenta el efectivo y se cierra."""
    __tablename__ = "pos_shifts"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    opened_by: Mapped[Optional[int]] = mapped_column(ForeignKey("pos_cashiers.id"))
    closed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("pos_cashiers.id"))
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    opening_cash: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    counted_cash: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    expected_cash: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    totals: Mapped[Optional[str]] = mapped_column(Text)  # JSON con el resumen al cerrar


class PosSale(Base):
    """Venta en el mostrador. client_uuid la genera la caja: si se corta internet la guarda y la sube despues sin duplicarla."""
    __tablename__ = "pos_sales"
    __table_args__ = (Index("ux_pos_sales_client", "store_id", "client_uuid", unique=True), Index("ix_pos_sales_kitchen", "store_id", "kitchen"))
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    shift_id: Mapped[Optional[int]] = mapped_column(ForeignKey("pos_shifts.id"), index=True)
    cashier_id: Mapped[Optional[int]] = mapped_column(ForeignKey("pos_cashiers.id"))
    client_uuid: Mapped[str] = mapped_column(String(40))
    number: Mapped[int] = mapped_column(Integer)  # numero de venta del local (1, 2, 3...)
    items: Mapped[str] = mapped_column(Text)  # JSON: [{product_id, name, quantity, unit_price, total}]
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    discount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    payment_method: Mapped[str] = mapped_column(String(20))  # efectivo | mercadopago | transferencia
    paid_with: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))  # con cuanto pago (efectivo)
    points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # Puntos Trappi que se le dan al cliente
    commission: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)  # comision de Trappi por usar la caja
    points_discount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)  # pagado con Puntos Trappi
    points_payment_id: Mapped[Optional[int]] = mapped_column(ForeignKey("points_payments.id"))
    voided: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sold_at: Mapped[datetime] = mapped_column(DateTime)  # hora en la caja (puede ser antes de subirla)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    # gastronomia: numero/nombre para llamarlo, para comer aca o para llevar, pago mixto y la comanda en el tablero de cocina
    call_number: Mapped[Optional[int]] = mapped_column(Integer)  # "Pedido 23" (la caja lo numera por dia)
    customer_name: Mapped[Optional[str]] = mapped_column(String(60))
    service: Mapped[Optional[str]] = mapped_column(String(10))  # aca | llevar
    payments: Mapped[Optional[str]] = mapped_column(Text)  # JSON [{method, amount}] si pago con dos o tres medios
    kitchen: Mapped[Optional[str]] = mapped_column(String(10))  # cocina | listo | entregado (None: no va al tablero)
    kitchen_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    approved_by: Mapped[Optional[int]] = mapped_column(ForeignKey("pos_cashiers.id"))  # dueño que autorizo un descuento grande
    promo_discount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)  # 2x1, combos, happy hour (los calcula el servidor)
    promos: Mapped[Optional[str]] = mapped_column(Text)  # JSON [{id, name, amount}]
    tip: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)  # propina (aparte del total: no lleva comision ni puntos)
    account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("client_accounts.id"), index=True)  # cliente frecuente (puntos sin QR)
    table_name: Mapped[Optional[str]] = mapped_column(String(40))  # "Mesa 3" si se cobró una mesa


class PosTable(Base):
    """Mesa del salón. El plano se arma en el panel (columna y fila); la cuenta abierta de cada mesa vive en la caja."""
    __tablename__ = "pos_tables"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    name: Mapped[str] = mapped_column(String(20))
    area: Mapped[str] = mapped_column(String(30), default="Salón", nullable=False)  # Salón | Vereda | Barra...
    seats: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    shape: Mapped[str] = mapped_column(String(10), default="square", nullable=False)  # square | round | long
    col: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    row: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    qr_code: Mapped[Optional[str]] = mapped_column(String(16), unique=True)  # QR de la mesa: el cliente pide desde ahi


class PosKitchenTicket(Base):
    """Tanda de una mesa que se manda a la cocina antes de cobrar (va al tablero de Comandas y al llamador). Sin importes."""
    __tablename__ = "pos_kitchen_tickets"
    __table_args__ = (Index("ux_pos_kitchen_client", "store_id", "client_uuid", unique=True), Index("ix_pos_kitchen_status", "store_id", "kitchen"))
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    cashier_id: Mapped[Optional[int]] = mapped_column(ForeignKey("pos_cashiers.id"))
    client_uuid: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(60))  # "Mesa 3 · Lucas"
    items: Mapped[str] = mapped_column(Text)  # JSON [{name, quantity, modifiers_text, note}]
    kitchen: Mapped[str] = mapped_column(String(10), default="cocina", nullable=False)  # cocina | listo | entregado
    kitchen_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    sent_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class PosPromo(Base):
    """Promo del mostrador: 2x1 / 3x2 (nxm), % de descuento (percent) o combo a precio fijo (combo), con días y horario.
    La caja la muestra aplicada, pero el descuento lo vuelve a calcular el servidor con la hora de la venta."""
    __tablename__ = "pos_promos"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(10))  # nxm | percent | combo
    buy: Mapped[int] = mapped_column(Integer, default=2, nullable=False)  # nxm: lleva N...
    pay: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # ...paga M
    value: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)  # percent: %; combo: precio del combo
    product_ids: Mapped[str] = mapped_column(Text, default="[]", nullable=False)  # JSON
    section_ids: Mapped[str] = mapped_column(Text, default="[]", nullable=False)  # JSON (nxm y percent: toda la sección)
    days: Mapped[str] = mapped_column(String(7), default="0123456", nullable=False)  # 0 = lunes
    start: Mapped[Optional[str]] = mapped_column(String(5))  # "18:00" (vacío: todo el día)
    end: Mapped[Optional[str]] = mapped_column(String(5))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class PosCashMovement(Base):
    """Plata que entra o sale del cajon sin ser una venta: retiro (pago a un proveedor) o ingreso (cambio). Cuenta en el cierre."""
    __tablename__ = "pos_cash_movements"
    __table_args__ = (Index("ux_pos_cash_client", "store_id", "client_uuid", unique=True),)
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey("pos_shifts.id"), index=True)
    cashier_id: Mapped[Optional[int]] = mapped_column(ForeignKey("pos_cashiers.id"))
    client_uuid: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(10))  # retiro | ingreso
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    reason: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class PointsPayment(Base):
    """Pago con Puntos Trappi en el mostrador. La caja lo pide con el total y un código de 4 números; el cliente escanea el QR
    del mostrador, pone el código y confirma desde su cuenta. Los puntos se descuentan al confirmar y vuelven si se cancela,
    si la venta no llega o si se anula."""
    __tablename__ = "points_payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    cashier_id: Mapped[Optional[int]] = mapped_column(ForeignKey("pos_cashiers.id"))
    code: Mapped[str] = mapped_column(String(8))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))  # total del ticket antes de los puntos
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending|confirmed|used|cancelled|expired|restored
    account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("client_accounts.id", ondelete="SET NULL"), index=True)
    points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    discount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    trappi_part: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)  # lo que pone Trappi del descuento
    sale_id: Mapped[Optional[int]] = mapped_column(Integer)  # la venta que lo usó (sin FK: la venta ya apunta a este pago)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class PointsClaim(Base):
    """QR de Puntos Trappi de una venta en el mostrador: un solo uso, vence, y los puntos quedan fijos al crearlo."""
    __tablename__ = "points_claims"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("pos_sales.id"), index=True)
    points: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    claimed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("client_accounts.id", ondelete="SET NULL"))
    claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


# ---------------------------------------------------------------- Trappi Viajes
class RideCompany(TimestampMixin, Base):
    """Empresa de viajes (remises, taxis, motos) con su propia flota. Pone sus tarifas; Trappi le cobra un abono por plan
    (sin comision por viaje). Solo aparece para los clientes cuando Trappi aprobo su habilitacion y esta activa."""
    __tablename__ = "ride_companies"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    slug: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    city_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cities.id"), index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(40))
    address: Mapped[Optional[str]] = mapped_column(String(255))
    logo_url: Mapped[Optional[str]] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(16), default="pendiente", server_default="pendiente", nullable=False)  # pendiente|activa|suspendida
    # habilitacion (la revisa y aprueba Trappi)
    legal_name: Mapped[Optional[str]] = mapped_column(String(200))
    cuit: Mapped[Optional[str]] = mapped_column(String(20))
    municipal_license: Mapped[Optional[str]] = mapped_column(String(80))  # numero de habilitacion municipal
    insurance_company: Mapped[Optional[str]] = mapped_column(String(120))
    insurance_policy: Mapped[Optional[str]] = mapped_column(String(80))
    insurance_expires: Mapped[Optional[date]] = mapped_column(Date)
    # renovacion del seguro que cargo la empresa ya aprobada: no vale hasta que Trappi la revisa
    insurance_pending_policy: Mapped[Optional[str]] = mapped_column(String(80))
    insurance_pending_expires: Mapped[Optional[date]] = mapped_column(Date)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    approved_by: Mapped[Optional[int]] = mapped_column(Integer)  # id del superadmin (sin FK: users ya apunta a esta tabla)
    review_note: Mapped[Optional[str]] = mapped_column(String(500))  # lo que falta o por que se suspendio
    # plan (lo define el superadmin)
    plan: Mapped[str] = mapped_column(String(16), default="inicial", server_default="inicial", nullable=False)  # inicial|pro|plus
    monthly_fee: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    driver_cap: Mapped[Optional[int]] = mapped_column(Integer)  # vacio: el del plan
    extra_driver_fee: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))  # plus: por conductor de mas
    rating_avg: Mapped[Optional[Decimal]] = mapped_column(Numeric(3, 2))
    rating_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    city: Mapped[Optional[City]] = relationship()
    tariffs: Mapped[List["RideTariff"]] = relationship(back_populates="company", cascade="all, delete-orphan")


class RideTariff(Base):
    """Tarifa de una empresa para un tipo de vehiculo. El precio se calcula siempre en el servidor."""
    __tablename__ = "ride_tariffs"
    __table_args__ = (Index("ux_ride_tariffs_company_vehicle", "company_id", "vehicle", unique=True),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("ride_companies.id", ondelete="CASCADE"), index=True)
    vehicle: Mapped[str] = mapped_column(String(10))  # auto | moto
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    base: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)  # bajada de bandera
    per_km: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    per_wait_min: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    minimum: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    night_percent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # recargo de 22 a 6
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    company: Mapped[RideCompany] = relationship(back_populates="tariffs")


class Ride(TimestampMixin, Base):
    """Un viaje pedido desde la app. El precio estimado queda fijo al pedirlo (con la tarifa de ese momento);
    al terminar solo se le suma la espera en la puerta, calculada por el servidor."""
    __tablename__ = "rides"
    __table_args__ = (Index("ix_rides_company_status", "company_id", "status"), Index("ix_rides_courier_status", "courier_id", "status"))
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("ride_companies.id"), index=True)
    account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("client_accounts.id", ondelete="SET NULL"), index=True)
    courier_id: Mapped[Optional[int]] = mapped_column(ForeignKey("couriers.id"))
    vehicle: Mapped[str] = mapped_column(String(10))
    # buscando -> asignado -> en_puerta -> en_viaje -> finalizado | cancelado | sin_conductor
    status: Mapped[str] = mapped_column(String(16), default="buscando", nullable=False)
    passenger_name: Mapped[Optional[str]] = mapped_column(String(160))
    passenger_phone: Mapped[Optional[str]] = mapped_column(String(40))
    origin_address: Mapped[Optional[str]] = mapped_column(String(255))
    origin_lat: Mapped[float] = mapped_column(Float)
    origin_lng: Mapped[float] = mapped_column(Float)
    origin_note: Mapped[Optional[str]] = mapped_column(String(160))  # "puerta del edificio"
    dest_address: Mapped[Optional[str]] = mapped_column(String(255))
    dest_lat: Mapped[float] = mapped_column(Float)
    dest_lng: Mapped[float] = mapped_column(Float)
    km: Mapped[float] = mapped_column(Float)
    minutes: Mapped[Optional[float]] = mapped_column(Float)
    route_estimated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tariff_snapshot: Mapped[Optional[str]] = mapped_column(Text)  # JSON de la tarifa usada
    night: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))  # estimado al pedir
    wait_charge: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    final_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    payment_method: Mapped[str] = mapped_column(String(20), default="efectivo", nullable=False)
    pin: Mapped[str] = mapped_column(String(6))  # se lo dice el pasajero al subir
    search_from: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)  # vuelve a empezar si el conductor cancela
    assigned_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    arrived_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    cancelled_by: Mapped[Optional[str]] = mapped_column(String(12))  # pasajero | conductor | empresa | sistema
    cancel_reason: Mapped[Optional[str]] = mapped_column(String(200))
    rating: Mapped[Optional[int]] = mapped_column(Integer)
    rating_tags: Mapped[Optional[str]] = mapped_column(String(200))
    rating_comment: Mapped[Optional[str]] = mapped_column(String(500))
    company: Mapped[RideCompany] = relationship()
    courier: Mapped[Optional[Courier]] = relationship()


class RideOffer(Base):
    """Oferta de un viaje a un conductor de la empresa: se acepta, se rechaza o vence (igual que en los pedidos)."""
    __tablename__ = "ride_offers"
    __table_args__ = (Index("ix_ride_offers_courier_status", "courier_id", "status"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    ride_id: Mapped[int] = mapped_column(ForeignKey("rides.id", ondelete="CASCADE"), index=True)
    courier_id: Mapped[int] = mapped_column(ForeignKey("couriers.id"))
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending, accepted, rejected, expired, cancelled
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ride: Mapped[Ride] = relationship()
    courier: Mapped[Courier] = relationship()


class MerchantApplication(Base):
    """Solicitud de un comercio que se quiere sumar (formulario público /sumate). No crea nada solo:
    el superadmin la revisa, contacta al dueño y recién ahí da de alta el comercio desde el panel."""
    __tablename__ = "merchant_applications"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)  # numero de tramite que ve el comercio
    status: Mapped[str] = mapped_column(String(12), default="nueva", server_default="nueva", nullable=False, index=True)  # nueva|contactada|aprobada|rechazada
    store_name: Mapped[str] = mapped_column(String(160))
    store_category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("store_categories.id", ondelete="SET NULL"))
    category_other: Mapped[Optional[str]] = mapped_column(String(100))  # rubro si no esta en la lista
    food_types: Mapped[Optional[str]] = mapped_column(String(400))  # que vende: pizzas, hamburguesas...
    province: Mapped[str] = mapped_column(String(60))
    city_name: Mapped[str] = mapped_column(String(120))
    city_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cities.id", ondelete="SET NULL"))  # si coincide con una ciudad de Trappi
    postal_code: Mapped[str] = mapped_column(String(10))
    address: Mapped[str] = mapped_column(String(255))
    address_extra: Mapped[Optional[str]] = mapped_column(String(120))  # local, piso, entre calles
    owner_name: Mapped[str] = mapped_column(String(160))
    owner_whatsapp: Mapped[str] = mapped_column(String(40))
    email: Mapped[str] = mapped_column(String(255))
    store_phone: Mapped[Optional[str]] = mapped_column(String(40))
    instagram: Mapped[Optional[str]] = mapped_column(String(120))
    cuit: Mapped[Optional[str]] = mapped_column(String(20))
    delivery: Mapped[Optional[str]] = mapped_column(String(12))  # propio | no_tiene | trappi
    hours: Mapped[Optional[str]] = mapped_column(String(200))
    comments: Mapped[Optional[str]] = mapped_column(Text)
    admin_note: Mapped[Optional[str]] = mapped_column(Text)
    store_id: Mapped[Optional[int]] = mapped_column(ForeignKey("stores.id", ondelete="SET NULL"))  # el comercio que se creo al aprobarla
    reviewed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    store_category: Mapped[Optional[StoreCategory]] = relationship()
    city: Mapped[Optional[City]] = relationship()



class StorePushSubscription(Base):
    """Celular o PC del dueño (o del personal) que recibe los avisos del local por notificacion web (gratis)."""
    __tablename__ = "store_push_subscriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    endpoint: Mapped[str] = mapped_column(String(1000), unique=True)
    p256dh: Mapped[str] = mapped_column(String(255))
    auth: Mapped[str] = mapped_column(String(255))
    label: Mapped[Optional[str]] = mapped_column(String(120))  # navegador/dispositivo, para reconocerlo
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    last_ok_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class ClientAddress(Base):
    """Direccion guardada de un cliente (Casa, Trabajo...). Se elige con un toque en la web y en la app."""
    __tablename__ = "client_addresses"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("client_accounts.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(40))
    address: Mapped[str] = mapped_column(String(255))
    reference: Mapped[Optional[str]] = mapped_column(String(255))
    lat: Mapped[Optional[float]] = mapped_column(Float)
    lng: Mapped[Optional[float]] = mapped_column(Float)
    icon: Mapped[str] = mapped_column(String(12), default="home", server_default="home", nullable=False)  # home | work | heart | pin
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class WaConversation(Base):
    """Charla de un cliente con el WhatsApp de un local. La atiende el agente o, si la toma, el dueño."""
    __tablename__ = "wa_conversations"
    __table_args__ = (Index("ux_wa_conv_store_wa", "store_id", "wa_id", unique=True),)
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    wa_id: Mapped[str] = mapped_column(String(20))  # numero del cliente (como lo manda Meta)
    name: Mapped[Optional[str]] = mapped_column(String(80))  # nombre de su perfil de WhatsApp
    account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("client_accounts.id"), index=True)  # se vincula al confirmar un pedido
    mode: Mapped[str] = mapped_column(String(10), default="agent", nullable=False)  # agent | human (la tomo el dueño)
    needs: Mapped[Optional[str]] = mapped_column(String(10))  # person (pidio una persona) | unknown (el agente no supo)
    needs_note: Mapped[Optional[str]] = mapped_column(String(200))
    cart: Mapped[Optional[str]] = mapped_column(Text)  # JSON: lineas del carrito que arma el agente
    plan: Mapped[Optional[str]] = mapped_column(Text)  # JSON: {delivery, scheduled_for} elegidos para el link
    history: Mapped[Optional[str]] = mapped_column(Text)  # JSON: memoria del agente (ultimos mensajes y herramientas)
    last_in_at: Mapped[Optional[datetime]] = mapped_column(DateTime)  # ultimo mensaje del cliente (ventana de 24 h de Meta)
    last_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    messages: Mapped[List["WaMessage"]] = relationship(back_populates="conversation", order_by="WaMessage.id", cascade="all, delete-orphan")


class WaMessage(Base):
    __tablename__ = "wa_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("wa_conversations.id"), index=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    direction: Mapped[str] = mapped_column(String(3))  # in | out
    author: Mapped[str] = mapped_column(String(10))  # customer | agent | owner | system
    text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    wa_message_id: Mapped[Optional[str]] = mapped_column(String(120), unique=True)  # id de Meta: el mismo aviso no se procesa dos veces
    status: Mapped[Optional[str]] = mapped_column(String(12))  # sent | failed | skipped (fuera de la ventana de 24 h)
    billed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)  # ya se sumo al cargo del dia en la liquidacion del local
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    conversation: Mapped["WaConversation"] = relationship(back_populates="messages")


class StampCard(Base):
    """Tarjeta de sellos de un cliente en un local."""
    __tablename__ = "stamp_cards"
    __table_args__ = (Index("ux_stamp_card", "store_id", "account_id", unique=True),)
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("client_accounts.id"), index=True)
    stamps: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # sellos de la tarjeta actual
    rewards: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # tarjetas completadas
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class OrderClaim(Base):
    """Reclamo de un cliente por un pedido ("faltó algo", "llegó mal"...), con foto opcional. Uno por pedido.
    El local lo ve y puede responder o dar un cupón suyo; Trappi lo resuelve (puntos, cupón o reintegro por Mercado Pago)."""
    __tablename__ = "order_claims"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), unique=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("client_accounts.id"), index=True)
    reason: Mapped[str] = mapped_column(String(20))  # falta | mal | frio | demora | no_llego | otro
    text: Mapped[Optional[str]] = mapped_column(Text)
    photo_id: Mapped[Optional[int]] = mapped_column(ForeignKey("order_photos.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(12), default="abierto", nullable=False)  # abierto | resuelto | rechazado
    resolution: Mapped[Optional[str]] = mapped_column(String(12))  # puntos | cupon | reintegro | nada
    points: Mapped[Optional[int]] = mapped_column(Integer)
    coupon_id: Mapped[Optional[int]] = mapped_column(ForeignKey("coupons.id"))
    store_note: Mapped[Optional[str]] = mapped_column(Text)  # lo que contesta el local
    answer: Mapped[Optional[str]] = mapped_column(Text)  # la respuesta que ve el cliente
    resolved_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    order: Mapped["Order"] = relationship()


class OrderPushSubscription(Base):
    """Navegador del cliente que pidió avisos del pedido ("confirmado", "en camino"...) por notificación web (gratis).
    Es por pedido (sirve sin cuenta) y se borra cuando el pedido termina."""
    __tablename__ = "order_push_subscriptions"
    __table_args__ = (Index("ux_order_push", "order_id", "endpoint", unique=True),)
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    endpoint: Mapped[str] = mapped_column(String(1000))
    p256dh: Mapped[str] = mapped_column(String(255))
    auth: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
