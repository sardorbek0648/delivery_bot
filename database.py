"""
Database connection and session management
"""

import os
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError
from contextlib import contextmanager
from models import Base, User, Category, Product, Order, OrderItem, CartItem, AdminSession, AdminLog

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DatabaseManager:
    """Ma'lumotlar bazasi bilan ishlash uchun klass"""
    
    def __init__(self, db_url: str):
        """
        Database manager konstruktori
        
        Args:
            db_url: Ma'lumotlar bazasiga ulanish URL'i
        """
        self.db_url = db_url
        self.engine = None
        self.SessionLocal = None
        self._initialize_database()
    
    def _initialize_database(self):
        """Ma'lumotlar bazasini sozlash"""
        try:
            # Engine yaratish
            self.engine = create_engine(
                self.db_url,
                echo=False,  # SQL so'rovlarini ko'rsatish uchun True qiling
                pool_pre_ping=True,
                pool_recycle=3600,
                connect_args={'charset': 'utf8mb4'}
            )
            
            # Session factory yaratish
            self.SessionLocal = sessionmaker(
                autocommit=False,
                autoflush=False,
                bind=self.engine
            )
            
            # Jadvallarni yaratish
            Base.metadata.create_all(bind=self.engine)
            logger.info("Ma'lumotlar bazasi muvaffaqiyatli sozlandi!")
            
        except Exception as e:
            logger.error(f"Ma'lumotlar bazasini sozlashda xatolik: {e}")
            raise
    
    @contextmanager
    def get_session(self) -> Session:
        """
        Database session kontekst manageri
        
        Usage:
            with db_manager.get_session() as session:
                # database operatsiyalari
                pass
        """
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Database operatsiyasida xatolik: {e}")
            raise
        finally:
            session.close()
    
    def test_connection(self) -> bool:
        """Ma'lumotlar bazasi ulanishini tekshirish"""
        try:
            with self.engine.connect() as connection:
                result = connection.execute(text("SELECT 1"))
                return result.fetchone()[0] == 1
        except Exception as e:
            logger.error(f"Ulanishni tekshirishda xatolik: {e}")
            return False


class UserService:
    """Foydalanuvchilar bilan ishlash uchun servis"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
    
    def create_or_update_user(self, user_data: dict) -> User:
        """Foydalanuvchini yaratish yoki yangilash"""
        with self.db_manager.get_session() as session:
            user = session.query(User).filter_by(user_id=str(user_data['user_id'])).first()
            
            if user:
                # Mavjud foydalanuvchini yangilash
                user.first_name = user_data.get('first_name', user.first_name)
                user.last_name = user_data.get('last_name', user.last_name)
                user.username = user_data.get('username', user.username)
                if 'phone_number' in user_data:
                    user.phone_number = user_data['phone_number']
                if 'address' in user_data:
                    user.address = user_data['address']
                if 'location_lat' in user_data:
                    user.location_lat = user_data['location_lat']
                if 'location_lng' in user_data:
                    user.location_lng = user_data['location_lng']
            else:
                # Yangi foydalanuvchi yaratish
                user = User(
                    user_id=str(user_data['user_id']),
                    first_name=user_data.get('first_name'),
                    last_name=user_data.get('last_name'),
                    username=user_data.get('username'),
                    phone_number=user_data.get('phone_number'),
                    address=user_data.get('address'),
                    location_lat=user_data.get('location_lat'),
                    location_lng=user_data.get('location_lng')
                )
                session.add(user)
            
            session.flush()
            session.refresh(user)
            return user
    
    def get_user_by_id(self, user_id: str) -> User:
        """Foydalanuvchini ID bo'yicha topish"""
        with self.db_manager.get_session() as session:
            return session.query(User).filter_by(user_id=str(user_id)).first()
    
    def update_user_location(self, user_id: str, latitude: float, longitude: float, address: str = None):
        """Foydalanuvchi joylashuvini yangilash"""
        with self.db_manager.get_session() as session:
            user = session.query(User).filter_by(user_id=str(user_id)).first()
            if user:
                user.location_lat = latitude
                user.location_lng = longitude
                if address:
                    user.address = address


