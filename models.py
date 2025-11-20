"""
Database models for Telegram Bot
SQLAlchemy models for MySQL database
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Boolean, ForeignKey, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

Base = declarative_base()


class User(Base):
    """Foydalanuvchi modeli"""
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(20), unique=True, nullable=False, index=True)  # Telegram user ID
    first_name = Column(String(255))
    last_name = Column(String(255))
    username = Column(String(255))
    phone_number = Column(String(20))
    location_lat = Column(Float)
    location_lng = Column(Float)
    address = Column(Text)
    registration_date = Column(DateTime, default=func.now())
    last_activity = Column(DateTime, default=func.now(), onupdate=func.now())
    is_active = Column(Boolean, default=True)
    
    # Relationships
    orders = relationship("Order", back_populates="user")
    cart_items = relationship("CartItem", back_populates="user")

    def __repr__(self):
        return f"<User(user_id={self.user_id}, name={self.first_name} {self.last_name})>"


class Category(Base):
    """Mahsulot kategoriyalari"""
    __tablename__ = 'categories'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())

    # Relationships
    products = relationship("Product", back_populates="category")

    def __repr__(self):
        return f"<Category(name={self.name})>"


class Product(Base):
    """Mahsulotlar modeli"""
    __tablename__ = 'products'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    price = Column(Float, nullable=False)
    category_id = Column(Integer, ForeignKey('categories.id'))
    image_url = Column(String(500))
    is_available = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    category = relationship("Category", back_populates="products")
    order_items = relationship("OrderItem", back_populates="product")
    cart_items = relationship("CartItem", back_populates="product")

    def __repr__(self):
        return f"<Product(name={self.name}, price={self.price})>"


class Order(Base):
    """Buyurtmalar modeli"""
    __tablename__ = 'orders'

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_number = Column(String(20), unique=True, nullable=False, index=True)
    user_id = Column(String(20), ForeignKey('users.user_id'), nullable=False)
    total_amount = Column(Float, nullable=False)
    delivery_address = Column(Text)
    delivery_lat = Column(Float)
    delivery_lng = Column(Float)
    phone_number = Column(String(20))
    status = Column(String(50), default='Kutilyapti')  # Kutilyapti, Tasdiqlandi, Tayyor, Yetkazildi, Bekor qilindi
    payment_method = Column(String(50))  # Naqd, Click, Payme
    payment_status = Column(String(50), default='Kutilmoqda')  # Kutilmoqda, To'landi, Bekor qilindi
    notes = Column(Text)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="orders")
    order_items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Order(order_number={self.order_number}, status={self.status})>"


class OrderItem(Base):
    """Buyurtma elementlari"""
    __tablename__ = 'order_items'

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey('orders.id'), nullable=False)
    product_id = Column(Integer, ForeignKey('products.id'), nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)  # Price at time of order
    created_at = Column(DateTime, default=func.now())

    # Relationships
    order = relationship("Order", back_populates="order_items")
    product = relationship("Product", back_populates="order_items")

    def __repr__(self):
        return f"<OrderItem(order_id={self.order_id}, product_id={self.product_id}, qty={self.quantity})>"


class CartItem(Base):
    """Savat elementlari"""
    __tablename__ = 'cart_items'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(20), ForeignKey('users.user_id'), nullable=False)
    product_id = Column(Integer, ForeignKey('products.id'), nullable=False)
    quantity = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="cart_items")
    product = relationship("Product", back_populates="cart_items")

    def __repr__(self):
        return f"<CartItem(user_id={self.user_id}, product_id={self.product_id}, qty={self.quantity})>"


class AdminSession(Base):
    """Admin sessiyalari"""
    __tablename__ = 'admin_sessions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(20), nullable=False, index=True)
    session_data = Column(JSON)  # Store session state as JSON
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    expires_at = Column(DateTime)

    def __repr__(self):
        return f"<AdminSession(user_id={self.user_id})>"


class AdminLog(Base):
    """Admin amaliyotlari logi"""
    __tablename__ = 'admin_logs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    admin_user_id = Column(String(20), nullable=False, index=True)
    action = Column(String(255), nullable=False)
    details = Column(Text)
    target_order_id = Column(Integer, ForeignKey('orders.id'), nullable=True)
    created_at = Column(DateTime, default=func.now())

    def __repr__(self):
        return f"<AdminLog(admin={self.admin_user_id}, action={self.action})>"