"""
To'liq Telegram Delivery Bot - Ma'lumotlar bazasi bilan
"""

import os
import logging
from datetime import datetime
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.constants import ParseMode
import asyncio

# Database imports
from database import (
    initialize_database, insert_sample_data,
    user_service, category_service, product_service, cart_service, order_service,
    db_manager
)
from models import User, Category, Product, Order, OrderItem, CartItem

# Environment variables
from dotenv import load_dotenv
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot konfiguratsiyasi
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_IDS = [int(x.strip()) for x in os.getenv('ADMIN_IDS', '').split(',') if x.strip()]

# User states
class UserState:
    MAIN_MENU = "main_menu"
    BROWSING_CATEGORIES = "browsing_categories"
    BROWSING_PRODUCTS = "browsing_products"
    VIEWING_CART = "viewing_cart"
    ENTERING_CONTACT = "entering_contact"
    ENTERING_ADDRESS = "entering_address"
    CONFIRMING_ORDER = "confirming_order"


# Global user states dictionary
user_states = {}


class DeliveryBot:
    """Telegram Delivery Bot klassi"""
    
    def __init__(self):
        self.application = None
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Bot ishga tushirishda chaqiriladigan funksiya"""
        user = update.effective_user
        chat_id = update.effective_chat.id
        
        # Foydalanuvchini ma'lumotlar bazasiga qo'shish yoki yangilash
        user_data = {
            'user_id': str(user.id),
            'first_name': user.first_name,
            'last_name': user.last_name,
            'username': user.username
        }
        
        try:
            db_user = user_service.create_or_update_user(user_data)
            logger.info(f"Foydalanuvchi saqlandi: {db_user.user_id}")
        except Exception as e:
            logger.error(f"Foydalanuvchini saqlashda xatolik: {e}")
        
        # Xush kelibsiz xabari
        welcome_text = f"""
🍕 **Xush kelibsiz, {user.first_name}!**

Bu bizning yetkazib berish xizmatimizning rasmiy boti.
Buyurtma berish uchun quyidagi tugmalardan foydalaning.

🛒 **Bizning xizmatlarimiz:**
• Tez yetkazib berish (30-45 daqiqa)
• Sifatli mahsulotlar
• 24/7 ishlaymiz
• Naqd va onlayn to'lov