class CategoryService:
    """Kategoriyalar bilan ishlash uchun servis"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
    
    def get_all_categories(self) -> list[Category]:
        """Barcha faol kategoriyalarni olish"""
        with self.db_manager.get_session() as session:
            return session.query(Category).filter_by(is_active=True).all()
    
    def create_category(self, name: str, description: str = None) -> Category:
        """Yangi kategoriya yaratish"""
        with self.db_manager.get_session() as session:
            category = Category(name=name, description=description)
            session.add(category)
            session.flush()
            session.refresh(category)
            return category
    
    def get_category_by_id(self, category_id: int) -> Category:
        """Kategoriyani ID bo'yicha olish"""
        with self.db_manager.get_session() as session:
            return session.query(Category).filter_by(id=category_id, is_active=True).first()


class ProductService:
    """Mahsulotlar bilan ishlash uchun servis"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
    
    def get_products_by_category(self, category_id: int) -> list[Product]:
        """Kategoriya bo'yicha mahsulotlarni olish"""
        with self.db_manager.get_session() as session:
            return session.query(Product).filter_by(
                category_id=category_id, 
                is_available=True
            ).all()
    
    def get_product_by_id(self, product_id: int) -> Product:
        """Mahsulotni ID bo'yicha olish"""
        with self.db_manager.get_session() as session:
            return session.query(Product).filter_by(id=product_id, is_available=True).first()
    
    def create_product(self, name: str, price: float, category_id: int, 
                      description: str = None, image_url: str = None) -> Product:
        """Yangi mahsulot yaratish"""
        with self.db_manager.get_session() as session:
            product = Product(
                name=name,
                price=price,
                category_id=category_id,
                description=description,
                image_url=image_url
            )
            session.add(product)
            session.flush()
            session.refresh(product)
            return product
    
    def search_products(self, query: str) -> list[Product]:
        """Mahsulot qidirish"""
        with self.db_manager.get_session() as session:
            return session.query(Product).filter(
                Product.name.contains(query),
                Product.is_available == True
            ).all()


class CartService:
    """Savat bilan ishlash uchun servis"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
    
    def add_to_cart(self, user_id: str, product_id: int, quantity: int = 1):
        """Savatga mahsulot qo'shish"""
        with self.db_manager.get_session() as session:
            cart_item = session.query(CartItem).filter_by(
                user_id=str(user_id), 
                product_id=product_id
            ).first()
            
            if cart_item:
                cart_item.quantity += quantity
            else:
                cart_item = CartItem(
                    user_id=str(user_id),
                    product_id=product_id,
                    quantity=quantity
                )
                session.add(cart_item)
    
    def remove_from_cart(self, user_id: str, product_id: int):
        """Savatdan mahsulot o'chirish"""
        with self.db_manager.get_session() as session:
            cart_item = session.query(CartItem).filter_by(
                user_id=str(user_id), 
                product_id=product_id
            ).first()
            if cart_item:
                session.delete(cart_item)
    
    def get_cart_items(self, user_id: str) -> list[CartItem]:
        """Foydalanuvchi savatini olish"""
        with self.db_manager.get_session() as session:
            return session.query(CartItem).filter_by(user_id=str(user_id)).all()
    
    def clear_cart(self, user_id: str):
        """Savatni tozalash"""
        with self.db_manager.get_session() as session:
            session.query(CartItem).filter_by(user_id=str(user_id)).delete()
    
    def update_cart_quantity(self, user_id: str, product_id: int, quantity: int):
        """Savat mahsuloti miqdorini yangilash"""
        with self.db_manager.get_session() as session:
            cart_item = session.query(CartItem).filter_by(
                user_id=str(user_id), 
                product_id=product_id
            ).first()
            
            if cart_item:
                if quantity <= 0:
                    session.delete(cart_item)
                else:
                    cart_item.quantity = quantity


