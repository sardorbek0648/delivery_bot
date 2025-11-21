
# bot.py
# python-telegram-bot v20+
import asyncio
import random
import json
import logging
import os
import re
import html
from datetime import datetime, timedelta, timezone
from typing import Optional

from telegram import (
    Update,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton,
    Location
)
from telegram.error import BadRequest
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ========== SOZLAMALAR ==========
BOT_TOKEN = "8447079141:AAEekMNhdb0DK2E0fmcNEhr650VkBHFMCSY"   # <<< bu yerga o'zingizning tokenni qo'ying
ADMIN_ID = 5788278697               # <<< asosiy admin id
admins = {ADMIN_ID}

USERS_FILE = "users.json"
ORDERS_FILE = "orders.json"
COURIERS_FILE = "couriers.json"
EARNINGS_FILE = "earnings.json"

# Buyurtmalar kanalining chat ID (o'zgartirdingiz):
BUYURTMALAR_CHANNEL_ID = -1003357292759
# Super-admin kanal yoki chat ID — default asosiy adminga yuboradi, kerak bo'lsa kanal ID qo'ying
SUPERADMIN_CHANNEL_ID = -1003401946836  # Super admin hisobot kanali ID

# ========== LOGGING ==========
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("dostavka_bot")

# ========== YUKLAMALAR VA SAQLASH UTILITYLARI ==========
def load_json(fname, default):
    try:
        if os.path.exists(fname):
            with open(fname, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        log.warning(f"Faylni yuklashda xatolik ({fname}): {e}")
    return default

def save_json(fname, data):
    tmp = fname + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, fname)
    except Exception as e:
        log.error(f"Faylni saqlashda xatolik ({fname}): {e}")

# Foydalanuvchilar va buyurtmalarni fayldan yuklash
_users_data = load_json(USERS_FILE, [])
users = set(int(x) for x in _users_data)

_orders_data = load_json(ORDERS_FILE, [])
orders = _orders_data if isinstance(_orders_data, list) else []

# Couriers
_couriers_data = load_json(COURIERS_FILE, [])
couriers = set(int(x) for x in _couriers_data)

# Earnings per courier
_earnings_data = load_json(EARNINGS_FILE, {})
earnings = {int(k): v for k, v in _earnings_data.items()} if isinstance(_earnings_data, dict) else {}

order_counter = max((o.get("order_number", 0) for o in orders), default=0)

# Xotiradagi taymer vazifalari
expiry_tasks: dict[int, asyncio.Task] = {}

# ========== MENYU & KLAVIATURALAR ==========
menu_data = {
    "Ichimliklar": { "Coca Cola 0.5l": {"price": 8000, "desc": "Salqin ichimlik"},"Coca Cola 1l": {"price": 11000, "desc": "Salqin ichimlik"},"Coca Cola 1.5l": {"price": 14000, "desc": "Salqin ichimlik"}, "Fanta": {"price": 7000, "desc": "Mevali lazzat"}},
    "Fast Food": {"Burger": {"price": 25000, "desc": "Go‘shtli burger"}, "Hot Dog": {"price": 18000, "desc": "Sosiska non ichida"}},
    "Taomlar": {"Palov": {"price": 35000, "desc": "An'anaviy o‘zbek taomi"}, "Manti": {"price": 30000, "desc": "Bug‘da pishirilgan manti"}},
}

def admin_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 Faol buyurtmalar", callback_data="admin_orders")],
        [InlineKeyboardButton("📣 Kanaldagi e'lonlar", callback_data="admin_published")],
        [InlineKeyboardButton("🧹 Barcha buyurtmalarni tozalash", callback_data="admin_clear_all_orders")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("➕ Yangi admin", callback_data="admin_add")],
        [InlineKeyboardButton("❌ Adminni olib tashlash", callback_data="admin_remove")],
        [InlineKeyboardButton("➕ Yetkazib beruvchi", callback_data="admin_add_courier")],
        [InlineKeyboardButton("❌ Yetkazib beruvchi", callback_data="admin_remove_courier")],
    ])

def category_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🥤 Ichimliklar", callback_data="cat_Ichimliklar")],
        [InlineKeyboardButton("🍔 Fast Food", callback_data="cat_Fast Food")],
        [InlineKeyboardButton("🍛 Taomlar", callback_data="cat_Taomlar")],
        [InlineKeyboardButton("🛒 Savat", callback_data="view_cart")],
    ])


def courier_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚚 Mening buyurtmalar", callback_data="courier_my_orders")],
    ])




# ... boshqa klaviatura funksiyalari o'zgarishsiz ...
def product_list_kb(category: str): return InlineKeyboardMarkup([[InlineKeyboardButton(f"{name} — {info['price']} so‘m", callback_data=f"prod_{category}|{name}")] for name, info in menu_data[category].items()] + [[InlineKeyboardButton("◀️ Ortga", callback_data="back_categories"), InlineKeyboardButton("🛒 Savat", callback_data="view_cart")]])
def quantity_kb(category: str, product: str, qty: int): return InlineKeyboardMarkup([ [InlineKeyboardButton("➖", callback_data=f"qty_{category}|{product}|dec"), InlineKeyboardButton(str(qty), callback_data="noop"), InlineKeyboardButton("➕", callback_data=f"qty_{category}|{product}|inc")], [InlineKeyboardButton("🛒 Savatga qo‘shish", callback_data=f"add_{product}|{qty}")], [InlineKeyboardButton("◀️ Menyuga qaytish", callback_data="back_categories")]])
def cart_text_and_total(cart: dict):
    if not cart: return "🛒 Savat bo‘sh.", 0
    lines, total, price_map = [], 0, {p: info["price"] for c in menu_data.values() for p, info in c.items()}
    for name, qty in cart.items():
        summa = price_map.get(name, 0) * qty
        total += summa; lines.append(f"• {name} x{qty} — {summa} so‘m")
    return "🛒 Savat:\n" + "\n".join(lines) + f"\n\nJami: {total} so‘m", total