Boshlash uchun **"🍽️ Menyu"** tugmasini bosing!
        """
        
        await self.show_main_menu(update, context, welcome_text)
    
    async def show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE, 
                           message_text: str = None):
        """Asosiy menyuni ko'rsatish"""
        keyboard = [
            [KeyboardButton("🍽️ Menyu"), KeyboardButton("🛒 Savat")],
            [KeyboardButton("📋 Mening buyurtmalarim"), KeyboardButton("📞 Aloqa")],
            [KeyboardButton("ℹ️ Ma'lumot")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        user_states[update.effective_user.id] = UserState.MAIN_MENU
        
        if message_text is None:
            message_text = "🏠 **Asosiy menyu**\n\nKerakli bo'limni tanlang:"
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                message_text, 
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=None
            )
            await update.callback_query.message.reply_text(
                "Quyidagi tugmalardan birini tanlang:", 
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(
                message_text, 
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
    
    async def show_categories(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Kategoriyalarni ko'rsatish"""
        try:
            categories = category_service.get_all_categories()
            
            if not categories:
                await update.message.reply_text(
                    "❌ Hozircha kategoriyalar mavjud emas.",
                    reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🏠 Bosh sahifa")]], resize_keyboard=True)
                )
                return
            
            keyboard = []
            for category in categories:
                keyboard.append([InlineKeyboardButton(category.name, callback_data=f"category_{category.id}")])
            
            keyboard.append([InlineKeyboardButton("🏠 Bosh sahifa", callback_data="main_menu")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            user_states[update.effective_user.id] = UserState.BROWSING_CATEGORIES
            
            await update.message.reply_text(
                "🍽️ **Kategoriyalar**\n\nQaysi kategoriyadan buyurtma bermoqchisiz?",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            
        except Exception as e:
            logger.error(f"Kategoriyalarni yuklashda xatolik: {e}")
            await update.message.reply_text("❌ Kategoriyalarni yuklashda xatolik yuz berdi.")
    
    async def show_products(self, update: Update, context: ContextTypes.DEFAULT_TYPE, category_id: int):
        """Mahsulotlarni ko'rsatish"""
        try:
            products = product_service.get_products_by_category(category_id)
            category = category_service.get_category_by_id(category_id)
            
            if not products:
                await update.callback_query.edit_message_text(
                    f"❌ {category.name} kategoriyasida hozircha mahsulotlar mavjud emas.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Orqaga", callback_data="show_categories")
                    ]])
                )
                return
            
            keyboard = []
            for product in products:
                price_text = f"{product.price:,.0f} so'm".replace(',', ' ')
                keyboard.append([
                    InlineKeyboardButton(
                        f"{product.name} - {price_text}", 
                        callback_data=f"product_{product.id}"
                    )
                ])
            
            keyboard.append([
                InlineKeyboardButton("🔙 Kategoriyalar", callback_data="show_categories"),
                InlineKeyboardButton("🛒 Savat", callback_data="view_cart")
            ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            user_states[update.effective_user.id] = UserState.BROWSING_PRODUCTS
            
            await update.callback_query.edit_message_text(
                f"🍽️ **{category.name}**\n\nMahsulotni tanlang:",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            
        except Exception as e:
            logger.error(f"Mahsulotlarni yuklashda xatolik: {e}")
            await update.callback_query.edit_message_text("❌ Mahsulotlarni yuklashda xatolik yuz berdi.")
    
    async def show_product_detail(self, update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int):
        """Mahsulot tafsilotlarini ko'rsatish"""
        try:
            product = product_service.get_product_by_id(product_id)
            
            if not product:
                await update.callback_query.edit_message_text(
                    "❌ Mahsulot topilmadi.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Orqaga", callback_data="show_categories")
                    ]])
                )
                return
            
            price_text = f"{product.price:,.0f} so'm".replace(',', ' ')
            
            description = product.description if product.description else "Tavsif mavjud emas"
            
            product_text = f"""
🍽️ **{product.name}**

📝 **Tavsif:** {description}
💰 **Narx:** {price_text}
📦 **Kategoriya:** {product.category.name}
            """
            
            keyboard = [
                [
                    InlineKeyboardButton("➖", callback_data=f"decrease_{product_id}"),
                    InlineKeyboardButton("1", callback_data=f"quantity_{product_id}"),
                    InlineKeyboardButton("➕", callback_data=f"increase_{product_id}")
                ],
                [InlineKeyboardButton("🛒 Savatga qo'shish", callback_data=f"add_to_cart_{product_id}_1")],
                [
                    InlineKeyboardButton("🔙 Orqaga", callback_data=f"category_{product.category_id}"),
                    InlineKeyboardButton("🛒 Savat", callback_data="view_cart")
                ]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if product.image_url:
                try:
                    await update.callback_query.edit_message_media(
                        media=InputMediaPhoto(media=product.image_url, caption=product_text, parse_mode=ParseMode.MARKDOWN),
                        reply_markup=reply_markup
                    )
                except:
                    await update.callback_query.edit_message_text(
                        product_text,
                        reply_markup=reply_markup,
                        parse_mode=ParseMode.MARKDOWN
                    )
            else:
                await update.callback_query.edit_message_text(
                    product_text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
            
        except Exception as e:
            logger.error(f"Mahsulot tafsilotlarini yuklashda xatolik: {e}")
            await update.callback_query.edit_message_text("❌ Mahsulot ma'lumotlarini yuklashda xatolik.")
    
    async def add_to_cart(self, update: Update, context: ContextTypes.DEFAULT_TYPE, 
                         product_id: int, quantity: int = 1):
        """Savatga mahsulot qo'shish"""
        try:
            user_id = str(update.effective_user.id)
            
            # Mahsulotni tekshirish
            product = product_service.get_product_by_id(product_id)
            if not product:
                await update.callback_query.answer("❌ Mahsulot topilmadi!", show_alert=True)
                return
            
            # Savatga qo'shish
            cart_service.add_to_cart(user_id, product_id, quantity)
            
            await update.callback_query.answer(
                f"✅ {product.name} savatga qo'shildi! (miqdor: {quantity})"
            )
            
            # Mahsulot sahifasini yangilash
            await self.show_product_detail(update, context, product_id)
            
        except Exception as e:
            logger.error(f"Savatga qo'shishda xatolik: {e}")
            await update.callback_query.answer("❌ Savatga qo'shishda xatolik!", show_alert=True)
    
    async def view_cart(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Savatni ko'rish"""
        try:
            user_id = str(update.effective_user.id)
            cart_items = cart_service.get_cart_items(user_id)
            
            if not cart_items:
                empty_message = """
🛒 **Savatingiz bo'sh**

Mahsulot qo'shish uchun menyuga o'ting.
                """
                
                keyboard = [[InlineKeyboardButton("🍽️ Menyu", callback_data="show_categories")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                if update.callback_query:
                    await update.callback_query.edit_message_text(
                        empty_message,
                        reply_markup=reply_markup,
                        parse_mode=ParseMode.MARKDOWN
                    )
                else:
                    await update.message.reply_text(
                        empty_message,
                        reply_markup=reply_markup,
                        parse_mode=ParseMode.MARKDOWN
                    )
                return
            
            # Savat ma'lumotlarini tayyorlash
            cart_text = "🛒 **Savatingiz:**\n\n"
            total_amount = 0
            
            keyboard = []
            
            for item in cart_items:
                item_total = item.product.price * item.quantity
                total_amount += item_total
                
                cart_text += f"• **{item.product.name}**\n"
                cart_text += f"  Narx: {item.product.price:,.0f} so'm\n".replace(',', ' ')
                cart_text += f"  Miqdor: {item.quantity} ta\n"
                cart_text += f"  Jami: {item_total:,.0f} so'm\n\n".replace(',', ' ')
                
                # Mahsulot miqdorini o'zgartirish tugmalari
                keyboard.append([
                    InlineKeyboardButton("➖", callback_data=f"cart_decrease_{item.product.id}"),
                    InlineKeyboardButton(f"{item.product.name} ({item.quantity})", callback_data=f"cart_item_{item.product.id}"),
                    InlineKeyboardButton("➕", callback_data=f"cart_increase_{item.product.id}")
                ])
            
            cart_text += f"💰 **Umumiy summa: {total_amount:,.0f} so'm**".replace(',', ' ')
            
            # Tugmalar qo'shish
            keyboard.append([InlineKeyboardButton("🗑️ Savatni tozalash", callback_data="clear_cart")])
            keyboard.append([
                InlineKeyboardButton("🍽️ Menyu", callback_data="show_categories"),
                InlineKeyboardButton("📦 Buyurtma berish", callback_data="start_order")
            ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            user_states[update.effective_user.id] = UserState.VIEWING_CART
            
            if update.callback_query:
                await update.callback_query.edit_message_text(
                    cart_text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text(
                    cart_text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
                
        except Exception as e:
            logger.error(f"Savatni ko'rishda xatolik: {e}")
            error_text = "❌ Savatni yuklashda xatolik yuz berdi."
            
            if update.callback_query:
                await update.callback_query.edit_message_text(error_text)
            else:
                await update.message.reply_text(error_text)
    
    async def start_order_process(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Buyurtma jarayonini boshlash"""
        user_id = str(update.effective_user.id)
        
        # Savatni tekshirish
        cart_items = cart_service.get_cart_items(user_id)
        if not cart_items:
            await update.callback_query.answer("❌ Savatingiz bo'sh!", show_alert=True)
            return
        
        # Telefon raqamini so'rash
        keyboard = [[KeyboardButton("📱 Telefon raqamni yuborish", request_contact=True)]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        user_states[update.effective_user.id] = UserState.ENTERING_CONTACT
        
        await update.callback_query.edit_message_text(
            "📱 **Buyurtma berish uchun telefon raqamingizni yuboring.**\n\n"
            "Quyidagi tugmani bosing yoki raqamni +998XXXXXXXXX formatida kiriting:",
            parse_mode=ParseMode.MARKDOWN
        )
        
        await update.callback_query.message.reply_text(
            "Telefon raqamingizni yuboring:",
            reply_markup=reply_markup
        )
    
    async def handle_contact(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Telefon raqamni qabul qilish"""
        user_id = str(update.effective_user.id)
        
        if update.message.contact:
            phone_number = update.message.contact.phone_number
        else:
            phone_number = update.message.text
            
        # Telefon raqamni formatlash va tekshirish
        if not phone_number.startswith('+'):
            phone_number = '+' + phone_number.lstrip('+')
        
        # Foydalanuvchi ma'lumotlarini yangilash
        user_service.create_or_update_user({
            'user_id': user_id,
            'phone_number': phone_number
        })
        
        context.user_data['phone_number'] = phone_number
        user_states[user_id] = UserState.ENTERING_ADDRESS
        
        # Manzil so'rash
        keyboard = [[KeyboardButton("📍 Joylashuvni yuborish", request_location=True)]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "📍 **Yetkazib berish manzilini yuboring.**\n\n"
            "Joylashuvni yuborish uchun quyidagi tugmani bosing yoki manzilni yozing:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def handle_location(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Joylashuv yoki manzilni qabul qilish"""
        user_id = str(update.effective_user.id)
        
        if update.message.location:
            # GPS joylashuv
            latitude = update.message.location.latitude
            longitude = update.message.location.longitude
            
            context.user_data['latitude'] = latitude
            context.user_data['longitude'] = longitude
            context.user_data['address'] = f"GPS: {latitude}, {longitude}"
            
            # Foydalanuvchi manzilini yangilash
            user_service.update_user_location(user_id, latitude, longitude)
            
        else:
            # Matn shaklida manzil
            address = update.message.text
            context.user_data['address'] = address
        
        await self.confirm_order(update, context)
    
    async def confirm_order(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Buyurtmani tasdiqlash"""
        user_id = str(update.effective_user.id)
        
        # Savat va buyurtma ma'lumotlari
        cart_items = cart_service.get_cart_items(user_id)
        total_amount = sum(item.product.price * item.quantity for item in cart_items)
        
        # Buyurtma ma'lumotlarini tayyorlash
        order_text = "📋 **Buyurtmani tasdiqlang:**\n\n"
        
        for item in cart_items:
            item_total = item.product.price * item.quantity
            order_text += f"• {item.product.name}\n"
            order_text += f"  {item.quantity} × {item.product.price:,.0f} = {item_total:,.0f} so'm\n\n".replace(',', ' ')
        
        order_text += f"💰 **Jami: {total_amount:,.0f} so'm**\n\n".replace(',', ' ')
        order_text += f"📱 **Telefon:** {context.user_data.get('phone_number', 'N/A')}\n"
        order_text += f"📍 **Manzil:** {context.user_data.get('address', 'N/A')}\n\n"
        order_text += "⏱️ **Yetkazib berish vaqti:** 30-45 daqiqa"
        
        keyboard = [
            [InlineKeyboardButton("✅ Tasdiqlash", callback_data="confirm_order_final")],
            [InlineKeyboardButton("❌ Bekor qilish", callback_data="view_cart")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        user_states[user_id] = UserState.CONFIRMING_ORDER
        
        await update.message.reply_text(
            order_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def finalize_order(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Buyurtmani yakunlash"""
        try:
            user_id = str(update.effective_user.id)
            
            # Savat elementlarini olish
            cart_items = cart_service.get_cart_items(user_id)
            if not cart_items:
                await update.callback_query.answer("❌ Savat bo'sh!", show_alert=True)
                return
            
            # Yetkazib berish ma'lumotlari
            delivery_data = {
                'phone': context.user_data.get('phone_number'),
                'address': context.user_data.get('address'),
                'latitude': context.user_data.get('latitude'),
                'longitude': context.user_data.get('longitude')
            }
            
            # Buyurtma yaratish
            order = order_service.create_order(user_id, cart_items, delivery_data)
            
            # Muvaffaqiyatli buyurtma xabari
            success_text = f"""
✅ **Buyurtma muvaffaqiyatli qabul qilindi!**

🏷️ **Buyurtma raqami:** #{order.order_number}
💰 **Summa:** {order.total_amount:,.0f} so'm
⏱️ **Yetkazib berish vaqti:** 30-45 daqiqa

Buyurtma holati haqida sizga xabar beramiz.
Aloqa uchun: {delivery_data['phone']}

Rahmat! 🙏
            """.replace(',', ' ')
            
            keyboard = [[InlineKeyboardButton("🏠 Bosh sahifa", callback_data="main_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.callback_query.edit_message_text(
                success_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            
            # Adminlarga xabar yuborish
            await self.notify_admins_new_order(order)
            
            # User datani tozalash
            context.user_data.clear()
            user_states[user_id] = UserState.MAIN_MENU
            
        except Exception as e:
            logger.error(f"Buyurtmani yakunlashda xatolik: {e}")
            await update.callback_query.edit_message_text(
                "❌ Buyurtmani qayta ishlaganda xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring."
            )
    
    async def notify_admins_new_order(self, order: Order):
        """Adminlarga yangi buyurtma haqida xabar yuborish"""
        try:
            admin_text = f"""
🔔 **YANGI BUYURTMA!**

🏷️ **Buyurtma #:** {order.order_number}
👤 **Mijoz:** {order.user.first_name} {order.user.last_name or ''}
📱 **Telefon:** {order.phone_number}
📍 **Manzil:** {order.delivery_address}
💰 **Summa:** {order.total_amount:,.0f} so'm

📦 **Mahsulotlar:**
            """.replace(',', ' ')
            
            for item in order.order_items:
                admin_text += f"• {item.product.name} × {item.quantity}\n"
            
            admin_text += f"\n⏰ **Vaqt:** {order.created_at.strftime('%d.%m.%Y %H:%M')}"
            
            keyboard = [
                [
                    InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"admin_confirm_{order.id}"),
                    InlineKeyboardButton("❌ Rad etish", callback_data=f"admin_reject_{order.id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            for admin_id in ADMIN_IDS:
                try:
                    await self.application.bot.send_message(
                        chat_id=admin_id,
                        text=admin_text,
                        reply_markup=reply_markup,
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception as e:
                    logger.error(f"Admin {admin_id} ga xabar yuborishda xatolik: {e}")
                    
        except Exception as e:
            logger.error(f"Adminlarga xabar yuborishda xatolik: {e}")
    
    async def show_user_orders(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Foydalanuvchi buyurtmalarini ko'rsatish"""
        try:
            user_id = str(update.effective_user.id)
            orders = order_service.get_user_orders(user_id)
            
            if not orders:
                await update.message.reply_text(
                    "📋 Sizda hali buyurtmalar yo'q.\n\n"
                    "Birinchi buyurtmangizni berishni boshlang! 😊"
                )
                return
            
            orders_text = "📋 **Sizning buyurtmalaringiz:**\n\n"
            
            for order in orders[:5]:  # Oxirgi 5 ta buyurtma
                status_emoji = {
                    'Kutilyapti': '⏳',
                    'Tasdiqlandi': '✅',
                    'Tayyor': '🍽️',
                    'Yetkazildi': '🚚',
                    'Bekor qilindi': '❌'
                }.get(order.status, '❓')
                
                orders_text += f"{status_emoji} **#{order.order_number}**\n"
                orders_text += f"Summa: {order.total_amount:,.0f} so'm\n".replace(',', ' ')
                orders_text += f"Holat: {order.status}\n"
                orders_text += f"Vaqt: {order.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"
            
            if len(orders) > 5:
                orders_text += f"... va yana {len(orders) - 5} ta buyurtma"
            
            await update.message.reply_text(
                orders_text,
                parse_mode=ParseMode.MARKDOWN
            )
            
        except Exception as e:
            logger.error(f"Buyurtmalarni yuklashda xatolik: {e}")
            await update.message.reply_text("❌ Buyurtmalarni yuklashda xatolik yuz berdi.")
    
    async def callback_query_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Callback query'larni boshqarish"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        if data == "main_menu":
            await self.show_main_menu(update, context)
        elif data == "show_categories":
            await self.show_categories(update, context)
        elif data.startswith("category_"):
            category_id = int(data.split("_")[1])
            await self.show_products(update, context, category_id)
        elif data.startswith("product_"):
            product_id = int(data.split("_")[1])
            await self.show_product_detail(update, context, product_id)
        elif data.startswith("add_to_cart_"):
            parts = data.split("_")
            product_id = int(parts[3])
            quantity = int(parts[4])
            await self.add_to_cart(update, context, product_id, quantity)
        elif data == "view_cart":
            await self.view_cart(update, context)
        elif data == "clear_cart":
            user_id = str(update.effective_user.id)
            cart_service.clear_cart(user_id)
            await query.edit_message_text("🗑️ Savat tozalandi!")
            await asyncio.sleep(1)
            await self.view_cart(update, context)
        elif data.startswith("cart_increase_"):
            product_id = int(data.split("_")[2])
            user_id = str(update.effective_user.id)
            cart_service.add_to_cart(user_id, product_id, 1)
            await self.view_cart(update, context)
        elif data.startswith("cart_decrease_"):
            product_id = int(data.split("_")[2])
            user_id = str(update.effective_user.id)
            cart_items = cart_service.get_cart_items(user_id)
            current_item = next((item for item in cart_items if item.product_id == product_id), None)
            if current_item and current_item.quantity > 1:
                cart_service.update_cart_quantity(user_id, product_id, current_item.quantity - 1)
            else:
                cart_service.remove_from_cart(user_id, product_id)
            await self.view_cart(update, context)
        elif data == "start_order":
            await self.start_order_process(update, context)
        elif data == "confirm_order_final":
            await self.finalize_order(update, context)
        # Admin buyruqlari
        elif data.startswith("admin_confirm_"):
            order_id = int(data.split("_")[2])
            await self.admin_confirm_order(update, context, order_id)
        elif data.startswith("admin_reject_"):
            order_id = int(data.split("_")[2])
            await self.admin_reject_order(update, context, order_id)
    
    async def admin_confirm_order(self, update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: int):
        """Admin tomonidan buyurtmani tasdiqlash"""
        try:
            order_service.update_order_status(order_id, "Tasdiqlandi")
            
            order = order_service.get_order_by_id(order_id)
            if order:
                # Mijozga xabar yuborish
                await self.application.bot.send_message(
                    chat_id=int(order.user_id),
                    text=f"✅ Sizning #{order.order_number} buyurtmangiz tasdiqlandi!\n"
                         f"Tayyorlanish vaqti: 30-45 daqiqa"
                )
            
            await update.callback_query.edit_message_text(
                f"✅ Buyurtma #{order.order_number} tasdiqlandi!"
            )
            
        except Exception as e:
            logger.error(f"Buyurtmani tasdiqlashda xatolik: {e}")
            await update.callback_query.answer("❌ Xatolik yuz berdi!", show_alert=True)
    
    async def admin_reject_order(self, update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: int):
        """Admin tomonidan buyurtmani rad etish"""
        try:
            order_service.update_order_status(order_id, "Bekor qilindi")
            
            order = order_service.get_order_by_id(order_id)
            if order:
                # Mijozga xabar yuborish
                await self.application.bot.send_message(
                    chat_id=int(order.user_id),
                    text=f"❌ Kechirasiz, #{order.order_number} buyurtmangiz rad etildi.\n"
                         f"Batafsil ma'lumot uchun aloqa: +998 XX XXX XX XX"
                )
            
            await update.callback_query.edit_message_text(
                f"❌ Buyurtma #{order.order_number} rad etildi!"
            )
            
        except Exception as e:
            logger.error(f"Buyurtmani rad etishda xatolik: {e}")
            await update.callback_query.answer("❌ Xatolik yuz berdi!", show_alert=True)
    
    async def handle_text_messages(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Matnli xabarlarni boshqarish"""
        text = update.message.text
        user_id = update.effective_user.id
        state = user_states.get(user_id, UserState.MAIN_MENU)
        
        if text == "🍽️ Menyu":
            await self.show_categories(update, context)
        elif text == "🛒 Savat":
            await self.view_cart(update, context)
        elif text == "📋 Mening buyurtmalarim":
            await self.show_user_orders(update, context)
        elif text == "📞 Aloqa":
            contact_text = """
📞 **Aloqa ma'lumotlari:**

📱 **Telefon:** +998 XX XXX XX XX
🕐 **Ish vaqti:** 24/7
📍 **Manzil:** Toshkent shahri

💬 **Telegram:** @delivery_support_bot
📧 **Email:** info@delivery.uz

Savollaringiz bo'lsa, bemalol murojaat qiling! 😊
            """
            await update.message.reply_text(contact_text, parse_mode=ParseMode.MARKDOWN)
        elif text == "ℹ️ Ma'lumot":
            info_text = """
ℹ️ **Bizning xizmat haqida:**

🍕 **Yetkazib berish xizmati**
Sifatli taomlar, tez yetkazib berish!

⭐ **Afzalliklar:**
• 30-45 daqiqada yetkazib berish
• Sifatli mahsulotlar
• 24/7 ishlaymiz
• Naqd va onlayn to'lov

📦 **Minimal buyurtma:** 50,000 so'm
🚚 **Yetkazib berish:** Bepul (100,000 so'm dan yuqori)
💳 **To'lov usullari:** Naqd, Click, Payme

Bon appetit! 🍽️
            """
            await update.message.reply_text(info_text, parse_mode=ParseMode.MARKDOWN)
        elif state == UserState.ENTERING_CONTACT:
            await self.handle_contact(update, context)
        elif state == UserState.ENTERING_ADDRESS:
            await self.handle_location(update, context)
        else:
            await update.message.reply_text(
                "Kechirasiz, tushunmadim. Iltimos, tugmalardan foydalaning."
            )
    
    def run(self):
        """Botni ishga tushirish"""
        # Ma'lumotlar bazasini ishga tushirish
        if not initialize_database():
            print("❌ Ma'lumotlar bazasini sozlab bo'lmadi!")
            return
        
        if not db_manager.test_connection():
            print("❌ Ma'lumotlar bazasiga ulanib bo'lmadi!")
            return
        
        print("✅ Ma'lumotlar bazasi ulanishi muvaffaqiyatli!")
        
        # Namunaviy ma'lumotlarni qo'shish
        insert_sample_data()
        
        # Bot applicationni yaratish
        self.application = Application.builder().token(BOT_TOKEN).build()
        
        # Handlerlarni qo'shish
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CallbackQueryHandler(self.callback_query_handler))
        self.application.add_handler(MessageHandler(filters.CONTACT, self.handle_contact))
        self.application.add_handler(MessageHandler(filters.LOCATION, self.handle_location))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text_messages))
        
        print("🚀 Bot ishga tushmoqda...")
        print(f"🔗 Bot nomi: @{BOT_TOKEN.split(':')[0]}")
        
        # Botni ishga tushirish
        self.application.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN o'rnatilmagan! .env faylni to'g'rilang.")
        exit(1)
    
    bot = DeliveryBot()
    bot.run()