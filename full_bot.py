"""
To'liq funksional Fast Food Bot
MySQL database bilan ishlaydi
"""

import os
import time
import requests
import json
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from models import Base, User, Product, Category, Order, OrderItem, CartItem

load_dotenv()

# Configuration
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 5788278697))
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_NAME = os.environ.get("DB_NAME", "dostavka_bot") 
DB_USER = os.environ.get("DB_USER", "root")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")

class DatabaseManager:
    def __init__(self):
        self.engine = None
        self.session_factory = None
        self.connect()
        
    def connect(self):
        """MySQL ga ulanish"""
        try:
            # Database yaratish (agar mavjud bo'lmasa)
            temp_engine = create_engine(f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/")
            with temp_engine.connect() as conn:
                conn.execute(text(f"CREATE DATABASE IF NOT EXISTS {DB_NAME}"))
                conn.commit()
            temp_engine.dispose()
            
            # Asosiy ulanish
            self.engine = create_engine(f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}")
            Base.metadata.create_all(self.engine)
            self.session_factory = sessionmaker(bind=self.engine)
            print("✅ MySQL bazaga muvaffaqiyatli ulanildi!")
            
            # Test ma'lumotlar qo'shish
            self.add_sample_data()
            
        except Exception as e:
            print(f"❌ MySQL ulanish xatosi: {e}")
            
    def add_sample_data(self):
        """Test ma'lumotlar qo'shish"""
        session = self.session_factory()
        try:
            # Kategoriyalar
            if session.query(Category).count() == 0:
                categories = [
                    Category(name="🍔 Burgerlar", description="Mazali burgerlar"),
                    Category(name="🍕 Pitsalar", description="Issiq pitsalar"),
                    Category(name="🥤 Ichimliklar", description="Sovuq ichimliklar"),
                    Category(name="🍟 Sneklar", description="Yengil taomlar")
                ]
                session.add_all(categories)
                session.commit()
                
            # Mahsulotlar
            if session.query(Product).count() == 0:
                burger_cat = session.query(Category).filter_by(name="🍔 Burgerlar").first()
                pizza_cat = session.query(Category).filter_by(name="🍕 Pitsalar").first()
                drink_cat = session.query(Category).filter_by(name="🥤 Ichimliklar").first()
                snack_cat = session.query(Category).filter_by(name="🍟 Sneklar").first()
                
                products = [
                    Product(name="Big Burger", price=25000, category_id=burger_cat.id, description="Katta va mazali burger"),
                    Product(name="Cheese Burger", price=20000, category_id=burger_cat.id, description="Pishloqli burger"),
                    Product(name="Chicken Burger", price=22000, category_id=burger_cat.id, description="Tovuqli burger"),
                    Product(name="Margherita Pizza", price=35000, category_id=pizza_cat.id, description="Klassik pitsa"),
                    Product(name="Pepperoni Pizza", price=40000, category_id=pizza_cat.id, description="Pepperoni bilan"),
                    Product(name="Coca Cola", price=8000, category_id=drink_cat.id, description="0.5L Coca Cola"),
                    Product(name="Fanta", price=8000, category_id=drink_cat.id, description="0.5L Fanta"),
                    Product(name="French Fries", price=12000, category_id=snack_cat.id, description="Kartoshka fri")
                ]
                session.add_all(products)
                session.commit()
                print("✅ Test ma'lumotlar qo'shildi!")
                
        except Exception as e:
            print(f"❌ Ma'lumot qo'shishda xato: {e}")
            session.rollback()
        finally:
            session.close()

class FullTelegramBot:
    def __init__(self, token):
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.last_update_id = 0
        self.db = DatabaseManager()
        self.user_states = {}  # Foydalanuvchi holatlari
        
    def send_message(self, chat_id, text, reply_markup=None):
        """Xabar yuborish"""
        url = f"{self.base_url}/sendMessage"
        data = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'HTML'
        }
        if reply_markup:
            data['reply_markup'] = json.dumps(reply_markup)
        try:
            response = requests.post(url, data=data, timeout=10)  # Timeout oshirildi
            return response.json()
        except requests.exceptions.Timeout:
            print(f"⏰ Xabar yuborishda timeout: {chat_id}")
            return None
        except requests.exceptions.ConnectionError:
            print(f"🌐 Xabar yuborishda ulanish xatosi: {chat_id}")
            return None
        except Exception as e:
            print(f"❌ Xabar yuborishda xato: {e}")
            return None
            
    def send_message_with_inline(self, chat_id, text, inline_keyboard=None, reply_keyboard=None):
        """Inline keyboard bilan xabar yuborish - faqat bitta xabar"""
        url = f"{self.base_url}/sendMessage"
        
        # Faqat inline keyboard bilan yuborish
        if inline_keyboard:
            data = {
                'chat_id': chat_id,
                'text': text,
                'parse_mode': 'HTML',
                'reply_markup': json.dumps({
                    'inline_keyboard': inline_keyboard
                })
            }
        else:
            data = {
                'chat_id': chat_id,
                'text': text,
                'parse_mode': 'HTML'
            }
            if reply_keyboard:
                data['reply_markup'] = json.dumps(reply_keyboard)
            
        try:
            response = requests.post(url, data=data, timeout=10)
            return response.json() if response else None
        except Exception as e:
            print(f"❌ Inline xabar yuborishda xato: {e}")
            return None
            
    def send_photo(self, chat_id, photo, caption=None, reply_markup=None):
        """Rasm yuborish"""
        url = f"{self.base_url}/sendPhoto"
        data = {
            'chat_id': chat_id,
            'photo': photo,
            'parse_mode': 'HTML'
        }
        if caption:
            data['caption'] = caption
        if reply_markup:
            data['reply_markup'] = json.dumps(reply_markup)
        
        try:
            response = requests.post(url, data=data, timeout=15)
            return response.json()
        except Exception as e:
            print(f"❌ Rasm yuborishda xato: {e}")
            return None
            
    def send_photo(self, chat_id, photo, caption=None, reply_markup=None):
        """Rasm yuborish"""
        url = f"{self.base_url}/sendPhoto"
        data = {
            'chat_id': chat_id,
            'photo': photo,
            'parse_mode': 'HTML'
        }
        if caption:
            data['caption'] = caption
        if reply_markup:
            data['reply_markup'] = json.dumps(reply_markup)
        try:
            response = requests.post(url, data=data)
            return response.json()
        except Exception as e:
            print(f"❌ Rasm yuborishda xato: {e}")
            return None
            
    def send_video(self, chat_id, video, caption=None, reply_markup=None):
        """Video yuborish"""
        url = f"{self.base_url}/sendVideo"
        data = {
            'chat_id': chat_id,
            'video': video,
            'parse_mode': 'HTML'
        }
        if caption:
            data['caption'] = caption
        if reply_markup:
            data['reply_markup'] = json.dumps(reply_markup)
        try:
            response = requests.post(url, data=data)
            return response.json()
        except Exception as e:
            print(f"❌ Video yuborishda xato: {e}")
            return None
            
    def send_document(self, chat_id, document, caption=None, reply_markup=None):
        """Fayl yuborish"""
        url = f"{self.base_url}/sendDocument"
        data = {
            'chat_id': chat_id,
            'document': document,
            'parse_mode': 'HTML'
        }
        if caption:
            data['caption'] = caption
        if reply_markup:
            data['reply_markup'] = json.dumps(reply_markup)
        try:
            response = requests.post(url, data=data)
            return response.json()
        except Exception as e:
            print(f"❌ Fayl yuborishda xato: {e}")
            return None
            
    def get_updates(self):
        """Updates olish"""
        url = f"{self.base_url}/getUpdates"
        data = {'offset': self.last_update_id + 1, 'timeout': 5}  # Timeout kamaytirildi
        try:
            response = requests.get(url, params=data, timeout=10)  # Request timeout
            return response.json()
        except requests.exceptions.Timeout:
            print(f"⏰ Timeout - internet sekin ishlayapti...")
            return {'ok': True, 'result': []}  # Bo'sh natija qaytarish
        except requests.exceptions.ConnectionError:
            print(f"🌐 Internet ulanishida muammo - qayta urinish...")
            return None
        except Exception as e:
            print(f"❌ Updates olishda xato: {e}")
            return None
            
    def save_user(self, user_data):
        """Foydalanuvchini bazaga saqlash"""
        session = self.db.session_factory()
        try:
            existing_user = session.query(User).filter_by(user_id=str(user_data['id'])).first()
            if not existing_user:
                new_user = User(
                    user_id=str(user_data['id']),
                    first_name=user_data.get('first_name', ''),
                    last_name=user_data.get('last_name', ''),
                    username=user_data.get('username', '')
                )
                session.add(new_user)
                session.commit()
                print(f"✅ Yangi foydalanuvchi: {user_data.get('first_name', 'Unknown')}")
            else:
                # Ma'lumotlarni yangilash
                existing_user.last_activity = datetime.now()
                session.commit()
        except Exception as e:
            print(f"❌ Foydalanuvchini saqlashda xato: {e}")
            session.rollback()
        finally:
            session.close()
            
    def get_admin_keyboard(self):
        """Admin klaviaturasi"""
        return {
            'keyboard': [
                ['🍽 Menyu boshqaruvi', '📋 Buyurtmalar'],
                ['📊 Statistika', '👥 Foydalanuvchilar'],
                ['➕ Mahsulot qo\'shish', '📤 Xabar yuborish'],
                ['🔄 Bot holati', '⚙️ Sozlamalar']
            ],
            'resize_keyboard': True
        }
    
    def get_user_keyboard(self):
        """Foydalanuvchi klaviaturasi"""
        return {
            'keyboard': [
                ['🍽 Menyu', '🛒 Savat'],
                ['📋 Buyurtmalarim', '📞 Aloqa'],
                ['ℹ️ Ma\'lumot']
            ],
            'resize_keyboard': True
        }
        
    def get_categories_keyboard(self):
        """Kategoriyalar klaviaturasi"""
        session = self.db.session_factory()
        try:
            categories = session.query(Category).all()
            keyboard = []
            row = []
            for i, category in enumerate(categories):
                row.append(category.name)
                if len(row) == 2 or i == len(categories) - 1:
                    keyboard.append(row)
                    row = []
            keyboard.append(['🔙 Orqaga'])
            return {'keyboard': keyboard, 'resize_keyboard': True}
        except Exception as e:
            print(f"❌ Kategoriyalar olishda xato: {e}")
            return {'keyboard': [['🔙 Orqaga']], 'resize_keyboard': True}
        finally:
            session.close()
            
    def get_products_by_category(self, category_name):
        """Kategoriya bo'yicha mahsulotlar"""
        session = self.db.session_factory()
        try:
            category = session.query(Category).filter_by(name=category_name).first()
            if category:
                products = session.query(Product).filter_by(category_id=category.id, is_available=True).all()
                return products
            return []
        except Exception as e:
            print(f"❌ Mahsulotlar olishda xato: {e}")
            return []
        finally:
            session.close()
            
    def get_cart_items(self, user_id):
        """Foydalanuvchi savatini olish"""
        session = self.db.session_factory()
        try:
            cart_items = session.query(CartItem).filter_by(user_id=str(user_id)).all()
            return cart_items
        except Exception as e:
            print(f"❌ Savat olishda xato: {e}")
            return []
        finally:
            session.close()
            
    def get_all_users(self):
        """Barcha foydalanuvchilarni olish"""
        session = self.db.session_factory()
        try:
            users = session.query(User).filter_by(is_active=True).all()
            return users
        except Exception as e:
            print(f"❌ Foydalanuvchilar olishda xato: {e}")
            return []
        finally:
            session.close()
            
    def broadcast_message(self, message_text, sender_id):
        """Barcha foydalanuvchilarga matn xabar yuborish"""
        users = self.get_all_users()
        success_count = 0
        failed_count = 0
        
        print(f"📤 {len(users)} ta foydalanuvchiga xabar yuborilmoqda...")
        
        for i, user in enumerate(users):
            if user.user_id != str(sender_id):  # O'ziga yubormaslik
                try:
                    result = self.send_message(int(user.user_id), message_text)
                    if result and result.get('ok'):
                        success_count += 1
                        print(f"✅ {i+1}/{len(users)}: {user.user_id}")
                    else:
                        failed_count += 1
                        print(f"❌ {i+1}/{len(users)}: {user.user_id}")
                    time.sleep(0.1)  # Rate limiting oshirildi
                except Exception as e:
                    print(f"❌ {user.user_id} ga xabar yuborishda xato: {e}")
                    failed_count += 1
                    time.sleep(0.1)
                    
        return success_count, failed_count
        
    def broadcast_photo(self, photo_id, caption, sender_id):
        """Barcha foydalanuvchilarga rasm yuborish"""
        users = self.get_all_users()
        success_count = 0
        failed_count = 0
        
        for user in users:
            if user.user_id != str(sender_id):  # O'ziga yubormaslik
                try:
                    result = self.send_photo(int(user.user_id), photo_id, caption)
                    if result and result.get('ok'):
                        success_count += 1
                    else:
                        failed_count += 1
                    time.sleep(0.05)  # Rate limiting
                except Exception as e:
                    print(f"❌ {user.user_id} ga rasm yuborishda xato: {e}")
                    failed_count += 1
                    
        return success_count, failed_count
        
    def broadcast_video(self, video_id, caption, sender_id):
        """Barcha foydalanuvchilarga video yuborish"""
        users = self.get_all_users()
        success_count = 0
        failed_count = 0
        
        for user in users:
            if user.user_id != str(sender_id):  # O'ziga yubormaslik
                try:
                    result = self.send_video(int(user.user_id), video_id, caption)
                    if result and result.get('ok'):
                        success_count += 1
                    else:
                        failed_count += 1
                    time.sleep(0.05)  # Rate limiting
                except Exception as e:
                    print(f"❌ {user.user_id} ga video yuborishda xato: {e}")
                    failed_count += 1
                    
        return success_count, failed_count
        
    def broadcast_document(self, document_id, caption, sender_id):
        """Barcha foydalanuvchilarga fayl yuborish"""
        users = self.get_all_users()
        success_count = 0
        failed_count = 0
        
        for user in users:
            if user.user_id != str(sender_id):  # O'ziga yubormaslik
                try:
                    result = self.send_document(int(user.user_id), document_id, caption)
                    if result and result.get('ok'):
                        success_count += 1
                    else:
                        failed_count += 1
                    time.sleep(0.05)  # Rate limiting
                except Exception as e:
                    print(f"❌ {user.user_id} ga fayl yuborishda xato: {e}")
                    failed_count += 1
                    
        return success_count, failed_count
        
    def add_to_cart(self, user_id, product_id, quantity=1):
        """Savatga qo'shish"""
        session = self.db.session_factory()
        try:
            existing_item = session.query(CartItem).filter_by(
                user_id=str(user_id), product_id=product_id
            ).first()
            
            if existing_item:
                existing_item.quantity += quantity
            else:
                new_item = CartItem(user_id=str(user_id), product_id=product_id, quantity=quantity)
                session.add(new_item)
            
            session.commit()
            return True
        except Exception as e:
            print(f"❌ Savatga qo'shishda xato: {e}")
            session.rollback()
            return False
        finally:
            session.close()
            
    def handle_user_orders(self, chat_id, user_id):
        """Foydalanuvchi buyurtmalar tarixi"""
        session = self.db.session_factory()
        try:
            orders = session.query(Order).filter_by(user_id=str(user_id)).order_by(Order.created_at.desc()).limit(10).all()
            
            if orders:
                response = "📋 <b>Sizning buyurtmalaringiz</b>\n\n"
                
                for order in orders:
                    # Status emoji
                    status_emoji = {
                        'pending': '🕐',
                        'confirmed': '✅',
                        'preparing': '👨‍🍳',
                        'ready': '🎆',
                        'delivering': '🚚',
                        'delivered': '✅',
                        'cancelled': '❌'
                    }.get(order.status, '🕐')
                    
                    status_text = {
                        'pending': 'Kutilmoqda',
                        'confirmed': 'Tasdiqlandi', 
                        'preparing': 'Tayyorlanmoqda',
                        'ready': 'Tayyor',
                        'delivering': 'Yetkazilmoqda',
                        'delivered': 'Yetkazilgan',
                        'cancelled': 'Bekor qilingan'
                    }.get(order.status, 'Kutilmoqda')
                    
                    response += f"🔢 <b>Buyurtma #{order.id}</b>\n"
                    response += f"{status_emoji} Status: <i>{status_text}</i>\n"
                    response += f"💰 Jami: <b>{order.total_amount:,} so'm</b>\n"
                    response += f"📅 Sana: <i>{order.created_at.strftime('%d.%m.%Y %H:%M')}</i>\n\n"
                        
                keyboard = [['🔄 Yangilash', '📞 Qo\'llab-quvvatlash'], ['🔙 Bosh menyu']]
            else:
                response = "📋 <b>Sizning buyurtmalaringiz</b>\n\n📭 <i>Hozircha buyurtmalar yo'q</i>\n\nBirinchi buyurtma berish uchun menyu bo'limiga o'ting!"
                keyboard = [['🍽 Menyu ko\'rish'], ['🏠 Bosh menyu']]
                
        except Exception as e:
            print(f"❌ Buyurtmalar olishda xato: {e}")
            response = "❌ Buyurtmalar ma'lumotini olishda xato yuz berdi."
            keyboard = [['🏠 Bosh menyu']]
        finally:
            session.close()
            
        self.send_message(chat_id, response, {'keyboard': keyboard, 'resize_keyboard': True})
        
    def handle_user_address(self, chat_id, user_id):
        """Foydalanuvchi manzil boshqaruvi"""
        session = self.db.session_factory()
        try:
            user = session.query(User).filter_by(user_id=str(user_id)).first()
            
            if user and user.address:
                response = f"""
📍 <b>Sizning manzillaringiz</b>

🏠 <b>Asosiy manzil:</b>
{user.address}

📞 <b>Telefon:</b> {user.phone_number or 'Kiritilmagan'}

📋 Buyurtma berishda ushbu ma'lumotlar ishlatiladi.
                """
                keyboard = [
                    ['✏️ Manzilni o\'zgartirish', '📞 Telefon o\'zgartirish'],
                    ['📍 Joylashuvni yuborish', '🏠 Bosh menyu']
                ]
            else:
                response = """
📍 <b>Manzil ma'lumotlari</b>

📭 <i>Hozircha manzil kiritilmagan</i>

Tez buyurtma berish uchun manzil va telefon raqamingizni kiriting!
                """
                keyboard = [
                    ['➕ Manzil qo\'shish', '📞 Telefon qo\'shish'],
                    ['📍 Joylashuvni yuborish', '🏠 Bosh menyu']
                ]
                
            self.send_message(chat_id, response, {'keyboard': keyboard, 'resize_keyboard': True})
            
        except Exception as e:
            print(f"❌ Manzil ma'lumotlarini olishda xato: {e}")
            response = "❌ Ma'lumotlarni olishda xato yuz berdi."
            keyboard = [['🏠 Bosh menyu']]
            self.send_message(chat_id, response, {'keyboard': keyboard, 'resize_keyboard': True})
        finally:
            session.close()
            
    def handle_contact_info(self, chat_id):
        """Bog'lanish ma'lumotlari"""
        response = """
📞 <b>Biz bilan bog'laning</b>

📱 <b>Telefon:</b> +998 90 123 45 67
📧 <b>Email:</b> info@fastfood.uz
🌐 <b>Website:</b> www.fastfood.uz
📍 <b>Manzil:</b> Toshkent sh., Amir Temur ko'chasi 15

🕰 <b>Ish vaqti:</b>
• Dushanba-Yakshanba: 08:00 - 23:00
• Yetkazib berish: 24/7

🚚 <b>Yetkazib berish:</b>
• Toshkent shahri bo'ylab: <b>BEPUL</b>
• Yetkazib berish vaqti: 30-60 daqiqa
• Minimal buyurtma: 15,000 so'm

💳 <b>To'lov usullari:</b>
• Naqd pul
• Plastic karta (Uzcard, Visa, MasterCard)
• Click, Payme

📞 <b>Qo'llab-quvvatlash:</b>
Savollar bo'lsa, 24/7 operator bilan bog'laning!
        """
        
        keyboard = [
            ['📞 Operator chaqirish', '📋 Shikoyat qoldirish'],
            ['📅 Bron qilish', '🎁 Chegirmalar'],
            ['🏠 Bosh menyu']
        ]
        
        self.send_message(chat_id, response, {'keyboard': keyboard, 'resize_keyboard': True})
        
    def handle_bot_info(self, chat_id):
        """Bot haqida ma'lumot"""
        response = f"""
ℹ️ <b>Fast Food Delivery Bot</b>

🍔 <b>Xizmatlar:</b>
• Tez va oson buyurtma berish
• Keng mahsulotlar tanlovi
• 24/7 yetkazib berish
• Turli to'lov usullari
• Buyurtmani real-time kuzatish

🔄 <b>Bot imkoniyatlari:</b>
• 🍽 Menyu ko'rish va buyurtma berish
• 🛒 Savat boshqaruvi
• 📋 Buyurtmalar tarixi
• 📍 Manzil saqlash
• 📞 Qo'llab-quvvatlash

📈 <b>Versiya ma'lumotlari:</b>
• Bot versiya: 2.0
• So'nggi yangilanish: {datetime.now().strftime('%d.%m.%Y')}
• Database: MySQL
• Til: O'zbek, Rus

👨‍💻 <b>Ishlab chiquvchi:</b>
@sinsnvjsnvos_bot

💰 <b>Narxlar:</b>
• Burgerlar: 20,000-25,000 so'm
• Pitsalar: 35,000-45,000 so'm
• Ichimliklar: 3,000-8,000 so'm
• Lavashlar: 16,000-20,000 so'm

⭐️ <b>Fikr-mulohaza:</b>
Botni yaxshilash uchun takliflaringizni yuboring!
        """
        
        keyboard = [
            ['📈 Statistika', '🔄 Yangiliklar'],
            ['⭐️ Baholash', '💬 Taklif berish'],
            ['🏠 Bosh menyu']
        ]
        
        self.send_message(chat_id, response, {'keyboard': keyboard, 'resize_keyboard': True})
            
    def handle_start(self, chat_id, user_data):
        """Start buyrug'ini qayta ishlash"""
        self.save_user(user_data)
        user_id = user_data['id']
        user_name = user_data.get('first_name', 'Foydalanuvchi')
        
        if user_id == ADMIN_ID:
            response = f"👑 <b>Salom Admin {user_name}!</b>\n\n🎛 <i>Admin paneliga xush kelibsiz!</i>\n\n✅ Bot muvaffaqiyatli ishlamoqda!\n\n📊 Quyidagi tugmalardan foydalaning:"
            keyboard = self.get_admin_keyboard()
        else:
            response = f"👋 <b>Salom {user_name}!</b>\n\n🍔 <i>Fast Food botiga xush kelibsiz!</i>\n\n📱 Mahsulotlarni buyurtma qiling:"
            keyboard = self.get_user_keyboard()
        
        self.send_message(chat_id, response, keyboard)
        
    def handle_menu(self, chat_id, user_id):
        """Menyu ko'rsatish"""
        response = "🍽 <b>Bizning Menyu</b>\n\n📂 Kategoriyani tanlang:"
        keyboard = self.get_categories_keyboard()
        self.send_message(chat_id, response, keyboard)
        self.user_states[user_id] = 'choosing_category'
        
    def handle_category_choice(self, chat_id, user_id, category_name):
        """Kategoriya tanlov - faqat inline keyboard"""
        products = self.get_products_by_category(category_name)
        
        if products:
            response = f"🍽 <b>{category_name}</b>\n\n📋 <b>Mahsulotlarni tanlang:</b>"
            inline_keyboard = []
            
            # Har bir mahsulot uchun inline tugma
            for product in products:
                inline_keyboard.append([{
                    'text': f"🍴 {product.name} - {product.price:,} so'm",
                    'callback_data': f"product_detail_{product.id}"
                }])
            
            # Pastki tugmalar ham inline keyboard da
            inline_keyboard.append([
                {'text': '🔙 Orqaga', 'callback_data': 'back_to_menu'},
                {'text': '🛒 Savatim', 'callback_data': 'view_cart'}
            ])
            
        else:
            response = f"😔 <b>{category_name}</b> da hozircha mahsulot yo'q."
            inline_keyboard = [
                [{'text': '🔙 Orqaga', 'callback_data': 'back_to_menu'}]
            ]
            
        # Faqat bitta xabar - inline keyboard bilan
        self.send_message_with_inline(chat_id, response, inline_keyboard)
        self.user_states[user_id] = f'choosing_product:{category_name}'
        
    def show_product_detail(self, chat_id, user_id, product_id, current_qty=1):
        """Mahsulot batafsil ma'lumotlarini ko'rsatish - miqdor bilan"""
        session = self.db.session_factory()
        try:
            product = session.query(Product).get(product_id)
            if not product:
                self.send_message(chat_id, "❌ Mahsulot topilmadi.")
                return
            
            # Mahsulot ma'lumotlari
            response = f"🍽 <b>{product.name}</b>\n\n"
            response += f"💰 <b>Narx:</b> {product.price:,} so'm\n"
            if product.description:
                response += f"📝 <b>Ta'rif:</b> {product.description}\n"
            response += f"\n📦 <b>Miqdor:</b> {current_qty} ta\n"
            response += f"💰 <b>Jami:</b> {product.price * current_qty:,} so'm"
            
            # Miqdor boshqaruv tugmalari
            inline_keyboard = [
                [
                    {'text': '➖', 'callback_data': f'qty_minus_{product_id}_{current_qty}'},
                    {'text': f'📦 {current_qty}', 'callback_data': f'qty_info_{product_id}'},
                    {'text': '➕', 'callback_data': f'qty_plus_{product_id}_{current_qty}'}
                ],
                [
                    {'text': f'🛒 Savatga qo\'shish ({current_qty} ta)', 'callback_data': f'add_to_cart_{product_id}_{current_qty}'}
                ],
                [
                    {'text': '🔙 Orqaga', 'callback_data': 'back_to_category'},
                    {'text': '🛒 Savatim', 'callback_data': 'view_cart'}
                ]
            ]
            
            # Agar mahsulotda rasm bo'lsa, rasm yuborish
            if hasattr(product, 'image') and product.image:
                self.send_photo(chat_id, product.image, response, 
                    {'inline_keyboard': inline_keyboard})
            else:
                # Rasm bo'lmasa, matn bilan yuborish
                self.send_message_with_inline(chat_id, response, inline_keyboard)
                
        except Exception as e:
            print(f"❌ Mahsulot ma'lumotlarini ko'rsatishda xato: {e}")
            self.send_message(chat_id, "❌ Xato yuz berdi.")
        finally:
            session.close()
    
    def handle_callback_query(self, callback_query):
        """Inline tugma bosilganda"""
        chat_id = callback_query['message']['chat']['id']
        user_id = callback_query['from']['id']
        data = callback_query['data']
        callback_query_id = callback_query['id']
        
        # Callback javob berish
        self.answer_callback_query(callback_query_id)
        
        if data.startswith('product_detail_'):
            product_id = int(data.replace('product_detail_', ''))
            self.show_product_detail(chat_id, user_id, product_id)
            
        elif data.startswith('qty_plus_'):
            # Miqdorni oshirish
            parts = data.split('_')
            product_id = int(parts[2])
            current_qty = int(parts[3])
            new_qty = min(current_qty + 1, 99)  # Maksimal 99
            self.show_product_detail(chat_id, user_id, product_id, new_qty)
            
        elif data.startswith('qty_minus_'):
            # Miqdorni kamaytirish
            parts = data.split('_')
            product_id = int(parts[2])
            current_qty = int(parts[3])
            new_qty = max(current_qty - 1, 1)  # Minimal 1
            self.show_product_detail(chat_id, user_id, product_id, new_qty)
            
        elif data.startswith('add_to_cart_'):
            # Savatga qo'shish
            parts = data.split('_')
            if len(parts) >= 4:
                product_id = int(parts[3])
                quantity = int(parts[4]) if len(parts) > 4 else 1
            else:
                product_id = int(parts[2])
                quantity = 1
            
            session = self.db.session_factory()
            try:
                product = session.query(Product).get(product_id)
                if product and self.add_to_cart(user_id, product.id, quantity):
                    response = f"✅ <b>{product.name}</b> savatga qo'shildi!\n\n📦 Miqdor: {quantity} ta\n💰 Narx: {product.price * quantity:,} so'm"
                    
                    inline_keyboard = [
                        [
                            {'text': '🛒 Savatim', 'callback_data': 'view_cart'},
                            {'text': '➕ Yana qo\'shish', 'callback_data': 'back_to_category'}
                        ],
                        [
                            {'text': '🍽 Menyu', 'callback_data': 'back_to_menu'}
                        ]
                    ]
                    
                    self.send_message_with_inline(chat_id, response, inline_keyboard)
                else:
                    self.send_message(chat_id, "❌ Mahsulotni savatga qo'shib bo'lmadi.")
            except Exception as e:
                print(f"❌ Mahsulot qo'shishda xato: {e}")
                self.send_message(chat_id, "❌ Xato yuz berdi.")
            finally:
                session.close()
                
        elif data == 'back_to_menu':
            self.handle_menu(chat_id, user_id)
            
        elif data == 'view_cart':
            self.handle_cart(chat_id, user_id)
            
        elif data == 'start_order':
            self.start_order_process(chat_id, user_id)
            
        elif data == 'clear_cart':
            # Savatni tozalash
            session = self.db.session_factory()
            try:
                session.query(CartItem).filter_by(user_id=str(user_id)).delete()
                session.commit()
                response = "🗑 <b>Savat tozalandi!</b>\n\n🍽 Menyu bo'limidan yangi mahsulotlar tanlang."
                inline_keyboard = [
                    [{'text': '🍽 Menyu', 'callback_data': 'back_to_menu'}]
                ]
                self.send_message_with_inline(chat_id, response, inline_keyboard)
            except Exception as e:
                print(f"❌ Savatni tozalashda xato: {e}")
                self.send_message(chat_id, "❌ Xato yuz berdi.")
            finally:
                session.close()
            
        elif data == 'back_to_category':
            # Oxirgi kategoriyaga qaytish
            state = self.user_states.get(user_id, '')
            if state.startswith('choosing_product:'):
                category_name = state.replace('choosing_product:', '')
                self.handle_category_choice(chat_id, user_id, category_name)
            else:
                self.handle_menu(chat_id, user_id)
            
        elif data.startswith('confirm_add_'):
            # Savatga qo'shishni tasdiqlash: confirm_add_productid_qty
            parts = data.split('_')
            product_id = int(parts[2])
            quantity = int(parts[3])
            
            session = self.db.session_factory()
            try:
                product = session.query(Product).get(product_id)
                if product and self.add_to_cart(user_id, product_id, quantity):
                    response = f"✅ <b>{product.name}</b> savatga qo'shildi!\n\n"
                    response += f"📦 Miqdor: {quantity} ta\n"
                    response += f"💰 Narx: {product.price:,} so'm\n"
                    response += f"💵 Jami: {product.price * quantity:,} so'm"
                    
                    inline_keyboard = [
                        [
                            {'text': '🛒 Savatim', 'callback_data': 'view_cart'},
                            {'text': '➕ Yana qo\'shish', 'callback_data': 'back_to_category'}
                        ],
                        [
                            {'text': '🍽 Menyu', 'callback_data': 'back_to_menu'}
                        ]
                    ]
                    self.send_message_with_inline(chat_id, response, inline_keyboard)
                else:
                    self.send_message(chat_id, "❌ Mahsulotni savatga qo'shib bo'lmadi.")
            except Exception as e:
                print(f"❌ Savatga qo'shishda xato: {e}")
                self.send_message(chat_id, "❌ Xato yuz berdi.")
            finally:
                session.close()
                
    def answer_callback_query(self, callback_query_id, text=None):
        """Callback query ga javob berish"""
        url = f"{self.base_url}/answerCallbackQuery"
        data = {'callback_query_id': callback_query_id}
        if text:
            data['text'] = text
        try:
            requests.post(url, data=data, timeout=5)
        except Exception as e:
            print(f"❌ Callback javob berishda xato: {e}")
    
    def handle_cart(self, chat_id, user_id):
        """Savat ko'rsatish - inline keyboard bilan"""
        cart_items = self.get_cart_items(user_id)
        
        if not cart_items:
            response = "🛒 <b>Sizning savatingiz</b>\n\n📭 <i>Savat bo'sh</i>\n\n🍽 Menyu bo'limidan mahsulot tanlang!"
            inline_keyboard = [
                [{'text': '🍽 Menyu', 'callback_data': 'back_to_menu'}]
            ]
        else:
            session = self.db.session_factory()
            try:
                response = "🛒 <b>Sizning savatingiz</b>\n\n"
                total = 0
                
                for item in cart_items:
                    product = session.query(Product).filter_by(id=item.product_id).first()
                    if product:
                        item_total = product.price * item.quantity
                        total += item_total
                        response += f"• <b>{product.name}</b>\n"
                        response += f"   Miqdor: {item.quantity} ta\n"
                        response += f"   Narx: {item_total:,} so'm\n\n"
                
                response += f"💰 <b>Jami: {total:,} so'm</b>"
                inline_keyboard = [
                    [{'text': '📲 Buyurtma berish', 'callback_data': 'start_order'}],
                    [
                        {'text': '🗑 Savatni tozalash', 'callback_data': 'clear_cart'},
                        {'text': '🍽 Menyu', 'callback_data': 'back_to_menu'}
                    ]
                ]
            except Exception as e:
                print(f"❌ Savat ko'rsatishda xato: {e}")
                response = "❌ Savatni ko'rsatishda xato."
                inline_keyboard = [
                    [{'text': '🍽 Menyu', 'callback_data': 'back_to_menu'}]
                ]
            finally:
                session.close()
                
        self.send_message_with_inline(chat_id, response, inline_keyboard)
        
    def start_order_process(self, chat_id, user_id):
        """Buyurtma jarayonini boshlash - telefon raqam so'rash"""
        cart_items = self.get_cart_items(user_id)
        if not cart_items:
            self.send_message(chat_id, "❌ Savatingiz bo'sh. Avval mahsulot qo'shing.")
            return
            
        response = "📱 <b>Buyurtma berish</b>\n\n"
        response += "🚚 Yetkazib berish uchun telefon raqamingizni yuboring\n\n"
        response += "📝 <i>Masalan: +998901234567</i>"
        
        keyboard = {
            'keyboard': [
                [{'text': '📱 Raqam yuborish', 'request_contact': True}],
                ['🔙 Orqaga']
            ],
            'resize_keyboard': True
        }
        
        self.send_message(chat_id, response, keyboard)
        self.user_states[user_id] = 'waiting_phone'
        
    def handle_phone_number(self, chat_id, user_id, phone_number):
        """Telefon raqamni saqlash va lokatsiya so'rash"""
        # Telefon raqamni tozalash
        if phone_number.startswith('+'):
            phone_number = phone_number[1:]  # + ni olib tashlash
        
        # Telefon raqamni saqlash
        session = self.db.session_factory()
        try:
            user = session.query(User).filter_by(user_id=str(user_id)).first()
            if user:
                user.phone = phone_number
                session.commit()
                
                response = f"✅ Telefon raqam saqlandi: <code>{phone_number}</code>\n\n"
                response += "📍 <b>Endi manzilingizni yuboring</b>\n\n"
                response += "📍 Joylashuvingizni yuboring yoki manzilni yozing\n"
                response += "📝 <i>Masalan: Toshkent, Chilonzor tumani...</i>"
                
                keyboard = {
                    'keyboard': [
                        [{'text': '📍 Lokatsiya yuborish', 'request_location': True}],
                        ['🔙 Orqaga']
                    ],
                    'resize_keyboard': True
                }
                
                self.send_message(chat_id, response, keyboard)
                self.user_states[user_id] = 'waiting_location'
            else:
                self.send_message(chat_id, "❌ Foydalanuvchi topilmadi.")
        except Exception as e:
            print(f"❌ Telefon raqam saqlashda xato: {e}")
            session.rollback()
            self.send_message(chat_id, "❌ Xato yuz berdi.")
        finally:
            session.close()
            
    def handle_location(self, chat_id, user_id, location_data):
        """Lokatsiya saqlash va buyurtma tasdiqlash"""
        session = self.db.session_factory()
        try:
            user = session.query(User).filter_by(user_id=str(user_id)).first()
            if user:
                # Lokatsiya ma'lumotlarini saqlash
                if isinstance(location_data, dict) and 'latitude' in location_data:
                    # Geolokatsiya
                    lat = location_data['latitude']
                    lon = location_data['longitude']
                    address = f"Koordinatalar: {lat:.6f}, {lon:.6f}"
                else:
                    # Matn manzil
                    address = str(location_data)
                    
                user.address = address
                session.commit()
                
                # Lokatsiya saqlandi xabari
                response = f"✅ <b>Lokatsiya saqlandi!</b>\n\n"
                response += f"📍 <b>Manzil:</b> {address}\n\n"
                response += "📄 <b>Buyurtmangizni tasdiqlang:</b>"
                
                self.send_message(chat_id, response)
                
                # Buyurtma tasdiqlash
                self.show_order_confirmation(chat_id, user_id)
            else:
                self.send_message(chat_id, "❌ Foydalanuvchi topilmadi.")
        except Exception as e:
            print(f"❌ Lokatsiya saqlashda xato: {e}")
            session.rollback()
            self.send_message(chat_id, "❌ Xato yuz berdi.")
        finally:
            session.close()
            
    def show_order_confirmation(self, chat_id, user_id):
        """Buyurtma tasdiqlash"""
        session = self.db.session_factory()
        try:
            user = session.query(User).filter_by(user_id=str(user_id)).first()
            cart_items = self.get_cart_items(user_id)
            
            if not user or not cart_items:
                self.send_message(chat_id, "❌ Ma'lumotlar topilmadi.")
                return
                
            response = "📋 <b>Buyurtma tasdiqlash</b>\n\n"
            response += f"👤 <b>Ism:</b> {user.first_name}\n"
            response += f"📱 <b>Telefon:</b> {user.phone}\n"
            response += f"📍 <b>Manzil:</b> {user.address}\n\n"
            response += "🛒 <b>Buyurtma tarkibi:</b>\n\n"
            
            total = 0
            item_count = 0
            
            for item in cart_items:
                product = session.query(Product).filter_by(id=item.product_id).first()
                if product:
                    item_total = product.price * item.quantity
                    total += item_total
                    item_count += item.quantity
                    response += f"• <b>{product.name}</b>\n"
                    response += f"   🔢 {item.quantity} ta x {product.price:,} = {item_total:,} so'm\n\n"
            
            response += f"📦 <b>Jami:</b> {item_count} ta mahsulot\n"
            response += f"💵 <b>Umumiy narx:</b> {total:,} so'm\n\n"
            response += "❓ <b>Buyurtmani tasdiqlay sizmi?</b>"
            
            keyboard = {
                'keyboard': [
                    ['✅ Tasdiqlash', '❌ Bekor qilish'],
                    ['🔙 Orqaga']
                ],
                'resize_keyboard': True
            }
            
            self.send_message(chat_id, response, keyboard)
            self.user_states[user_id] = 'confirming_order'
            
        except Exception as e:
            print(f"❌ Buyurtma tasdiqlashda xato: {e}")
            self.send_message(chat_id, "❌ Xato yuz berdi.")
        finally:
            session.close()
            
    def confirm_order(self, chat_id, user_id):
        """Buyurtmani tasdiqlash va guruhga jo'natish"""
        session = self.db.session_factory()
        try:
            user = session.query(User).filter_by(user_id=str(user_id)).first()
            cart_items = self.get_cart_items(user_id)
            
            if not user or not cart_items:
                self.send_message(chat_id, "❌ Ma'lumotlar topilmadi.")
                return
                
            # Buyurtma yaratish
            total = 0
            order_items = []
            
            for item in cart_items:
                product = session.query(Product).filter_by(id=item.product_id).first()
                if product:
                    item_total = product.price * item.quantity
                    total += item_total
                    order_items.append({
                        'name': product.name,
                        'quantity': item.quantity,
                        'price': product.price,
                        'total': item_total
                    })
            
            # Order ma'lumotlarini tayyorlash
            order_data = {
                'user_id': str(user_id),
                'total_amount': total,
                'status': 'pending',
                'items': json.dumps(order_items, ensure_ascii=False)
            }
            
            new_order = Order(**order_data)
            session.add(new_order)
            session.commit()
            
            order_id = new_order.id
            
            # Savatni tozalash
            session.query(CartItem).filter_by(user_id=str(user_id)).delete()
            session.commit()
            
            # Foydalanuvchiga xabar
            response = f"✅ <b>Buyurtma muvaffaqiyatli qabul qilindi!</b>\n\n"
            response += f"🔢 <b>Buyurtma raqami:</b> #{order_id}\n"
            response += f"💵 <b>Jami:</b> {total:,} so'm\n\n"
            response += "🚚 <i>Tez orada siz bilan bog'lanamiz!</i>\n\n"
            response += "🙏 Rahmat!"
            
            keyboard = {
                'keyboard': [
                    ['🍽 Menyu', '📋 Buyurtmalarim'],
                    ['🛎 Yordam']
                ],
                'resize_keyboard': True
            }
            
            self.send_message(chat_id, response, keyboard)
            
            # Admin/Guruhga buyurtma jo'natish (agar GROUP_CHAT_ID bor bo'lsa)
            self.send_order_to_group(order_id, user, order_items, total)
            
            # User state ni tozalash
            if user_id in self.user_states:
                del self.user_states[user_id]
                
        except Exception as e:
            print(f"❌ Buyurtma tasdiqlanishda xato: {e}")
            session.rollback()
            self.send_message(chat_id, "❌ Buyurtma tasdiqlanmadi. Qayta urinib ko'ring.")
        finally:
            session.close()
            
    def send_order_to_group(self, order_id, user, order_items, total):
        """Buyurtmani guruhga jo'natish"""
        try:
            # Guruh ID sini .env dan olish (agar bor bo'lsa)
            GROUP_CHAT_ID = os.getenv('GROUP_CHAT_ID')
            
            if not GROUP_CHAT_ID:
                print("📝 GROUP_CHAT_ID .env da topilmadi. Guruhga jo'natilmadi.")
                return
                
            message = f"🎆 <b>YANGI BUYURTMA</b> 🎆\n\n"
            message += f"🔢 <b>Buyurtma #:</b> {order_id}\n"
            message += f"👤 <b>Mijoz:</b> {user.first_name}\n"
            message += f"📱 <b>Telefon:</b> {user.phone}\n"
            message += f"📍 <b>Manzil:</b> {user.address}\n\n"
            message += "🛒 <b>Buyurtma tarkibi:</b>\n"
            
            for item in order_items:
                message += f"• <b>{item['name']}</b>\n"
                message += f"   {item['quantity']} ta x {item['price']:,} = {item['total']:,} so'm\n\n"
            
            message += f"💵 <b>JAMI: {total:,} so'm</b>\n\n"
            message += f"⏰ <b>Vaqt:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}"
            
            # Guruhga jo'natish
            url = f"{self.base_url}/sendMessage"
            data = {
                'chat_id': GROUP_CHAT_ID,
                'text': message,
                'parse_mode': 'HTML'
            }
            
            response = requests.post(url, data=data, timeout=10)
            if response.json().get('ok'):
                print(f"✅ Buyurtma #{order_id} guruhga jo'natildi")
            else:
                print(f"❌ Guruhga jo'natishda xato: {response.json()}")
                
        except Exception as e:
            print(f"❌ Guruhga buyurtma jo'natishda xato: {e}")
    
    def handle_admin_stats(self, chat_id):
        """Admin statistika"""
        session = self.db.session_factory()
        try:
            user_count = session.query(User).count()
            product_count = session.query(Product).count()
            category_count = session.query(Category).count()
            order_count = session.query(Order).count()
            
            response = f"""
📊 <b>Bot Statistikasi</b>

👥 Foydalanuvchilar: <b>{user_count}</b>
🍽 Mahsulotlar: <b>{product_count}</b>
📂 Kategoriyalar: <b>{category_count}</b>
📋 Buyurtmalar: <b>{order_count}</b>
📅 Bugun: <i>{datetime.now().strftime('%d.%m.%Y')}</i>
⏰ Vaqt: <i>{datetime.now().strftime('%H:%M')}</i>

✅ Bot faol ishlayapti!
            """
            
        except Exception as e:
            print(f"❌ Statistika olishda xato: {e}")
            response = "❌ Statistika olishda xato yuz berdi."
        finally:
            session.close()
            
        self.send_message(chat_id, response)
        
    def handle_message(self, message):
        """Xabarni qayta ishlash"""
        chat_id = message['chat']['id']
        user = message['from']
        text = message.get('text', '')
        user_id = user['id']
        user_name = user.get('first_name', 'Foydalanuvchi')
        
        # Rasm, video, fayl check
        photo = message.get('photo')
        video = message.get('video')
        document = message.get('document')
        caption = message.get('caption', '')
        
        print(f"📨 {user_name} ({user_id}): {text or 'Media fayl'}")
        
        # Agar admin broadcast kutmoqda bo'lsa va media fayl yuborganida
        if user_id == ADMIN_ID and user_id in self.user_states and self.user_states[user_id] == 'waiting_broadcast_message':
            if photo:
                # Rasm broadcast
                photo_id = photo[-1]['file_id']  # Eng katta rasm
                self.send_message(chat_id, "📤 <b>Rasm barcha foydalanuvchilarga yuborilmoqda...</b>")
                success, failed = self.broadcast_photo(photo_id, caption, user_id)
                
                result_message = f"""
✅ <b>Rasm yuborildi!</b>

📊 <b>Natijalar:</b>
✅ Muvaffaqiyatli: <b>{success}</b> ta
❌ Xato: <b>{failed}</b> ta
📤 Jami: <b>{success + failed}</b> ta foydalanuvchi

📝 <b>Izoh:</b> <i>{caption or 'Izohsiz'}</i>
                """
                keyboard = self.get_admin_keyboard()
                self.send_message(chat_id, result_message, keyboard)
                del self.user_states[user_id]
                return
                
            elif video:
                # Video broadcast
                video_id = video['file_id']
                self.send_message(chat_id, "📤 <b>Video barcha foydalanuvchilarga yuborilmoqda...</b>")
                success, failed = self.broadcast_video(video_id, caption, user_id)
                
                result_message = f"""
✅ <b>Video yuborildi!</b>

📊 <b>Natijalar:</b>
✅ Muvaffaqiyatli: <b>{success}</b> ta
❌ Xato: <b>{failed}</b> ta
📤 Jami: <b>{success + failed}</b> ta foydalanuvchi

📝 <b>Izoh:</b> <i>{caption or 'Izohsiz'}</i>
                """
                keyboard = self.get_admin_keyboard()
                self.send_message(chat_id, result_message, keyboard)
                del self.user_states[user_id]
                return
                
            elif document:
                # Fayl broadcast
                document_id = document['file_id']
                self.send_message(chat_id, "📤 <b>Fayl barcha foydalanuvchilarga yuborilmoqda...</b>")
                success, failed = self.broadcast_document(document_id, caption, user_id)
                
                result_message = f"""
✅ <b>Fayl yuborildi!</b>

📊 <b>Natijalar:</b>
✅ Muvaffaqiyatli: <b>{success}</b> ta
❌ Xato: <b>{failed}</b> ta
📤 Jami: <b>{success + failed}</b> ta foydalanuvchi

📝 <b>Fayl nomi:</b> <i>{document.get('file_name', 'Fayl')}</i>
📝 <b>Izoh:</b> <i>{caption or 'Izohsiz'}</i>
                """
                keyboard = self.get_admin_keyboard()
                self.send_message(chat_id, result_message, keyboard)
                del self.user_states[user_id]
                return
        
        # Buyruqlar
        if text.startswith('/start'):
            self.handle_start(chat_id, user)
            
        elif text.startswith('/admin'):
            if user_id == ADMIN_ID:
                response = "👑 <b>Admin Panel</b>\n\n🎛 Boshqaruv tugmalarini tanlang:"
                keyboard = self.get_admin_keyboard()
                self.send_message(chat_id, response, keyboard)
            else:
                self.send_message(chat_id, "❌ Sizda admin huquqlari yo'q!")
                
        # Admin tugmalar
        elif text == '🍽 Menyu boshqaruvi' and user_id == ADMIN_ID:
            response = """
🍽 <b>Menyu Boshqaruvi</b>

📝 Mavjud amallar:
• ➕ Mahsulot qo'shish
• ✏️ Mahsulotni tahrirlash  
• 🗑 Mahsulotni o'chirish
• 📂 Kategoriya boshqaruvi

Tugmalardan foydalaning:
            """
            keyboard = [
                ['➕ Mahsulot qo\'shish', '📂 Kategoriyalar'],
                ['📋 Mahsulotlar ro\'yxati', '🔙 Orqaga']
            ]
            self.send_message(chat_id, response, {'keyboard': keyboard, 'resize_keyboard': True})
            
        elif text == '📋 Buyurtmalar' and user_id == ADMIN_ID:
            session = self.db.session_factory()
            try:
                orders = session.query(Order).order_by(Order.created_at.desc()).limit(10).all()
                if orders:
                    response = "📋 <b>So'nggi Buyurtmalar</b>\n\n"
                    for order in orders:
                        response += f"🔢 Buyurtma #{order.id}\n"
                        response += f"👤 Foydalanuvchi ID: {order.user_id}\n"
                        response += f"💰 Jami: {order.total_amount:,} so'm\n"
                        response += f"📅 {order.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"
                else:
                    response = "📋 <b>Buyurtmalar</b>\n\n📭 Hozircha buyurtmalar yo'q."
            except Exception as e:
                print(f"❌ Buyurtmalar olishda xato: {e}")
                response = "❌ Buyurtmalar olishda xato."
            finally:
                session.close()
            self.send_message(chat_id, response)
            
        elif text == '📊 Statistika' and user_id == ADMIN_ID:
            self.handle_admin_stats(chat_id)
            
        elif text == '🔄 Bot holati' and user_id == ADMIN_ID:
            response = f"""
🔄 <b>Bot Holati</b>

✅ Status: <i>Aktiv</i>
🤖 Bot: <i>Ishlayapti</i>
🗄 Database: <i>MySQL OK</i>
👑 Admin: <i>{user_name}</i>
🆔 Admin ID: <i>{user_id}</i>
⏰ Vaqt: <i>{datetime.now().strftime('%H:%M:%S')}</i>
📅 Sana: <i>{datetime.now().strftime('%d.%m.%Y')}</i>
            """
            self.send_message(chat_id, response)
            
        elif text == '📤 Xabar yuborish' and user_id == ADMIN_ID:
            response = """
📤 <b>Barcha foydalanuvchilarga xabar yuborish</b>

📝 Quyidagi formatlardan birini yuboring:
• <b>Matn xabar</b> - oddiy matn
• <b>Rasm + matn</b> - rasm va izoh
• <b>Video + matn</b> - video va izoh
• <b>Fayl + matn</b> - har qanday fayl va izoh

✍️ Xabaringizni yuboring:
            """
            keyboard = [['🔙 Orqaga']]
            self.send_message(chat_id, response, {'keyboard': keyboard, 'resize_keyboard': True})
            self.user_states[user_id] = 'waiting_broadcast_message'
            
        # Foydalanuvchi tugmalar
        elif text in ['🍽 Menyu ko\'rish', '🍽 Menyu']:
            self.handle_menu(chat_id, user_id)
            
        elif text in ['🛒 Savatim', '🛒 Savat']:
            self.handle_cart(chat_id, user_id)
            
        elif text == '📋 Buyurtmalarim':
            self.handle_user_orders(chat_id, user_id)
            
        elif text == '📍 Manzilim':
            self.handle_user_address(chat_id, user_id)
            
        elif text in ['📞 Bog\'lanish', '📞 Aloqa']:
            self.handle_contact_info(chat_id)
            
        elif text == 'ℹ️ Ma\'lumot':
            self.handle_bot_info(chat_id)
            
        elif text in ['🏠 Bosh menyu', '🔙 Bosh menyu']:
            keyboard = self.get_user_keyboard() if user_id != ADMIN_ID else self.get_admin_keyboard()
            response = "🏠 <b>Bosh menyu</b>" if user_id != ADMIN_ID else "👑 <b>Admin paneli</b>"
            self.send_message(chat_id, response, keyboard)
            if user_id in self.user_states:
                del self.user_states[user_id]
            
        # Kategoriya/mahsulot tanlov
        elif user_id in self.user_states:
            state = self.user_states.get(user_id, '')
            
            if state == 'choosing_category':
                if text == '🔙 Orqaga':
                    keyboard = self.get_user_keyboard() if user_id != ADMIN_ID else self.get_admin_keyboard()
                    self.send_message(chat_id, "🏠 Bosh menyu:", keyboard)
                    del self.user_states[user_id]
                else:
                    # Noto'g'ri tanlov
                    self.send_message(chat_id, "Iltimos, tugmalardan foydalaning 📱")
                    
            elif state.startswith('choosing_product:'):
                if text == '🔙 Orqaga':
                    self.handle_menu(chat_id, user_id)
                elif text in ['🛒 Savat', '🛒 Savatim']:
                    self.handle_cart(chat_id, user_id)
                elif text == '📲 Buyurtma berish':
                    self.start_order_process(chat_id, user_id)
                else:
                    # Inline tugmalardan foydalanishni tavsiya qilish
                    self.send_message(chat_id, "Iltimos, yuqoridagi inline tugmalardan foydalaning 👆")
                    
            elif state == 'waiting_broadcast_message' and user_id == ADMIN_ID:
                if text == '🔙 Orqaga':
                    keyboard = self.get_admin_keyboard()
                    self.send_message(chat_id, "🏠 Admin paneli:", keyboard)
                    del self.user_states[user_id]
                else:
                    # Broadcast xabar yuborish
                    self.send_message(chat_id, "📤 <b>Xabar yuborilmoqda...</b>")
                    success, failed = self.broadcast_message(text, user_id)
                    
                    result_message = f"""
✅ <b>Xabar yuborildi!</b>

📊 <b>Natijalar:</b>
✅ Muvaffaqiyatli: <b>{success}</b> ta
❌ Xato: <b>{failed}</b> ta
📤 Jami: <b>{success + failed}</b> ta foydalanuvchi

📝 <b>Yuborilgan xabar:</b>
<i>{text}</i>
                    """
                    keyboard = self.get_admin_keyboard()
                    self.send_message(chat_id, result_message, keyboard)
                    del self.user_states[user_id]
                    
            # Buyurtma berish jarayoni
            elif state == 'waiting_phone':
                if text == '🔙 Orqaga':
                    self.handle_cart(chat_id, user_id)
                else:
                    # Telefon raqamni olish
                    contact = message.get('contact')
                    if contact:
                        phone = contact.get('phone_number')
                    else:
                        phone = text
                    
                    self.handle_phone_number(chat_id, user_id, phone)
                    
            elif state == 'waiting_location':
                if text == '🔙 Orqaga':
                    self.start_order_process(chat_id, user_id)
                else:
                    # Lokatsiyani olish
                    location = message.get('location')
                    if location:
                        self.handle_location(chat_id, user_id, location)
                    else:
                        self.handle_location(chat_id, user_id, text)
                        
            elif state == 'confirming_order':
                if text == '✅ Tasdiqlash':
                    self.confirm_order(chat_id, user_id)
                elif text == '❌ Bekor qilish':
                    self.send_message(chat_id, "❌ Buyurtma bekor qilindi.")
                    self.handle_cart(chat_id, user_id)
                    del self.user_states[user_id]
                elif text == '🔙 Orqaga':
                    current_state = self.user_states.get(user_id, '')
                    if current_state.startswith('choosing_product:'):
                        # Kategoriyadan orqaga - menuga qaytish
                        self.handle_menu(chat_id, user_id)
                    else:
                        # Boshqa holatlardan orqaga - menuga qaytish
                        self.handle_menu(chat_id, user_id)
                    
        # Default javob
        else:
            if user_id == ADMIN_ID:
                self.send_message(chat_id, "Admin panelidagi tugmalardan foydalaning 👑")
            else:
                self.send_message(chat_id, "Iltimos, tugmalardan foydalaning 📱")
    
    def run(self):
        """Botni ishga tushirish"""
        print("🚀 To'liq funksional bot ishga tushmoqda...")
        print(f"👑 Admin ID: {ADMIN_ID}")
        print("Bot tayyor! Telegram da /start yuboring.\n")
        
        connection_errors = 0
        max_connection_errors = 5
        
        while True:
            try:
                result = self.get_updates()
                
                if result and result.get('ok'):
                    updates = result.get('result', [])
                    connection_errors = 0  # Reset connection error count
                    
                    for update in updates:
                        self.last_update_id = update['update_id']
                        
                        if 'message' in update:
                            self.handle_message(update['message'])
                        elif 'callback_query' in update:
                            self.handle_callback_query(update['callback_query'])
                elif result is None:
                    connection_errors += 1
                    if connection_errors >= max_connection_errors:
                        print(f"❌ {max_connection_errors} ta ketma-ket ulanish xatosi. Internet ulanishini tekshiring.")
                        time.sleep(30)  # 30 soniya kutish
                        connection_errors = 0
                    else:
                        time.sleep(2)  # Qisqa pauza
                
                time.sleep(1)
                
            except KeyboardInterrupt:
                print("\n⏹️ Bot to'xtatilmoqda...")
                break
            except Exception as e:
                print(f"❌ Umumiy xato: {e}")
                time.sleep(5)

def main():
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN .env faylida topilmadi!")
        return
    
    # Bot ulanishini tekshirish
    test_url = f"https://api.telegram.org/bot{BOT_TOKEN}/getMe"
    try:
        response = requests.get(test_url, timeout=10)
        result = response.json()
        
        if result.get('ok'):
            bot_info = result['result']
            print(f"✅ Bot ulanishi muvaffaqiyatli!")
            print(f"🤖 Bot nomi: {bot_info['first_name']}")
            print(f"📝 Username: @{bot_info['username']}")
        else:
            print(f"❌ Bot token xato: {result}")
            return
    except Exception as e:
        print(f"❌ Bot ulanishida xato: {e}")
        return
    
    # Botni ishga tushirish
    bot = FullTelegramBot(BOT_TOKEN)
    bot.run()

if __name__ == "__main__":
    main()