class OrderService:
    """Buyurtmalar bilan ishlash uchun servis"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
    
    def create_order(self, user_id: str, cart_items: list[CartItem], 
                    delivery_data: dict, payment_method: str = "Naqd") -> Order:
        """Yangi buyurtma yaratish"""
        with self.db_manager.get_session() as session:
            # Buyurtma raqamini yaratish
            import random
            import string
            order_number = ''.join(random.choices(string.digits, k=8))
            
            # Umumiy summa hisoblash
            total_amount = sum(item.product.price * item.quantity for item in cart_items)
            
            # Buyurtma yaratish
            order = Order(
                order_number=order_number,
                user_id=str(user_id),
                total_amount=total_amount,
                delivery_address=delivery_data.get('address'),
                delivery_lat=delivery_data.get('latitude'),
                delivery_lng=delivery_data.get('longitude'),
                phone_number=delivery_data.get('phone'),
                payment_method=payment_method,
                notes=delivery_data.get('notes')
            )
            session.add(order)
            session.flush()
            
            # Buyurtma elementlarini qo'shish
            for cart_item in cart_items:
                order_item = OrderItem(
                    order_id=order.id,
                    product_id=cart_item.product_id,
                    quantity=cart_item.quantity,
                    price=cart_item.product.price
                )
                session.add(order_item)
            
            # Savatni tozalash
            session.query(CartItem).filter_by(user_id=str(user_id)).delete()
            
            session.flush()
            session.refresh(order)
            return order
    
    def get_user_orders(self, user_id: str) -> list[Order]:
        """Foydalanuvchi buyurtmalarini olish"""
        with self.db_manager.get_session() as session:
            return session.query(Order).filter_by(user_id=str(user_id))\
                          .order_by(Order.created_at.desc()).all()
    
    def get_order_by_number(self, order_number: str) -> Order:
        """Buyurtmani raqam bo'yicha olish"""
        with self.db_manager.get_session() as session:
            return session.query(Order).filter_by(order_number=order_number).first()
    
    def update_order_status(self, order_id: int, status: str):
        """Buyurtma holatini yangilash"""
        with self.db_manager.get_session() as session:
            order = session.query(Order).filter_by(id=order_id).first()
            if order:
                order.status = status
    
    def get_pending_orders(self) -> list[Order]:
        """Kutilyotgan buyurtmalarni olish"""
        with self.db_manager.get_session() as session:
            return session.query(Order).filter(
                Order.status.in_(['Kutilyapti', 'Tasdiqlandi', 'Tayyor'])
            ).order_by(Order.created_at.asc()).all()


# Database konfiguratsiyasi
def get_database_url() -> str:
    """Ma'lumotlar bazasi URL'ini olish"""
    # .env fayldan yoki muhit o'zgaruvchilardan
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    # MySQL connection parametrlari
    DB_HOST = os.getenv('DB_HOST', 'localhost')
    DB_PORT = os.getenv('DB_PORT', '3306')
    DB_USER = os.getenv('DB_USER', 'root')
    DB_PASSWORD = os.getenv('DB_PASSWORD', '')
    DB_NAME = os.getenv('DB_NAME', 'delivery_bot')
    
    return f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"


# Global database manager
db_manager = None
user_service = None
category_service = None
product_service = None
cart_service = None
order_service = None


def initialize_database():
    """Ma'lumotlar bazasini ishga tushirish"""
    global db_manager, user_service, category_service, product_service, cart_service, order_service
    
    try:
        db_url = get_database_url()
        db_manager = DatabaseManager(db_url)
        
        # Servislarni yaratish
        user_service = UserService(db_manager)
        category_service = CategoryService(db_manager)
        product_service = ProductService(db_manager)
        cart_service = CartService(db_manager)
        order_service = OrderService(db_manager)
        
        logger.info("Ma'lumotlar bazasi servislari muvaffaqiyatli ishga tushirildi!")
        return True
        
    except Exception as e:
        logger.error(f"Ma'lumotlar bazasini ishga tushirishda xatolik: {e}")
        return False