def cart_menu_kb(has_items: bool):
    rows = [[InlineKeyboardButton("◀️ Menyu", callback_data="back_categories")]]
    if has_items: rows.insert(0, [InlineKeyboardButton("🧹 Tozalash", callback_data="clear_cart"), InlineKeyboardButton("✅ Buyurtma berish", callback_data="checkout")])
    return InlineKeyboardMarkup(rows)

# ========== YORDAMCHI FUNKSIYALAR ==========
def persist_users(): save_json(USERS_FILE, list(users))
def persist_orders(): save_json(ORDERS_FILE, orders)
def persist_couriers(): save_json(COURIERS_FILE, list(couriers))
def persist_earnings():
    # convert keys to str for JSON
    save_json(EARNINGS_FILE, {str(k): v for k, v in earnings.items()})
def load_earnings():
    global earnings
    _d = load_json(EARNINGS_FILE, {})
    earnings = {int(k): v for k, v in _d.items()} if isinstance(_d, dict) else {}
def find_order(order_number: int): return next((o for o in orders if int(o.get("order_number", -1)) == int(order_number)), None)


async def report_superadmin(bot, text: str):
    """Yagona helper: super-admin kanaliga xabar yuboradi (xatolikni loglaydi)."""
    try:
        await bot.send_message(chat_id=SUPERADMIN_CHANNEL_ID, text=text, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        log.warning(f"Superadminga yuborishda xato: {e}")


def normalize_phone(phone: str) -> str:
    """Normalize phone number: remove spaces and punctuation, ensure leading +.
    If number starts with single 0 (local), assume +998 (Uzbekistan) and replace leading 0 with +998.
    """
    if not phone:
        return ""
    s = str(phone).strip()
    # remove everything except digits and +
    s = re.sub(r"[^\d+]", "", s)
    if s.startswith("00"):
        s = "+" + s[2:]
    if s.startswith("0") and not s.startswith("+"):
        # assume local Uzbek format like 90xxxxxxx -> +99890xxxxxxx
        s = "+998" + s[1:]
    if not s.startswith("+"):
        s = "+" + s
    return s


def phone_html_link(phone: str) -> str:
    p = normalize_phone(phone)
    p_escaped = html.escape(p)
    return f'<a href="tel:{p_escaped}">{p_escaped}</a>'


def generate_otp(length: int = 5) -> str:
    return ''.join(str(random.randint(0, 9)) for _ in range(length))

# ========== BUYURTMA STATUSI UCHUN KBIT ==========
def generate_admin_order_kb(order: dict, show_cancel: bool = True) -> InlineKeyboardMarkup:
    """Admin uchun buyurtma statusini o'zgartirish tugmalarini yaratadi.
    show_cancel: agar False bo'lsa, bekor qilish tugmasi qo'shilmaydi (kanal postlari uchun).
    """
    buttons = []
    order_num = order['order_number']
    status = order['status']

    # Agar buyurtma kanalga yuborilgan bo'lsa, yetkazib beruvchi uni qabul qila olishi uchun tugma qo'shamiz
    if status == 'Kanalda':
        buttons.append(InlineKeyboardButton("📥 Qabul qilish", callback_data=f"accept_{order_num}"))
    elif status == 'Qabul qilingan':
        # agar kuryer allaqachon qabul qilgan bo'lsa, admin uchun yetkazildi tugmasi
        buttons.append(InlineKeyboardButton("✅ Yetkazib berildi", callback_data=f"set_status_{order_num}_Yetkazib berildi"))

    # Har doim bekor qilish tugmasi mavjud (agar yetkazilmagan bo'lsa) — lekin faqat show_cancel True bo'lsa
    if show_cancel and status != 'Yetkazib berildi':
        buttons.append(InlineKeyboardButton(f"❌ Bekor qilish", callback_data=f"cancel_order_{order_num}"))

    return InlineKeyboardMarkup([buttons])

# ========== BUYURTMA TAYMERI VAZIFASI ==========
async def handle_order_expiry(order_number: int, bot):
    """Buyurtma uchun 30 soniyalik taymerni boshqaradi; tugagach buyurtma kanalga yuboriladi."""
    try:
        # 30 soniya kutish
        await asyncio.sleep(30)

        order = find_order(order_number)
        if not order or order["status"] != "Kutilyapti": return

        # Vaqt tugagach buyurtma kanalga yuboriladi va foydalanuvchi bekor qila olmaydi
        order["status"] = "Kanalda"
        persist_orders()

        # yuborish uchun kanal matni (telefonni + bilan ko'rsatish)
        kanal_text = f"🆕 Yangi buyurtma #{order_number}!\n\n{order.get('original_text', '')}\n\n👤 {order.get('user')}\n📞 {normalize_phone(order.get('phone'))}\n📍 https://www.google.com/maps/search/?api=1&query={order.get('loc')}"
        try:
            msg = await bot.send_message(chat_id=BUYURTMALAR_CHANNEL_ID, text=kanal_text, reply_markup=generate_admin_order_kb(order, show_cancel=False))
            order["admin_msgs"] = [{"admin_id": BUYURTMALAR_CHANNEL_ID, "chat_id": msg.chat_id, "message_id": msg.message_id, "text": order.get('original_text','')}]
            persist_orders()
            # Report to super-admin that order was auto-posted to channel
            try:
                sa_text = (
                    f"[E'LON QILINDI] {datetime.now(timezone.utc).isoformat()}\n"
                    f"Kanalga yuborilgan buyurtma: #{order_number}\n"
                    f"Mijoz: {order.get('user')} (id: {order.get('user_id')})\n"
                    f"Telefon: {phone_html_link(order.get('phone'))}\n"
                    f"Jami: {order.get('total')} so'm\n"
                    f"Mahsulotlar: {', '.join(order.get('items', []))}\n"
                    f"Manzil: https://www.google.com/maps/search/?api=1&query={order.get('loc')}"
                )
                await report_superadmin(bot, sa_text)
            except Exception as e:
                log.warning(f"Superadminga publish hisobotini yuborishda xato: {e}")
        except Exception as e:
            log.warning(f"Kanalga buyurtma yuborishda xato (expiry): {e}")

        # Bildirish: foydalanuvchiga buyurtma kanalda e'lon qilindi haqida xabar berish
        um = order.get("user_msg")
        if um:
            try:
                final_txt = f"✅ Buyurtma #{order_number} kanalda e'lon qilindi. Yetkazib beruvchilar qabul qilishini kuting.\n\n{order.get('original_text', '')}"
                await bot.edit_message_text(chat_id=um["chat_id"], message_id=um["message_id"], text=final_txt)
                await bot.send_message(chat_id=um["chat_id"], text="Buyurtmangiz kanalda e'lon qilindi. 30 soniya ichida bekor qilish mumkin emas.")
            except BadRequest: pass
    except asyncio.CancelledError: return
    except Exception as e: log.exception(f"Taymerda xatolik (buyurtma #{order_number}): {e}")
    finally: expiry_tasks.pop(order_number, None)

# ========== HANDLERLAR ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (o'zgarishsiz)
    user = update.effective_user; user_id = user.id; first_name = user.first_name or "Foydalanuvchi"
    if user_id not in users: users.add(user_id); persist_users()
    try: await context.bot.send_message(chat_id=user_id, text=f"Salom, {first_name}! 👋\nSizning Telegram ID raqamingiz: `{user_id}`", parse_mode="Markdown")
    except Exception as e: log.warning(f"ID xabarini yuborishda xato: {e}")
    ud = context.user_data; ud.clear(); ud["cart"] = {}
    # Admin sees admin panel
    if user_id in admins:
        await context.bot.send_message(chat_id=user_id, text="🔑 Admin panelga xush kelibsiz!", reply_markup=admin_panel_kb())
        return
    # Couriers see courier panel instead of regular user menu
    if user_id in couriers:
        await context.bot.send_message(chat_id=user_id, text="🚚 Yetkazib beruvchi paneli:", reply_markup=courier_panel_kb())
        return
    # Regular users see the menu
    await context.bot.send_message(chat_id=user_id, text="🍔 Fast Food botiga xush kelibsiz!", reply_markup=category_menu_kb())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text("Buyruqlar:\n/start — Boshlash\n/help — Yordam")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); data = query.data or ""; uid = update.effective_user.id
    ud = context.user_data; ud.setdefault("cart", {})
    global order_counter

    # ADMIN FUNKSIONALI
    if uid in admins:
        if data == "admin_orders":
            # Faol (admin tomonidan boshqariladigan) buyurtmalar: faqat kanalga e'lon qilinganlar
            published = [o for o in orders if o.get("status") == "Kanalda"]
            if not published:
                await query.edit_message_text("📭 Hozir kanalda e'lon qilingan buyurtmalar yo'q.", reply_markup=admin_panel_kb())
                return

            await query.edit_message_text("📣 Kanalda e'lon qilingan buyurtmalar yuborilmoqda:", reply_markup=admin_panel_kb())
            for o in reversed(published):
                dt_str = datetime.fromisoformat(o.get("dt")).strftime('%Y-%m-%d %H:%M')
                order_text = (
                    f"#{o['order_number']} — **{o['status'].upper()}**\n"
                    f"👤 {o['user']}\n📞 {normalize_phone(o.get('phone'))}\n"
                    f"🛒 {', '.join(o.get('items', []))}\n💰 {o['total']} so‘m\n"
                    f"📍 https://www.google.com/maps/search/?api=1&query={o['loc']}\n"
                    f"🕒 {dt_str}"
                )
                # Adminlar kanaldagi buyurtmani shu yerdan bekor qilishi mumkin
                await context.bot.send_message(chat_id=uid, text=order_text, reply_markup=generate_admin_order_kb(o, show_cancel=True), parse_mode="Markdown")
            return
        
        if data == "admin_clear_all_orders":
            global order_counter
            orders.clear()
            order_counter = 0
            persist_orders()
            await query.edit_message_text("✅ Barcha buyurtmalar tarixi muvaffaqiyatli tozalandi!", reply_markup=admin_panel_kb())
            return
            
        if data.startswith("set_status_"):
            try: _, _, order_num_str, new_status = data.split("_"); order_num = int(order_num_str)
            except (ValueError, IndexError): await query.answer("Noto'g'ri buyruq", show_alert=True); return




            order = find_order(order_num)
            if not order: await query.answer("Buyurtma topilmadi", show_alert=True); return
            
            order['status'] = new_status
            persist_orders()
            
            await query.edit_message_text(query.message.text + f"\n\n✅ Status \"{new_status}\" ga o'zgartirildi.", reply_markup=generate_admin_order_kb(order))
            
            try:
                await context.bot.send_message(chat_id=order['user_id'], text=f"🔔 Sizning #{order_num} buyurtmangizning holati \"{new_status}\" ga o'zgardi.")
            except Exception as e:
                log.warning(f"Foydalanuvchiga status o'zgarishi haqida yuborishda xato: {e}")

            # Report to super-admin channel about status change
            try:
                sa_text = (
                    f"[HOLAT] {datetime.now(timezone.utc).isoformat()}\n"
                    f"Admin: {uid} ({update.effective_user.full_name})\n"
                    f"Buyurtma: #{order_num} — Holat: {new_status}\n"
                    f"Mijoz: {order.get('user')} (id: {order.get('user_id')})\n"
                    f"Telefon: {phone_html_link(order.get('phone'))}\n"
                    f"Jami: {order.get('total')} so'm\n"
                    f"Mahsulotlar: {', '.join(order.get('items', []))}\n"
                    f"Manzil: https://www.google.com/maps/search/?api=1&query={order.get('loc')}"
                )
                await report_superadmin(context.bot, sa_text)
            except Exception as e:
                log.warning(f"Superadminga status hisobotini yuborishda xato: {e}")

            return
            
        # ... (broadcast, add/remove admin o'zgarishsiz)
        if data == "admin_broadcast": ud["want_broadcast"] = True; await query.edit_message_text("📢 Yuboriladigan xabarni yozing:", reply_markup=admin_panel_kb()); return
        if data == "admin_add": ud["want_add_admin"] = True; await query.edit_message_text("➕ Yangi admin ID raqamini kiriting:", reply_markup=admin_panel_kb()); return
        if data == "admin_remove": ud["want_remove_admin"] = True; await query.edit_message_text("❌ O'chiriladigan admin ID raqamini kiriting:", reply_markup=admin_panel_kb()); return
        if data == "admin_add_courier": ud["want_add_courier"] = True; await query.edit_message_text("➕ Yetkazib beruvchi ID raqamini kiriting:", reply_markup=admin_panel_kb()); return
        if data == "admin_remove_courier": ud["want_remove_courier"] = True; await query.edit_message_text("❌ O'chiriladigan yetkazib beruvchi ID raqamini kiriting:", reply_markup=admin_panel_kb()); return
    # Payment callbacks (user finishing checkout)
    if data == 'pay_cash' or data == 'pay_card':
        is_cash = (data == 'pay_cash')
        pending = context.user_data.pop('pending_order', None)
        if not pending:
            await query.answer("Hech qanday buyurtma topilmadi.", show_alert=True); return
        # create order
        order_counter += 1; order_number = order_counter
        order = {
            'order_number': order_number,
            'user_id': update.effective_user.id,
            'user': f"{update.effective_user.full_name} (id: {update.effective_user.id})",
            'items': pending['items'],
            'total': pending['total'],
            'phone': pending['phone'],
            'loc': pending['loc'],
            'dt': pending['dt'],
            'status': 'Kutilyapti',
            'user_msg': None,
            'admin_msgs': [],
            'original_text': pending.get('original_text',''),
            'payment': 'cash' if is_cash else 'card'
        }
        # If cash, generate OTP
        if is_cash:
            otp = generate_otp()
            order['otp'] = otp
        orders.append(order)

        cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"❌ Bekor qilish #{order_number}", callback_data=f"cancel_order_{order_number}")]])
        sent = await query.message.reply_text(f"✅ Buyurtmangiz #{order_number} qabul qilindi!\n\n{order.get('original_text')}\n\n⏳ Bekor qilish uchun 30 soniyangiz bor.", reply_markup=cancel_kb)
        order['user_msg'] = {'chat_id': sent.chat_id, 'message_id': sent.message_id}
        await query.edit_message_text("Buyurtma qabul qilindi. Kanalga e'lon qilish 30s ichida amalga oshiriladi.")

        persist_orders()
        t = asyncio.create_task(handle_order_expiry(order_number, context.bot))
        expiry_tasks[order_number] = t

        # If cash, send OTP to user
        if is_cash:
            try:
                await context.bot.send_message(chat_id=order['user_id'], text=f"Sizning buyurtmangiz uchun tasdiq kodi (OTP): {order['otp']}. Ushbu kodni yetkazib beruvchiga yetkazilganda berishingiz kerak.")
            except Exception as e:
                log.warning(f"OTP yuborishda xato: {e}")
        return

    # --- Yetkazib beruvchi (courier) funksiyalari ---
    # Qabul qilish: faqat couriers ro'yxatidagi foydalanuvchilar qila oladi
    if data.startswith("accept_"):
        try: order_num = int(data.split("_")[-1])
        except (ValueError, IndexError): await query.answer("Noto'g'ri buyruq", show_alert=True); return

        order = find_order(order_num)
        if not order: await query.answer("Buyurtma topilmadi", show_alert=True); return
        if order.get('status') != 'Kanalda': await query.answer("Bu buyurtma qabul qilish uchun mavjud emas.", show_alert=True); return

        if uid not in couriers:
            await query.answer("Siz yetkazib beruvchi emassiz.", show_alert=True); return

        # Belgilash: kuryer buyurtmani qabul qilganda status "Qabul qilingan" ga o'zgaradi
        order['status'] = "Qabul qilingan"
        order['courier_id'] = uid
        order['courier_name'] = update.effective_user.full_name
        persist_orders()

        # Kanaldagi xabarni o'chirish (agar mavjud bo'lsa)
        for am in list(order.get('admin_msgs', [])):
            try:
                if am.get('chat_id') == BUYURTMALAR_CHANNEL_ID:
                    # avvalo o'chirishga harakat qilamiz
                    try:
                        await context.bot.delete_message(chat_id=am['chat_id'], message_id=am['message_id'])
                        # Qabul qilindi deb yangi xabar yuborish
                        await context.bot.send_message(chat_id=BUYURTMALAR_CHANNEL_ID, text=f"✅ Buyurtma #{order_num} qabul qilindi yetkazib beruvchi: {update.effective_user.full_name}")
                    except Exception as e:
                        # Agar o'chira olmasak (bot kanal admin emas yoki ruxsat yo'q), xabarni tahrirlab 'qabul qilindi' deb belgilaymiz
                        log.warning(f"Kanal xabarini o'chirish muvaffaqiyatsiz ({am.get('chat_id')}:{am.get('message_id')}): {e}")
                        try:
                            await context.bot.edit_message_text(chat_id=am['chat_id'], message_id=am['message_id'], text=f"✅ Buyurtma #{order_num} qabul qilindi yetkazib beruvchi: {update.effective_user.full_name}")
                        except Exception as e2:
                            log.warning(f"Kanal xabarini tahrirlashda xato: {e2}")
            except Exception:
                # umumiy himoya: agar admin_msgs ichida noo'rin format bo'lsa davom etamiz
                continue
        # Tozalash va faqat courier uchun yuborish (telefon link bilan)
        courier_text = (
            f"🚚 Siz #{order_num} buyurtmani qabul qildingiz.\n\n"
            f"{html.escape(order.get('original_text',''))}\n\n"
            f"Mijoz: {html.escape(order.get('user'))}\n"
            f"Tel: {phone_html_link(order.get('phone'))}\n"
            f"Manzil: https://www.google.com/maps/search/?api=1&query={html.escape(order.get('loc'))}"
        )
        kb = InlineKeyboardMarkup([[InlineKeyboardButton('✅ Yetkazildi', callback_data=f'delivered_{order_num}'), InlineKeyboardButton('🔄 Qaytarish', callback_data=f'return_{order_num}')]])
        try:
            msg = await context.bot.send_message(chat_id=uid, text=courier_text, reply_markup=kb, parse_mode="HTML")
            order['courier_msg'] = {'chat_id': msg.chat_id, 'message_id': msg.message_id}
        except Exception as e: log.warning(f"Yetkazib beruvchiga buyurtma yuborishda xato: {e}")
        persist_orders()
        # Report accept action to super-admin channel
        try:
            sa_text = (
                f"[QABUL QILINDI] {datetime.now(timezone.utc).isoformat()}\n"
                f"Yetkazib beruvchi: {uid} ({update.effective_user.full_name})\n"
                f"Qabul qilingan buyurtma: #{order_num}\n"
                f"Mijoz: {order.get('user')} (id: {order.get('user_id')})\n"
                f"Telefon: {phone_html_link(order.get('phone'))}\n"
                f"Jami: {order.get('total')} so'm\n"
                f"Mahsulotlar: {', '.join(order.get('items', []))}\n"
                f"Manzil: https://www.google.com/maps/search/?api=1&query={order.get('loc')}"
            )
            await report_superadmin(context.bot, sa_text)
        except Exception as e:
            log.warning(f"Superadminga accept hisobotini yuborishda xato: {e}")

        await query.answer('Buyurtma sizga biriktirildi.')
        return

    if data.startswith('delivered_'):
        try: order_num = int(data.split('_')[-1])
        except (ValueError, IndexError): await query.answer("Noto'g'ri buyruq", show_alert=True); return
        order = find_order(order_num)
        if not order: await query.answer('Buyurtma topilmadi', show_alert=True); return
        if order.get('courier_id') != uid: await query.answer('Bu buyurtma sizga tegishli emas', show_alert=True); return
        # If payment was cash, require OTP confirmation from courier before finalizing
        if order.get('payment') == 'cash':
            context.user_data['expecting_otp_for'] = order_num
            await context.bot.send_message(chat_id=uid, text=f"Iltimos, mijozdan olgan OTP kodini kiriting (Buyurtma #{order_num}).")
            await query.answer('OTP kodini kiriting...')
            return

        # non-cash: finalize immediately
        order['status'] = 'Yetkazib berildi'
        persist_orders()
        # notify user
        try: await context.bot.send_message(chat_id=order['user_id'], text=f"✅ Sizning #{order_num} buyurtmangiz yetkazib berildi.")
        except Exception as e: log.warning(f"Foydalanuvchiga yetkazildi xabarida xato: {e}")
        # edit courier message
        try: await context.bot.edit_message_text(chat_id=order['courier_msg']['chat_id'], message_id=order['courier_msg']['message_id'], text="✅ Yetkazildi")
        except Exception: pass
        # Report delivered action to super-admin
        try:
            sa_text = (
                f"[YETKAZILDI] {datetime.now(timezone.utc).isoformat()}\n"
                f"Yetkazib beruvchi: {uid} ({update.effective_user.full_name})\n"
                f"Yetkazilgan buyurtma: #{order_num}\n"
                f"Mijoz: {order.get('user')} (id: {order.get('user_id')})\n"
                f"Telefon: {phone_html_link(order.get('phone'))}\n"
                f"Jami: {order.get('total')} so'm\n"
                f"Mahsulotlar: {', '.join(order.get('items', []))}"
            )
            await report_superadmin(context.bot, sa_text)
        except Exception as e:
            log.warning(f"Superadminga delivered hisobotini yuborishda xato: {e}")
        await query.answer('Buyurtma yetkazildi sifatida belgilandi.')
        return

    if data.startswith('return_'):
        try: order_num = int(data.split('_')[-1])
        except (ValueError, IndexError): await query.answer("Noto'g'ri buyruq", show_alert=True); return
        order = find_order(order_num)
        if not order: await query.answer('Buyurtma topilmadi', show_alert=True); return
        if order.get('courier_id') != uid: await query.answer('Bu buyurtma sizga tegishli emas', show_alert=True); return
        # qaytarish: kuryer buyurtmani qaytarsa, uning statusi kanalga e'lon qilingan ('Kanalda') ga qaytadi
        # va buyurtma qaytarilganligi belgilanadi — qaytarilganlar soni oshiriladi
        order['status'] = 'Kanalda'
        # increase returned counter and store last return info
        order['returned_count'] = order.get('returned_count', 0) + 1
        order['last_returned_by'] = uid
        order['last_returned_at'] = datetime.now(timezone.utc).isoformat()
        # remove courier assignment
        order.pop('courier_id', None); order.pop('courier_name', None)
        # repost to channel
        # mark returned status visibly in channel post to avoid double-prep
        returned_note = ""
        if order.get('returned_count', 0) > 0:
            returned_note = f"\n⚠️ DIQQAT: Bu buyurtma {order.get('returned_count')} marta qaytarilgan. So'nggi qaytarish: {order.get('last_returned_at')}\nYetkazib beruvchi ID: {order.get('last_returned_by')}"
        kanal_text = (
            f"🆕 Yangi buyurtma #{order_num}!\n\n{order.get('original_text','')}\n\n"
            f"👤 Mijoz: {order.get('user')}\n📞 {normalize_phone(order.get('phone'))}\n"
            f"📍 https://www.google.com/maps/search/?api=1&query={order.get('loc')}"
            f"{returned_note}"
        )
        try:
            msg = await context.bot.send_message(chat_id=BUYURTMALAR_CHANNEL_ID, text=kanal_text, reply_markup=generate_admin_order_kb(order, show_cancel=False))
            order['admin_msgs'] = [{'admin_id': BUYURTMALAR_CHANNEL_ID, 'chat_id': msg.chat_id, 'message_id': msg.message_id, 'text': order.get('original_text','')}]
        except Exception as e: log.warning(f"Kanalga qaytarishda xato: {e}")
        # remove courier message
        try: await context.bot.delete_message(chat_id=order['courier_msg']['chat_id'], message_id=order['courier_msg']['message_id'])
        except Exception: pass
        order.pop('courier_msg', None)
        persist_orders()
        # Report return action to super-admin
        try:
            sa_text = (
                f"[QAYTARILDI] {datetime.now(timezone.utc).isoformat()}\n"
                f"Yetkazib beruvchi: {uid} ({update.effective_user.full_name})\n"
                f"Buyurtma kanalga qaytarildi: #{order_num}\n"
                f"Mijoz: {order.get('user')} (id: {order.get('user_id')})\n"
                f"Telefon: {phone_html_link(order.get('phone'))}\n"
                f"Jami: {order.get('total')} so'm\n"
                f"Mahsulotlar: {', '.join(order.get('items', []))}\n"
                f"Manzil: https://www.google.com/maps/search/?api=1&query={order.get('loc')}"
            )
            await report_superadmin(context.bot, sa_text)
        except Exception as e:
            log.warning(f"Superadminga return hisobotini yuborishda xato: {e}")
        await query.answer('Buyurtma kanalga qaytarildi.')
        return

    # FOYDALANUVCHI FUNKSIONALI (o'zgarishsiz)
    if data.startswith("cat_"): cat = data.split("_", 1)[1]; await query.edit_message_text(f"📋 {cat} menyusi:", reply_markup=product_list_kb(cat))
    elif data == "back_categories": await query.edit_message_text("Kategoriya tanlang:", reply_markup=category_menu_kb())
    elif data.startswith("prod_"):
        _, rest = data.split("_", 1); cat, prod = rest.split("|")
        ud.update({"current_cat": cat, "current_prod": prod, "current_qty": 1})
        info = menu_data[cat][prod]; text = f"🍽 {prod}\n\n💰 Narxi: {info['price']} so‘m\n\n{info['desc']}"
        await query.edit_message_text(text, reply_markup=quantity_kb(cat, prod, 1))
    elif data.startswith("qty_"):
        _, rest = data.split("_", 1); cat, prod, op = rest.split("|")
        qty = ud.get("current_qty", 1); qty = max(1, qty - 1) if op == "dec" else qty + 1
        ud["current_qty"] = qty; await query.edit_message_reply_markup(reply_markup=quantity_kb(cat, prod, qty))
    elif data.startswith("add_"):
        _, rest = data.split("_", 1); prod, qty_str = rest.split("|"); qty = int(qty_str)
        cart = ud["cart"]; cart[prod] = cart.get(prod, 0) + qty
        text, _ = cart_text_and_total(cart); await query.edit_message_text(f"✅ {prod} x{qty} savatga qo‘shildi.\n\n{text}", reply_markup=cart_menu_kb(bool(cart)))
    elif data == "view_cart": text, _ = cart_text_and_total(ud["cart"]); await query.edit_message_text(text, reply_markup=cart_menu_kb(bool(ud["cart"])))
    elif data == "clear_cart": ud["cart"] = {}; await query.edit_message_text("🧹 Savat tozalandi.", reply_markup=cart_menu_kb(False))
    elif data == "checkout":
        if not ud.get("cart"): await query.edit_message_text("🛒 Savat bo‘sh.", reply_markup=category_menu_kb()); return
        ud["checkout_state"] = "ask_phone"
        kb = ReplyKeyboardMarkup([[KeyboardButton("📞 Raqamni ulashish", request_contact=True)]], resize_keyboard=True, one_time_keyboard=True)
        await query.message.reply_text("📞 Iltimos, telefon raqamingizni yuboring:", reply_markup=kb)
        await query.delete_message()

    # --- Kuryer uchun callbacklar (alohida funktsiyalar) ---
    if uid in couriers:
        if data == "courier_my_orders":
            my_orders = [o for o in orders if o.get('courier_id') == uid]
            if not my_orders:
                await query.edit_message_text("🚚 Sizga biriktirilgan buyurtmangiz yo'q.")
                return
            for o in reversed(my_orders):
                dt_str = datetime.fromisoformat(o.get('dt')).strftime('%Y-%m-%d %H:%M')
                text = (
                    f"#{o['order_number']} — {o.get('status')}\n"
                    f"Mijoz: {o.get('user')}\n"
                    f"Tel: {o.get('phone')}\n"
                    f"Mahsulotlar: {', '.join(o.get('items', []))}\n"
                    f"Jami: {o.get('total')} so'm\n"
                    f"Manzil: https://www.google.com/maps/search/?api=1&query={o.get('loc')}\n"
                    f"Vaqt: {dt_str}"
                )
                await context.bot.send_message(chat_id=uid, text=text)
            return
    
    # BUYURTMANI BEKOR QILISH (YANGILANGAN)
    elif data.startswith("cancel_order_"):
        try: order_num = int(data.split("_")[-1])
        except (ValueError, IndexError): await query.answer("Noto'g'ri buyruq", show_alert=True); return

        order_index = -1
        for i, o in enumerate(orders):
            if o.get("order_number") == order_num:
                order_index = i; break
        
        if order_index == -1: await query.answer("Buyurtma topilmadi", show_alert=True); return
        order = orders[order_index]
        # Ruxsat tekshiruvi: faqat buyurtma egasi yoki admin bekor qila oladi
        is_user_canceling = (uid == order["user_id"])
        is_admin_canceling = (uid in admins)
        if not (is_user_canceling or is_admin_canceling):
            await query.answer("❌ Siz bu buyurtmani bekor qila olmaysiz.", show_alert=True)
            return

        # Foydalanuvchi faqat "Kutilyapti" holatidagi buyurtmani bekor qilishi mumkin
        if is_user_canceling and order['status'] != 'Kutilyapti':
            await query.answer("⏳ Faqat 'Kutilyapti' holatidagi buyurtmani bekor qila olasiz!", show_alert=True); return

        # Admin esa allaqachon yetkazilgan buyurtmani bekor qila olmaydi
        if is_admin_canceling and order['status'] == 'Yetkazib berildi':
            await query.answer("Bu buyurtma allaqachon yetkazilgan.", show_alert=True); return

        # Vazifani to'xtatish
        t = expiry_tasks.pop(order_num, None)
        if t: t.cancel()

        # Admin xabarlarini tahrirlash/o'chirish
        for am in order.get("admin_msgs", []):
            try: await context.bot.edit_message_text(f"❌ Buyurtma #{order_num} bekor qilindi.", chat_id=am["chat_id"], message_id=am["message_id"])
            except BadRequest: pass

        # Foydalanuvchi xabarini tahrirlash
        try: await query.edit_message_text(f"❌ Buyurtma #{order_num} bekor qilindi.")
        except BadRequest: pass
        
        # Admin bekor qilsa, foydalanuvchiga xabar berish
        if is_admin_canceling and not is_user_canceling:
            try: await context.bot.send_message(chat_id=order["user_id"], text=f"⚠️ Sizning #{order_num} buyurtmangiz admin tomonidan bekor qilindi.")
            except Exception as e: log.warning(f"Foydalanuvchiga bekor qilish haqida yuborishda xato: {e}")

        # Report cancel action to super-admin
        try:
            canceller = update.effective_user
            sa_text = (
                f"[BEKOR QILINDI] {datetime.now(timezone.utc).isoformat()}\n"
                f"Bekor qilgan: {canceller.id} ({canceller.full_name})\n"
                f"Buyurtma: #{order_num}\n"
                f"Mijoz: {order.get('user')} (id: {order.get('user_id')})\n"
                f"Telefon: {phone_html_link(order.get('phone'))}\n"
                f"Jami: {order.get('total')} so'm\n"
                f"Mahsulotlar: {', '.join(order.get('items', []))}"
            )
            await report_superadmin(context.bot, sa_text)
        except Exception as e:
            log.warning(f"Superadminga cancel hisobotini yuborishda xato: {e}")

        # Buyurtmani ro'yxatdan o'chirish
        del orders[order_index]
        persist_orders()

