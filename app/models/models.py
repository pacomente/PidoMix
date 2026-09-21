from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, ForeignKey, Integer, Numeric, String, Text
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
    store_id: Mapped[Optional[int]] = mapped_column(ForeignKey("stores.id"), nullable=True)
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
    store_category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("store_categories.id"))
    store_category: Mapped[Optional[StoreCategory]] = relationship(back_populates="stores")
    admins: Mapped[List[User]] = relationship(back_populates="store")
    products: Mapped[List["Product"]] = relationship(back_populates="store", cascade="all, delete-orphan")
    hours: Mapped[List["StoreHour"]] = relationship(back_populates="store", cascade="all, delete-orphan")
    orders: Mapped[List["Order"]] = relationship(back_populates="store")


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
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("categories.id"))
    store: Mapped[Store] = relationship(back_populates="products")
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
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
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
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("customers.id"))
    delivery_method: Mapped[str] = mapped_column(String(30))
    payment_method: Mapped[str] = mapped_column(String(30), default="whatsapp")
    address: Mapped[Optional[str]] = mapped_column(String(255))
    reference: Mapped[Optional[str]] = mapped_column(String(255))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    shipping: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    platform_commission: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    store_commission: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    status: Mapped[OrderStatus] = mapped_column(SAEnum(OrderStatus, name="order_status_enum"), default=OrderStatus.PENDIENTE, nullable=False)
    whatsapp_url: Mapped[Optional[str]] = mapped_column(String(2000))
    customer: Mapped[Optional[Customer]] = relationship(back_populates="orders")
    store: Mapped[Store] = relationship(back_populates="orders")
    items: Mapped[List["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    product_name: Mapped[str] = mapped_column(String(180))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    quantity: Mapped[int] = mapped_column(Integer)
    order: Mapped[Order] = relationship(back_populates="items")


class Setting(Base):
    __tablename__ = "settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True)
    value: Mapped[Optional[str]] = mapped_column(Text)