def insert_sample_data():
    """Namunaviy ma'lumotlarni kiritish"""
    if not db_manager:
        logger.error("Ma'lumotlar bazasi ulanmagan!")
        return
    
    try:
        # Kategoriyalar
        categories_data = [
            {"name": "🍕 Pizza", "description": "Har xil turdagi pitsa"},
            {"name": "🍔 Burger", "description": "Mazali burgerlar"},
            {"name": "🥤 Ichimliklar", "description": "Sovuq va issiq ichimliklar"},
            {"name": "🍰 Shirinliklar", "description": "Tort va shirinliklar"}
        ]
        
        for cat_data in categories_data:
            existing = category_service.get_all_categories()
            if not any(cat.name == cat_data['name'] for cat in existing):
                category_service.create_category(cat_data['name'], cat_data['description'])
        
        # Mahsulotlar
        categories = category_service.get_all_categories()
        pizza_cat = next((cat for cat in categories if "Pizza" in cat.name), None)
        burger_cat = next((cat for cat in categories if "Burger" in cat.name), None)
        drink_cat = next((cat for cat in categories if "Ichimliklar" in cat.name), None)
        dessert_cat = next((cat for cat in categories if "Shirinliklar" in cat.name), None)
        
        products_data = [
            # Pizza
            {"name": "Margarita Pizza", "price": 45000, "category_id": pizza_cat.id if pizza_cat else 1},
            {"name": "Pepperoni Pizza", "price": 55000, "category_id": pizza_cat.id if pizza_cat else 1},
            {"name": "Four Cheese Pizza", "price": 60000, "category_id": pizza_cat.id if pizza_cat else 1},
            
            # Burger
            {"name": "Classic Burger", "price": 35000, "category_id": burger_cat.id if burger_cat else 2},
            {"name": "Cheese Burger", "price": 40000, "category_id": burger_cat.id if burger_cat else 2},
            {"name": "Chicken Burger", "price": 42000, "category_id": burger_cat.id if burger_cat else 2},
            
            # Ichimliklar
            {"name": "Coca Cola 0.5L", "price": 8000, "category_id": drink_cat.id if drink_cat else 3},
            {"name": "Mineral suv 0.5L", "price": 5000, "category_id": drink_cat.id if drink_cat else 3},
            {"name": "Fresh orange juice", "price": 15000, "category_id": drink_cat.id if drink_cat else 3},
            
            # Shirinliklar
            {"name": "Tiramisu", "price": 25000, "category_id": dessert_cat.id if dessert_cat else 4},
            {"name": "Chocolate cake", "price": 20000, "category_id": dessert_cat.id if dessert_cat else 4}
        ]
        
        for prod_data in products_data:
            existing_product = product_service.get_products_by_category(prod_data['category_id'])
            if not any(prod.name == prod_data['name'] for prod in existing_product):
                product_service.create_product(
                    name=prod_data['name'],
                    price=prod_data['price'],
                    category_id=prod_data['category_id'],
                    description=f"{prod_data['name']} - mazali va sifatli"
                )
        
        logger.info("Namunaviy ma'lumotlar muvaffaqiyatli qo'shildi!")
        
    except Exception as e:
        logger.error(f"Namunaviy ma'lumotlarni qo'shishda xatolik: {e}")


if __name__ == "__main__":
    # Test qilish uchun
    if initialize_database():
        if db_manager.test_connection():
            print("✅ Ma'lumotlar bazasi ulanishi muvaffaqiyatli!")
            insert_sample_data()
        else:
            print("❌ Ma'lumotlar bazasiga ulanib bo'lmadi!")
    else:
        print("❌ Ma'lumotlar bazasini sozlashda xatolik!")