# ========== XABAR HANDLERLARI ==========
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (o'zgarishsiz)
    uid = update.effective_user.id; text = (update.message.text or "").strip(); ud = context.user_data; ud.setdefault("cart", {})
    # Courier OTP flow: if courier was asked to provide OTP for an order
    if uid in couriers and ud.get('expecting_otp_for'):
        try:
            order_num = int(ud.get('expecting_otp_for'))
            order = find_order(order_num)
            if not order:
                await update.message.reply_text('Buyurtma topilmadi.'); ud.pop('expecting_otp_for', None); return
            # compare OTP
            if text == str(order.get('otp')):
                # finalize
                order['status'] = 'Yetkazib berildi'
                order['collected_amount'] = order.get('total')
                # update courier earnings
                cid = uid
                rec = earnings.get(cid, {'total': 0, 'deliveries': []})
                rec['total'] = rec.get('total', 0) + order.get('total', 0)
                rec.setdefault('deliveries', []).append(order_num)
                earnings[cid] = rec
                persist_earnings()
                persist_orders()
                # notify user
                try: await context.bot.send_message(chat_id=order['user_id'], text=f"✅ Sizning #{order_num} buyurtmangiz yetkazib berildi. (Naqd to'lov qabul qilindi)")
                except Exception as e: log.warning(f"Foydalanuvchiga yetkazildi xabarida xato: {e}")
                # edit courier message
                try: await context.bot.edit_message_text(chat_id=order['courier_msg']['chat_id'], message_id=order['courier_msg']['message_id'], text="✅ Yetkazildi (Naqd to'lov)")
                except Exception: pass
                # report to superadmin
                try:
                    sa_text = (
                        f"[YETKAZILDI-NAQD] {datetime.now(timezone.utc).isoformat()}\n"
                        f"Yetkazib beruvchi: {cid} ({update.effective_user.full_name})\n"
                        f"Buyurtma: #{order_num}\n"
                        f"Mijoz: {order.get('user')} (id: {order.get('user_id')})\n"
                        f"Telefon: {phone_html_link(order.get('phone'))}\n"
                        f"Jami: {order.get('total')} so'm\n"
                        f"Naqd qabul qilindi: {order.get('total')} so'm"
                    )
                    await report_superadmin(context.bot, sa_text)
                except Exception as e:
                    log.warning(f"Superadminga cash delivered hisobotini yuborishda xato: {e}")
                ud.pop('expecting_otp_for', None)
                await update.message.reply_text('✅ OTP tekshirildi, buyurtma yetkazildi.')
                return
            else:
                await update.message.reply_text('❌ Noto‘g‘ri OTP. Iltimos qayta urinib ko‘ring.')
                return
        except Exception as e:
            log.warning(f"OTP flow error: {e}")
            ud.pop('expecting_otp_for', None)
            return
    if uid in admins:
        if ud.get("want_broadcast"):
            ud.pop("want_broadcast", None); sent, failed = 0, 0
            for user_id in list(users):
                try: await context.bot.send_message(chat_id=user_id, text=text); sent += 1
                except Exception as e: failed += 1; log.warning(f"Broadcastda xato ({user_id}): {e}")
            await update.message.reply_text(f"✅ Xabar yuborildi.\nMuvaffaqiyatli: {sent}\nXatolik: {failed}", reply_markup=admin_panel_kb()); return
        if ud.get("want_add_admin"):
            ud.pop("want_add_admin", None)
            try:
                admins.add(int(text)); await update.message.reply_text(f"✅ {text} admin sifatida qo‘shildi.", reply_markup=admin_panel_kb())
                try:
                    sa_text = (
                        f"[ADMIN QO'SHILDI] {datetime.now(timezone.utc).isoformat()}\n"
                        f"Qo'shgan admin: {uid} ({update.effective_user.full_name})\n"
                        f"Yangi admin: {text}"
                    )
                    await report_superadmin(context.bot, sa_text)
                except Exception as e:
                    log.warning(f"Superadminga admin add hisobotini yuborishda xato: {e}")
            except ValueError: await update.message.reply_text("❌ Xato ID.", reply_markup=admin_panel_kb()); return
        if ud.get("want_remove_admin"):
            ud.pop("want_remove_admin", None)
            try:
                rem_id = int(text)
                if rem_id == ADMIN_ID: await update.message.reply_text("⚠️ Asosiy adminni o‘chira olmaysiz.", reply_markup=admin_panel_kb())
                elif rem_id in admins:
                    admins.discard(rem_id); await update.message.reply_text(f"✅ {rem_id} adminlikdan olib tashlandi.", reply_markup=admin_panel_kb())
                    try:
                        sa_text = (
                            f"[ADMIN O'CHIRILDI] {datetime.now(timezone.utc).isoformat()}\n"
                            f"O'chirgan admin: {uid} ({update.effective_user.full_name})\n"
                            f"O'chirilgan admin: {rem_id}"
                        )
                        await report_superadmin(context.bot, sa_text)
                    except Exception as e:
                        log.warning(f"Superadminga admin remove hisobotini yuborishda xato: {e}")
                else: await update.message.reply_text("ℹ️ Bu ID adminlar ro‘yxatida yo‘q.", reply_markup=admin_panel_kb())
            except ValueError: await update.message.reply_text("❌ Xato ID.", reply_markup=admin_panel_kb()); return
        if ud.get("want_add_courier"):
            ud.pop("want_add_courier", None)
            try:
                cid = int(text)
                couriers.add(cid); persist_couriers(); await update.message.reply_text(f"✅ {cid} yetkazib beruvchi sifatida qo‘shildi.", reply_markup=admin_panel_kb())
                # report to super-admin
                try:
                    sa_text = (
                        f"[YETKAZIB BERUVCHI QO'SHILDI] {datetime.now(timezone.utc).isoformat()}\n"
                        f"Qo'shgan admin: {uid} ({update.effective_user.full_name})\n"
                        f"Yangi yetkazib beruvchi: {cid}"
                    )
                    await report_superadmin(context.bot, sa_text)
                except Exception as e:
                    log.warning(f"Superadminga courier add hisobotini yuborishda xato: {e}")
            except ValueError: await update.message.reply_text("❌ Xato ID.", reply_markup=admin_panel_kb()); return
        if ud.get("want_remove_courier"):
            ud.pop("want_remove_courier", None)
            try:
                rcid = int(text)
                if rcid in couriers:
                    couriers.discard(rcid); persist_couriers(); await update.message.reply_text(f"✅ {rcid} yetkazib beruvchi ro'yxatidan olib tashlandi.", reply_markup=admin_panel_kb())
                    try:
                        sa_text = (
                            f"[YETKAZIB BERUVCHI O'CHIRILDI] {datetime.now(timezone.utc).isoformat()}\n"
                            f"O'chirgan admin: {uid} ({update.effective_user.full_name})\n"
                            f"O'chirilgan yetkazib beruvchi: {rcid}"
                        )
                        await report_superadmin(context.bot, sa_text)
                    except Exception as e:
                        log.warning(f"Superadminga courier remove hisobotini yuborishda xato: {e}")
                else:
                    await update.message.reply_text("ℹ️ Bu ID yetkazib beruvchilar ro‘yxatida yo‘q.", reply_markup=admin_panel_kb())
            except ValueError: await update.message.reply_text("❌ Xato ID.", reply_markup=admin_panel_kb()); return
    if ud.get("checkout_state") == "ask_phone" and text:
        ud["phone"] = text; ud["checkout_state"] = "ask_location"
        kb = ReplyKeyboardMarkup([[KeyboardButton("📍 Lokatsiyani ulashish", request_location=True)]], resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text("📍 Iltimos, manzilingizni yuboring:", reply_markup=kb); return
    await start(update, context)




async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = context.user_data
    if ud.get("checkout_state") == "ask_phone" and update.message.contact:
        ud["phone"] = update.message.contact.phone_number; ud["checkout_state"] = "ask_location"
        kb = ReplyKeyboardMarkup([[KeyboardButton("📍 Lokatsiyani ulashish", request_location=True)]], resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text("📍 Endi manzilingizni yuboring:", reply_markup=kb)

async def location_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global order_counter
    ud = context.user_data
    if ud.get("checkout_state") == "ask_location" and update.message.location:
        loc: Location = update.message.location; ud["checkout_state"] = None
        cart = ud.get("cart", {}); cart_summary, total = cart_text_and_total(cart)
        # Saqlab qo'yamiz va foydalanuvchidan to'lov turini so'raymiz (Naqd yoki Kart)
        ud['pending_order'] = {
            'items': [f"{k} x{v}" for k, v in cart.items()],
            'total': total,
            'phone': ud.get('phone', "Noma'lum"),
            'loc': f"{loc.latitude:.5f},{loc.longitude:.5f}",
            'dt': datetime.now(timezone.utc).isoformat(),
            'original_text': cart_summary
        }
        ud["cart"] = {}
        # payment choice keyboard
        pay_kb = InlineKeyboardMarkup([[InlineKeyboardButton("💵 Naqd (cash)", callback_data="pay_cash") , InlineKeyboardButton("💳 Kartasi", callback_data="pay_card")]])
        await update.message.reply_text("To'lov turini tanlang:", reply_markup=pay_kb)
        return

# ========== ASOSIY FUNKSIYA ==========
def main():
    async def startup_reschedule(app):
        global order_counter
        if orders: order_counter = max((o.get("order_number", 0) for o in orders), default=0)
        for o in list(orders):
            if o.get("status") == "Kutilyapti":
                created = datetime.fromisoformat(o["dt"])
                if (datetime.now(timezone.utc) - created).total_seconds() < 60: 
                    task = asyncio.create_task(handle_order_expiry(o["order_number"], app.bot))
                    expiry_tasks[o["order_number"]] = task



    app = ApplicationBuilder().token(BOT_TOKEN).post_init(startup_reschedule).build()
    app.add_handler(CommandHandler("start", start)); app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.CONTACT, contact_handler)); app.add_handler(MessageHandler(filters.LOCATION, location_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    log.info("Bot ishga tushdi."); app.run_polling()

if __name__ == "__main__":
    main()