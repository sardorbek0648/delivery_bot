
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
import time
from typing import Optional

from telegram import (
    Update,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton,
    Location
)
from telegram import InputMediaPhoto, LabeledPrice
from telegram import InputMediaPhoto
from telegram.error import BadRequest
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    PreCheckoutQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ========== SOZLAMALAR ==========
# Bot tokenni muhitdan o'qing (Heroku/GitHub Secrets uchun). Repo ichida saqlamang.
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = 5788278697               # <<< asosiy admin id
admins = {ADMIN_ID}

USERS_FILE = "users.json"
ORDERS_FILE = "orders.json"
COURIERS_FILE = "couriers.json"
EARNINGS_FILE = "earnings.json"
MENU_FILE = "menu.json"
USERS_INFO_FILE = "users_info.json"

# Buyurtmalar kanalining chat ID (o'zgartirdingiz):
BUYURTMALAR_CHANNEL_ID = -1003357292759
# Super-admin kanal yoki chat ID — default asosiy adminga yuboradi, kerak bo'lsa kanal ID qo'ying
SUPERADMIN_CHANNEL_ID = -1003401946836  # Super admin hisobot kanali ID
SUGGESTIONS_CHANNEL_ID = -1003394437912  # Taklif va shikoyatlar kanali
PAYMENT_PROVIDER_TOKEN = os.getenv('PAYMENT_PROVIDER_TOKEN', '')
PAYMENTS_CHANNEL_ID = -1003105969871  # Manat o'tovlar kanali

# ========== LOGGING ==========
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("dostavka_bot")

# Track all bot-sent messages per private chat so we can purge on /start
bot_messages_by_chat: dict[int, list[dict]] = {}

def _record_bot_message(chat_id: int, message_id: int):
    try:
        if chat_id is None or message_id is None:
            return
        lst = bot_messages_by_chat.setdefault(int(chat_id), [])
        lst.append({'chat_id': int(chat_id), 'message_id': int(message_id)})
        if len(lst) > 300:
            del lst[: len(lst) - 300]
    except Exception:
        pass

async def _delete_all_bot_messages_for_chat(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    try:
        arr = bot_messages_by_chat.pop(int(chat_id), [])
        for m in arr:
            try:
                await context.bot.delete_message(chat_id=m.get('chat_id'), message_id=m.get('message_id'))
            except Exception:
                try:
                    await context.bot.edit_message_text(chat_id=m.get('chat_id'), message_id=m.get('message_id'), text='\u200b')
                except Exception:
                    pass
    except Exception:
        pass

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
# Track last category message shown to each chat so we can update listings when availability changes
last_category_messages: dict[tuple[int, str], int] = {}
# Track admin "active orders" sessions: map admin_id -> list of sent message dicts
admin_orders_sessions: dict[int, list[dict]] = {}

# Per-user info (name, phone, other profile data)
_users_info = load_json(USERS_INFO_FILE, {})
users_info = {int(k): v for k, v in _users_info.items()} if isinstance(_users_info, dict) else {}

def persist_users_info():
    try:
        save_json(USERS_INFO_FILE, {str(k): v for k, v in users_info.items()})
    except Exception:
        pass
 

async def clear_admin_session(uid: int, context: ContextTypes.DEFAULT_TYPE, ud: Optional[dict] = None):
    """Centralized helper to remove stored admin prompts, session messages and transient state.
    Best-effort: deletes stored bot messages referenced in `admin_orders_sessions` and
    `amenu_last_prompt`, and clears common `context.user_data` admin keys.
    """
    try:
        if ud is None:
            ud = context.user_data
        # delete single last prompt if present
        try:
            lp = ud.pop('amenu_last_prompt', None)
            if lp:
                try:
                    await context.bot.delete_message(chat_id=lp.get('chat_id'), message_id=lp.get('message_id'))
                except Exception:
                    pass
        except Exception:
            pass

        # delete any admin-session messages we previously stored, but only those
        # that were sent into the admin's private chat (avoid touching channel posts)
        try:
                sent_prompts = admin_orders_sessions.pop(uid, [])
                try:
                    await _safe_delete_session_messages(context, uid, sent_prompts)
                except Exception:
                    pass
        except Exception:
            pass

        # clear common transient admin/user_data keys
        for k in ('amenu_add_product_step','amenu_add_product_cat','amenu_new_name','amenu_new_price','amenu_new_desc','amenu_new_photo','amenu_edit_price','amenu_edit_desc','amenu_edit_photo','amenu_adding_category','want_broadcast','want_add_admin','want_remove_admin','want_add_courier','want_remove_courier','last_prompt_msg'):
            try:
                ud.pop(k, None)
            except Exception:
                pass
    except Exception:
        # swallow any error to avoid breaking admin flows
        pass


async def clear_user_session(uid: int, context: ContextTypes.DEFAULT_TYPE, ud: Optional[dict] = None):
    """Delete best-effort any transient messages we stored for a regular user session.
    This includes keys: history_messages, menu_messages, welcome_msg, suggest_prompt, last_prompt_msg.
    Fall back to editing text if deletion isn't allowed.
    """
    prompt_mid = None
    try:
        if ud is None:
            ud = context.user_data
        # delete history messages
        try:
            hist = ud.pop('history_messages', [])
            for idx, m in enumerate(hist):
                cid = m.get('chat_id'); mid = m.get('message_id')
                try:
                    await context.bot.delete_message(chat_id=cid, message_id=mid)
                    if idx == 0:
                        prompt_mid = mid
                except Exception as e:
                    log.warning(f"Failed to delete user history message {mid} in chat {cid}: {e}")
                    try:
                        await context.bot.edit_message_text(chat_id=cid, message_id=mid, text='‎')
                        if idx == 0:
                            prompt_mid = mid
                    except Exception as e2:
                        log.warning(f"Failed to edit-to-blank user history message {mid} in chat {cid}: {e2}")
        except Exception:
            pass

        # delete menu messages
        try:
            menu_msgs = ud.pop('menu_messages', [])
            for m in menu_msgs:
                cid = m.get('chat_id'); mid = m.get('message_id')
                try:
                    await context.bot.delete_message(chat_id=cid, message_id=mid)
                except Exception as e:
                    log.warning(f"Failed to delete user menu message {mid} in chat {cid}: {e}")
                    try:
                        await context.bot.edit_message_text(chat_id=cid, message_id=mid, text='‎')
                    except Exception as e2:
                        log.warning(f"Failed to edit-to-blank user menu message {mid} in chat {cid}: {e2}")
        except Exception:
            pass

        # delete suggest prompt
        try:
            sp = ud.pop('suggest_prompt', None)
            if sp:
                cid = sp.get('chat_id'); mid = sp.get('message_id')
                try:
                    await context.bot.delete_message(chat_id=cid, message_id=mid)
                except Exception as e:
                    log.warning(f"Failed to delete suggest_prompt {mid} in chat {cid}: {e}")
                    try:
                        await context.bot.edit_message_text(chat_id=cid, message_id=mid, text='‎')
                    except Exception as e2:
                        log.warning(f"Failed to edit-to-blank suggest_prompt {mid} in chat {cid}: {e2}")
        except Exception:
            pass

        # delete last_prompt_msg
        try:
            lp = ud.pop('last_prompt_msg', None)
            if lp:
                cid = lp.get('chat_id'); mid = lp.get('message_id')
                try:
                    await context.bot.delete_message(chat_id=cid, message_id=mid)
                except Exception as e:
                    log.warning(f"Failed to delete last_prompt_msg {mid} in chat {cid}: {e}")
                    try:
                        await context.bot.edit_message_text(chat_id=cid, message_id=mid, text='‎')
                    except Exception as e2:
                        log.warning(f"Failed to edit-to-blank last_prompt_msg {mid} in chat {cid}: {e2}")
        except Exception:
            pass

        # delete stored welcome message
        try:
            wm = ud.pop('welcome_msg', None)
            if wm:
                cid = wm.get('chat_id'); mid = wm.get('message_id')
                try:
                    await context.bot.delete_message(chat_id=cid, message_id=mid)
                except Exception as e:
                    log.warning(f"Failed to delete welcome_msg {mid} in chat {cid}: {e}")
                    try:
                        await context.bot.edit_message_text(chat_id=cid, message_id=mid, text='‎')
                    except Exception as e2:
                        log.warning(f"Failed to edit-to-blank welcome_msg {mid} in chat {cid}: {e2}")
        except Exception:
            pass
    except Exception:
        pass
    return prompt_mid

# ========== MENYU & KLAVIATURALAR ==========
menu_data = {
    "Ichimliklar": { "Coca Cola 0.5l": {"price": 8000, "desc": "Salqin ichimlik"},"Coca Cola 1l": {"price": 11000, "desc": "Salqin ichimlik"},"Coca Cola 1.5l": {"price": 14000, "desc": "Salqin ichimlik"}, "Fanta": {"price": 7000, "desc": "Mevali lazzat"}},
    "Fast Food": {"Burger": {"price": 25000, "desc": "Go‘shtli burger"}, "Hot Dog": {"price": 18000, "desc": "Sosiska non ichida"}},
    "Taomlar": {"Palov": {"price": 35000, "desc": "An'anaviy o‘zbek taomi"}, "Manti": {"price": 30000, "desc": "Bug‘da pishirilgan manti"}},
}

# Load persisted menu if exists
_loaded_menu = load_json(MENU_FILE, None)
if isinstance(_loaded_menu, dict):
    menu_data = _loaded_menu

def persist_menu():
    try:
        save_json(MENU_FILE, menu_data)
    except Exception as e:
        log.warning(f"Menyuni saqlashda xato: {e}")


def _track_menu_message(ud: dict, msg):
    """Helper: record a sent message into user's `menu_messages` list
    so it can be cleaned up when the user exits the menu."""
    try:
        if ud is None:
            return
        menu_msgs = ud.setdefault('menu_messages', [])
        menu_msgs.append({'chat_id': msg.chat_id, 'message_id': msg.message_id})
    except Exception:
        pass


def refresh_category_views(context, cat: str):
    """Update any cached category messages so users see menu changes immediately."""
    try:
        for (chat_id, c), msg_id in list(last_category_messages.items()):
            if c == cat:
                try:
                    context.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=f"📋 {cat} menyusi:", reply_markup=product_list_kb(cat))
                except Exception:
                    try:
                        last_category_messages.pop((chat_id, c), None)
                    except Exception:
                        pass
    except Exception:
        pass

def admin_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 Faol buyurtmalar", callback_data="admin_orders")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🧾 Menyuni tahrirlash", callback_data="admin_edit_menu")],
        [InlineKeyboardButton("⚠️ Mahsulot tugadi", callback_data="admin_mark_product")],
        [InlineKeyboardButton("➕ Yangi admin", callback_data="admin_add")],
        [InlineKeyboardButton("❌ Adminni olib tashlash", callback_data="admin_remove")],
        [InlineKeyboardButton("➕ Yetkazib beruvchi", callback_data="admin_add_courier")],
        [InlineKeyboardButton("❌ Yetkazib beruvchi", callback_data="admin_remove_courier")],
    ])

def category_menu_kb() -> InlineKeyboardMarkup:
    # build category buttons dynamically from current `menu_data` so admin-added categories are visible to users
    rows = []
    try:
        for cat in menu_data.keys():
            rows.append([InlineKeyboardButton(cat, callback_data=f"cat_{cat}")])
    except Exception:
        # fallback to default static categories if something goes wrong
        rows = [[InlineKeyboardButton("🥤 Ichimliklar", callback_data="cat_Ichimliklar")], [InlineKeyboardButton("🍔 Fast Food", callback_data="cat_Fast Food")], [InlineKeyboardButton("🍛 Taomlar", callback_data="cat_Taomlar")]]
    # always include cart button
    rows.append([InlineKeyboardButton("🛒 Savat", callback_data="view_cart")])
    return InlineKeyboardMarkup(rows)


def courier_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚚 Mening buyurtmalar", callback_data="courier_my_orders")],
    ])




# ... boshqa klaviatura funksiyalari o'zgarishsiz ...
def product_list_kb(category: str):
    # For regular users, only show products that are marked available (default True)
    rows = []
    for name, info in menu_data.get(category, {}).items():
        if not info.get('available', True):
            # hidden from users
            continue
        rows.append([InlineKeyboardButton(f"{name} — {info['price']} so‘m", callback_data=f"prod_{category}|{name}")])
    rows.append([InlineKeyboardButton("◀️ Ortga", callback_data="back_categories"), InlineKeyboardButton("🛒 Savat", callback_data="view_cart")])
    return InlineKeyboardMarkup(rows)
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


async def _safe_delete_session_messages(context: ContextTypes.DEFAULT_TYPE, uid: int, sent: list[dict]):
    """Helper: delete only messages that were sent into the admin/user private chat `uid`.
    Avoids attempting to delete channel posts or cross-chat message ids which produce many 400 errors.
    Best-effort: try delete, then fallback to edit-to-blank, and log failures.
    """
    try:
        if not sent:
            return
        sent_local = [m for m in sent if m and m.get('chat_id') == uid and m.get('message_id')]
        for m in sent_local:
            cid = m.get('chat_id'); mid = m.get('message_id')
            try:
                await context.bot.delete_message(chat_id=cid, message_id=mid)
            except Exception as e:
                log.warning(f"Failed to delete session message {mid} in chat {cid}: {e}")
                try:
                    await context.bot.edit_message_text(chat_id=cid, message_id=mid, text='‎')
                except Exception as e2:
                    log.warning(f"Failed to edit-to-blank session message {mid} in chat {cid}: {e2}")
    except Exception:
        pass


async def report_superadmin(bot, text: str):
    """Yagona helper: super-admin kanaliga xabar yuboradi (xatolikni loglaydi)."""
    try:
        await bot.send_message(chat_id=SUPERADMIN_CHANNEL_ID, text=text, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        log.warning(f"Superadminga yuborishda xato: {e}")


async def precheckout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Answer Telegram pre-checkout queries. We accept valid payloads.
    This is a lightweight check — we accept and let successful_payment handler finalize.
    """
    try:
        pcq = update.pre_checkout_query
        # For now we accept all pre-checkout queries. If you want to validate payloads,
        # compare pcq.invoice_payload with stored pending invoices.
        await pcq.answer(ok=True)
    except Exception as e:
        log.warning(f"PreCheckoutQuery handling failed: {e}")


async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle successful payments delivered by Telegram (Message.successful_payment).
    Create the real order from stored `pending_invoice` in `context.user_data`.
    """
    try:
        msg = update.message
        successful = msg.successful_payment
        if not successful:
            return
        invoice_payload = getattr(successful, 'invoice_payload', None) or getattr(successful, 'payload', None)
        pending = context.user_data.pop('pending_invoice', None)
        if pending and pending.get('payload') == invoice_payload:
            pending_order = pending.get('pending_order')
            # create order record (paid)
            global order_counter
            order_counter += 1
            order_number = order_counter
            order = {
                'order_number': order_number,
                'user_id': msg.chat_id,
                'user_name': msg.chat.full_name if msg.chat else '',
                'user_username': msg.chat.username if msg.chat else '',
                'user': f"{msg.chat.full_name} (id: {msg.chat_id})",
                'items': pending_order.get('items', []),
                'total': pending_order.get('total', 0),
                'phone': pending_order.get('phone', ''),
                'loc': pending_order.get('loc', ''),
                'dt': pending_order.get('dt') or datetime.now(timezone.utc).isoformat(),
                'status': 'Kutilyapti',
                'user_msg': None,
                'admin_msgs': [],
                'original_text': pending_order.get('original_text',''),
                'payment': 'card',
                'paid': True,
                'payment_info': {
                    'provider_payment_charge_id': getattr(successful, 'provider_payment_charge_id', None),
                    'telegram_payment_charge_id': getattr(successful, 'telegram_payment_charge_id', None),
                    'currency': successful.currency,
                    'total_amount': successful.total_amount,
                }
            }
            orders.append(order)
            persist_orders()
            # generate OTP for card-paid orders so courier can verify on delivery
            try:
                otp = generate_otp()
                order['otp'] = otp
                persist_orders()
                exit_kb = ReplyKeyboardMarkup([[KeyboardButton('🔙 Chiqish')]], resize_keyboard=True, one_time_keyboard=True)
                await context.bot.send_message(chat_id=msg.chat_id, text=f"Sizning buyurtmangiz uchun tasdiq kodi (OTP): {otp}. Ushbu kodni yetkazib beruvchiga yetkazilganda berishingiz kerak.", reply_markup=exit_kb)
            except Exception:
                pass
            # schedule expiry as usual
            t = asyncio.create_task(handle_order_expiry(order_number, context.bot))
            expiry_tasks[order_number] = t
            # notify user
            try:
                await context.bot.send_message(chat_id=msg.chat_id, text=f"✅ To'lov muvaffaqiyatli. Buyurtmangiz #{order_number} qabul qilindi.\n\n{order.get('original_text','')}")
            except Exception:
                pass
            # optionally notify super-admin
            try:
                sa_text = (
                    f"[TO'LOV] {datetime.now(timezone.utc).isoformat()}\n"
                    f"Mijoz: {order.get('user')} (id: {order.get('user_id')})\n"
                    f"Buyurtma: #{order_number}\n"
                    f"Jami: {order.get('total')} {order['payment_info'].get('currency')}\n"
                )
                await report_superadmin(context.bot, sa_text)
            except Exception:
                pass
        else:
            # No matching pending invoice; log and accept
            log.info(f"Successful payment received but no pending invoice matched: payload={invoice_payload}")
    except Exception as e:
        log.exception(f"Error handling successful payment: {e}")


async def api_call_with_retry(callable_func, *args, retries: int = 3, initial_delay: float = 1.0, **kwargs):
    """Call a coroutine function with simple exponential backoff retries.
    callable_func should be an async callable (e.g., bot.send_message).
    """
    delay = initial_delay
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            return await callable_func(*args, **kwargs)
        except Exception as e:
            last_exc = e
            log.warning(f"API call failed (attempt {attempt}/{retries}): {e}")
            if attempt == retries:
                raise
            await asyncio.sleep(delay)
            delay *= 2
    if last_exc:
        raise last_exc


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


def product_price(name: str) -> int:
    for cat in menu_data.values():
        if name in cat:
            return cat[name]['price']
    return 0


def build_superadmin_order_text(order: dict) -> str:
    parts = []
    parts.append(f"📝 Buyurtma #{order['order_number']} — {order.get('status')}")
    parts.append(f"👤 {html.escape(order.get('user',''))}")
    parts.append(f"📞 {phone_html_link(order.get('phone'))}")
    parts.append("")
    items = order.get('items', [])
    for i, it in enumerate(items):
        parts.append(f"{i+1}. {html.escape(it)}")
    parts.append("")
    parts.append(f"💰 Jami: {order.get('total',0)} so'm")
    parts.append(f"📍 Manzil: https://www.google.com/maps/search/?api=1&query={html.escape(order.get('loc',''))}")
    return "\n".join(parts)


def build_superadmin_kb(order: dict) -> InlineKeyboardMarkup:
    rows = []
    items = order.get('items', [])
    for idx, it in enumerate(items):
        rows.append([
            InlineKeyboardButton("➖", callback_data=f"sa_dec_{order['order_number']}_{idx}"),
            InlineKeyboardButton(f"{it}", callback_data="noop"),
            InlineKeyboardButton("➕", callback_data=f"sa_inc_{order['order_number']}_{idx}")
        ])
    rows.append([
        InlineKeyboardButton("➕ Mahsulot qo'shish", callback_data=f"sa_add_{order['order_number']}"),
        InlineKeyboardButton("✅ Kanalga yangilash", callback_data=f"sa_done_{order['order_number']}"),
        InlineKeyboardButton("❌ Bekor", callback_data=f"sa_canceledit_{order['order_number']}")
    ])
    return InlineKeyboardMarkup(rows)


def build_admin_edit_kb(order: dict) -> InlineKeyboardMarkup:
    """Build inline keyboard for admin item-level editing (proposed_items must exist in order)."""
    rows = []
    items = order.get('proposed_items', order.get('items', []))
    for idx, it in enumerate(items):
        rows.append([
            InlineKeyboardButton("➖", callback_data=f"ae_dec_{order['order_number']}_{idx}"),
            InlineKeyboardButton(f"{it}", callback_data="noop"),
            InlineKeyboardButton("➕", callback_data=f"ae_inc_{order['order_number']}_{idx}")
        ])
    rows.append([
        InlineKeyboardButton("➕ Mahsulot qo'shish", callback_data=f"ae_add_{order['order_number']}"),
        InlineKeyboardButton("✅ Saqlash va mijozga tasdiqlash", callback_data=f"ae_done_{order['order_number']}"),
        InlineKeyboardButton("❌ Bekor", callback_data=f"ae_cancel_{order['order_number']}")
    ])
    return InlineKeyboardMarkup(rows)


async def send_superadmin_order_report(bot, order: dict):
    try:
        text = build_superadmin_order_text(order)
        kb = build_superadmin_kb(order)
        msg = await bot.send_message(chat_id=SUPERADMIN_CHANNEL_ID, text=text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)
        order['superadmin_msg'] = {'chat_id': msg.chat_id, 'message_id': msg.message_id}
        persist_orders()
    except Exception as e:
        log.warning(f"Superadminga buyurtma hisobotini yuborishda xato: {e}")

# ========== BUYURTMA STATUSI UCHUN KBIT ==========
def generate_admin_order_kb(order: dict, show_cancel: bool = True, show_edit: bool = True, include_accept: bool = True) -> InlineKeyboardMarkup:
    """Admin uchun buyurtma statusini o'zgartirish tugmalarini yaratadi.
    show_cancel: agar False bo'lsa, bekor qilish tugmasi qo'shilmaydi (kanal postlari uchun).
    """
    buttons = []
    order_num = order['order_number']
    status = order['status']

    # Agar buyurtma kanalga yuborilgan bo'lsa, yetkazib beruvchi uni qabul qila olishi uchun tugma qo'shamiz
    # 'accept' button should only be included when the keyboard is shown in the channel
    # (so couriers can accept). When showing the keyboard to admins, set include_accept=False.
    if status == 'Kanalda' and include_accept:
        buttons.append(InlineKeyboardButton("📥 Qabul qilish", callback_data=f"accept_{order_num}"))
    elif status == 'Qabul qilingan':
        # agar kuryer allaqachon qabul qilgan bo'lsa, admin uchun yetkazildi tugmasi
        buttons.append(InlineKeyboardButton("✅ Yetkazib berildi", callback_data=f"set_status_{order_num}_Yetkazib berildi"))

    # Har doim bekor qilish tugmasi mavjud (agar yetkazilmagan bo'lsa) — lekin faqat show_cancel True bo'lsa
    if show_cancel and status != 'Yetkazib berildi':
        buttons.append(InlineKeyboardButton(f"❌ Bekor qilish", callback_data=f"cancel_order_{order_num}"))
    # Note: edit button intentionally omitted — admin item-level editing via separate menu
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
        kanal_text = (
            f"🆕 Yangi buyurtma #{order_number}!\n\n{order.get('original_text', '')}\n\n"
            f"👤 {order.get('user')}\n📞 {normalize_phone(order.get('phone'))}\n"
            f"📍 https://www.google.com/maps/search/?api=1&query={order.get('loc')}"
        )
        try:
            msg = await api_call_with_retry(
                bot.send_message,
                chat_id=BUYURTMALAR_CHANNEL_ID,
                text=kanal_text,
                reply_markup=generate_admin_order_kb(order, show_cancel=False),
            )
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
                # structured superadmin report (allows inline editing)
                try:
                    await send_superadmin_order_report(bot, order)
                except Exception:
                    pass
        except Exception as e:
            log.warning(f"Kanalga buyurtma yuborishda xato (expiry): {e}")

        # Bildirish: foydalanuvchiga buyurtma kanalda e'lon qilindi haqida xabar berish
        um = order.get("user_msg")
        if um:
            final_txt = (
                f"✅ Buyurtma #{order_number} kanalda e'lon qilindi. Yetkazib beruvchilar qabul qilishini kuting.\n\n"
                f"{order.get('original_text', '')}"
            )
            # Try to edit the previous user message and send a follow-up; retry on transient errors.
            try:
                try:
                    await api_call_with_retry(
                        bot.edit_message_text,
                        chat_id=um["chat_id"],
                        message_id=um["message_id"],
                        text=final_txt,
                    )
                except Exception as e:
                    log.warning(f"Foydalanuvchi xabarini tahrirlash muvaffaqiyatsiz (order #{order_number}): {e}")
                        # Vaqt tugagach buyurtma kanalga yuboriladi va foydalanuvchi bekor qila olmaydi
                    await api_call_with_retry(
                        bot.send_message,
                        chat_id=um["chat_id"],
                        text="30 soniya o'tdi — buyurtmani endi bekor qila olmaysiz.",
                    )
                except Exception as e:
                    log.warning(f"Foydalanuvchiga xabar yuborishda xato (order #{order_number}): {e}")
            except BadRequest:
                pass
    except asyncio.CancelledError: return
    except Exception as e: log.exception(f"Taymerda xatolik (buyurtma #{order_number}): {e}")
    finally: expiry_tasks.pop(order_number, None)

# ========== HANDLERLAR ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Start handler: ensure admins see only the admin panel (no extra greetings/messages)
    user = update.effective_user; user_id = user.id; first_name = user.first_name or "Foydalanuvchi"
    if user_id not in users:
        users.add(user_id); persist_users()
    ud = context.user_data
    # Determine role early for correct cleanup ordering
    is_admin = user_id in admins
    # Best-effort: delete any prior bot messages/prompts for a clean start
    try:
        # For admins, clear admin prompts first (before wiping user_data)
        if is_admin:
            try:
                await clear_admin_session(user_id, context, ud)
            except Exception:
                pass
        # Clear user session messages (menus, history, prompts)
        try:
            await clear_user_session(user_id, context, ud)
        except Exception:
            pass
        # Delete ANY bot-sent messages recorded for this chat (photos, texts, keyboards, etc.)
        try:
            await _delete_all_bot_messages_for_chat(context, user_id)
        except Exception:
            pass
        # Also delete any cached category-view messages for this chat
        try:
            for (chat_id, cat), mid in list(last_category_messages.items()):
                if chat_id == user_id:
                    try:
                        await context.bot.delete_message(chat_id=chat_id, message_id=mid)
                    except Exception:
                        # fallback: try to blank it if deletion fails
                        try:
                            await context.bot.edit_message_text(chat_id=chat_id, message_id=mid, text='\u200b')
                        except Exception:
                            pass
                    finally:
                        try:
                            last_category_messages.pop((chat_id, cat), None)
                        except Exception:
                            pass
        except Exception:
            pass
        # Optionally delete the user's /start command message to keep chat clean
        try:
            if update.message:
                await update.message.delete()
        except Exception:
            pass
    except Exception:
        pass
    # Now reset per-user state
    ud.clear(); ud["cart"] = {}

    # Admins: send only the admin panel and nothing else
    if is_admin:
        # Admin panel after cleanup
        try:
            await context.bot.send_message(chat_id=user_id, text="🔑 Admin panelga xush kelibsiz!", reply_markup=admin_panel_kb())
        except Exception as e:
            log.warning(f"Admin panelni yuborishda xato: {e}")
        return

    # For non-admins, show user greeting/menu as before
    try:
        await context.bot.send_message(chat_id=user_id, text=f"Salom, {first_name}! 👋\nSizning Telegram ID raqamingiz: `{user_id}`", parse_mode="Markdown")
    except Exception as e:
        log.warning(f"ID xabarini yuborishda xato: {e}")

    # Couriers see courier panel instead of regular user menu
    if user_id in couriers:
        await context.bot.send_message(chat_id=user_id, text="🚚 Yetkazib beruvchi paneli:", reply_markup=courier_panel_kb())
        return

    # Regular users: show a simple reply-keyboard with top-level actions (not categories)
    try:
        # If we don't have stored profile info for this user, start a short questionnaire
        if user_id not in users_info:
            # ask for full name first
            ud = context.user_data
            ud['profile_setup'] = 'name'
            try:
                await context.bot.send_message(chat_id=user_id, text="Assalomu alaykum! Iltimos, to'liq ismingizni kiriting:")
            except Exception:
                pass
            return

        user_kb = ReplyKeyboardMarkup([
            [KeyboardButton("🍔 Menyu"), KeyboardButton("Taklif va shikoyatlar")],
            [KeyboardButton("🧾 Buyurtmalar tarixi")]
        ], resize_keyboard=True, one_time_keyboard=False)
        try:
            sent_w = await context.bot.send_message(chat_id=user_id, text="🍔 Fast Food botiga xush kelibsiz! Quyidagi tugmalardan foydalaning:", reply_markup=user_kb)
            # store welcome message id so we can delete/restore it when entering/exiting menu
            try:
                ud['welcome_msg'] = {'chat_id': sent_w.chat_id, 'message_id': sent_w.message_id, 'text': "🍔 Fast Food botiga xush kelibsiz! Quyidagi tugmalardan foydalaning:"}
            except Exception:
                pass
        except Exception as e:
            log.warning(f"Foydalanuvchi uchun boshlang'ich klaviatura yuborishda xato: {e}")
    except Exception as e:
        log.warning(f"Foydalanuvchi uchun boshlang'ich klaviatura yuborishda xato: {e}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text("Buyruqlar:\n/start — Boshlash\n/help — Yordam")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); data = query.data or ""; uid = update.effective_user.id
    ud = context.user_data; ud.setdefault("cart", {})
    global order_counter

    # ADMIN FUNKSIONALI
    if uid in admins:
        if data == 'admin_panel':
            # Cleanup any transient admin prompts and states when returning to the panel
            try:
                await clear_admin_session(uid, context, ud)
            except Exception:
                pass
            try:
                await query.edit_message_text("🔑 Admin panelga xush kelibsiz!", reply_markup=admin_panel_kb())
            except Exception:
                pass
            return
        # Admin reply-to-suggestion button pressed: set up reply state
        if data.startswith('reply_sug_'):
            # format: reply_sug_<user_id>_<channel_msg_id>
            parts = data.split('_')
            try:
                target_user = int(parts[2])
                channel_msg_id = int(parts[3]) if len(parts) > 3 else None
            except Exception:
                await query.answer('Noto‘g‘ri parametrlar', show_alert=True); return
            # set admin's user_data so their next message will be forwarded to target_user
            ud['want_reply_to'] = {'target_user': target_user, 'channel_msg_id': channel_msg_id}
            # prompt admin to type the reply
            try:
                exit_kb = ReplyKeyboardMarkup([[KeyboardButton('🔙 Chiqish')]], resize_keyboard=True, one_time_keyboard=True)
                prompt = await context.bot.send_message(chat_id=uid, text=f"Mijoz (id: {target_user}) ga yuboriladigan javob matnini yoki media-xabarni yuboring.\n(Yuborilgach, men xabaringizni mijozga jo‘nataman.)", reply_markup=exit_kb)
                # record prompt so we can clear it on exit
                admin_orders_sessions[uid] = admin_orders_sessions.get(uid, []) + [{'chat_id': prompt.chat_id, 'message_id': prompt.message_id}]
                # forward the original suggestion message from the suggestions channel into admin private chat
                try:
                    if channel_msg_id:
                        fwd = await context.bot.forward_message(chat_id=uid, from_chat_id=SUGGESTIONS_CHANNEL_ID, message_id=channel_msg_id)
                        admin_orders_sessions[uid] = admin_orders_sessions.get(uid, []) + [{'chat_id': fwd.chat_id, 'message_id': fwd.message_id}]
                except Exception:
                    pass
            except Exception:
                pass
            try:
                await query.answer('Iltimos javobni yozing...')
            except Exception:
                pass
            return
        if data == "admin_orders":
            # Faol (admin tomonidan boshqariladigan) buyurtmalar: faqat kanalga e'lon qilinganlar
            published = [o for o in orders if o.get("status") == "Kanalda"]
            if not published:
                await query.edit_message_text("📭 Hozir kanalda e'lon qilingan buyurtmalar yo'q.", reply_markup=admin_panel_kb())
                return
            # Replace admin panel buttons with a reply keyboard exit button while listing orders
            try:
                await query.edit_message_text("📣 Kanalda e'lon qilingan buyurtmalar:")
            except Exception:
                pass
            exit_kb = ReplyKeyboardMarkup([[KeyboardButton("🔙 Chiqish")]], resize_keyboard=True, one_time_keyboard=True)
            # We'll collect all messages we send here (header, prompt and individual order messages)
            sent_msgs = []
            # include the edited header message (so it can be deleted later) —
            # only record messages that were actually sent to the admin's private chat
            try:
                if query.message.chat_id == uid:
                    sent_msgs.append({'chat_id': query.message.chat_id, 'message_id': query.message.message_id})
            except Exception:
                pass
            try:
                prompt_msg = await context.bot.send_message(chat_id=uid, text="🔙 Chiqish tugmasini bosing:", reply_markup=exit_kb)
                sent_msgs.append({'chat_id': prompt_msg.chat_id, 'message_id': prompt_msg.message_id})
            except Exception:
                pass
            for o in reversed(published):
                dt_str = datetime.fromisoformat(o.get("dt")).strftime('%Y-%m-%d %H:%M')
                order_text = (
                    f"#{o['order_number']} — **{o['status'].upper()}**\n"
                    f"👤 {o['user']}\n📞 {normalize_phone(o.get('phone'))}\n"
                    f"🛒 {', '.join(o.get('items', []))}\n💰 {o['total']} so‘m\n"
                    f"📍 https://www.google.com/maps/search/?api=1&query={o['loc']}\n"
                    f"🕒 {dt_str}"
                )
                try:
                    msg = await context.bot.send_message(chat_id=uid, text=order_text, reply_markup=generate_admin_order_kb(o, show_cancel=True, include_accept=False), parse_mode="Markdown")
                    sent_msgs.append({'chat_id': msg.chat_id, 'message_id': msg.message_id})
                except Exception:
                    # If sending fails, continue
                    continue
            # store session so we can delete these messages when admin exits
            admin_orders_sessions[uid] = sent_msgs
            return
        
        # Note: 'clear all orders' function removed per admin request
            
        if data.startswith("set_status_"):
            try: _, _, order_num_str, new_status = data.split("_"); order_num = int(order_num_str)
            except (ValueError, IndexError): await query.answer("Noto'g'ri buyruq", show_alert=True); return




            order = find_order(order_num)
            if not order: await query.answer("Buyurtma topilmadi", show_alert=True); return

            order['status'] = new_status
            persist_orders()

            # If admin marked it as accepted (Qabul qilingan), remove the user's confirmation message to avoid chat clutter
            try:
                if new_status == 'Qabul qilingan' and order.get('user_msg'):
                    um = order.pop('user_msg', None)
                    if um:
                        try:
                            await context.bot.delete_message(chat_id=um['chat_id'], message_id=um['message_id'])
                        except Exception:
                            pass
            except Exception:
                pass

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
        if data == "admin_broadcast":
            ud["want_broadcast"] = True
            # Edit the panel message and send a prompt with an exit keyboard so admin can cancel
            try:
                await query.edit_message_text("📢 Yuboriladigan xabarni yozing:")
            except Exception:
                pass
            exit_kb = ReplyKeyboardMarkup([[KeyboardButton("🔙 Chiqish")]], resize_keyboard=True, one_time_keyboard=True)
            try:
                prompt_msg = await context.bot.send_message(chat_id=uid, text="📢 Yuboriladigan xabarni yozing:", reply_markup=exit_kb)
                # store only the prompt message for cleanup
                admin_orders_sessions[uid] = [{'chat_id': prompt_msg.chat_id, 'message_id': prompt_msg.message_id}]
                # delete the original inline admin message to avoid duplicate text
                try:
                    await context.bot.delete_message(chat_id=query.message.chat_id, message_id=query.message.message_id)
                except Exception:
                    pass
            except Exception:
                pass
            return
        if data == "admin_add":
            ud["want_add_admin"] = True
            # Prompt admin to enter new admin ID with an exit button (like broadcast flow)
            try:
                await query.edit_message_text("➕ Yangi admin ID raqamini kiriting:")
            except Exception:
                pass
            exit_kb = ReplyKeyboardMarkup([[KeyboardButton("🔙 Chiqish")]], resize_keyboard=True, one_time_keyboard=True)
            try:
                prompt_msg = await context.bot.send_message(chat_id=uid, text="➕ Yangi admin ID raqamini kiriting:", reply_markup=exit_kb)
                # store only the prompt message for cleanup on exit
                admin_orders_sessions[uid] = [{'chat_id': prompt_msg.chat_id, 'message_id': prompt_msg.message_id}]
                # delete the original inline admin message to avoid duplicate text
                try:
                    await context.bot.delete_message(chat_id=query.message.chat_id, message_id=query.message.message_id)
                except Exception:
                    pass
            except Exception:
                pass
            return
        if data == "admin_remove":
            ud["want_remove_admin"] = True
            try:
                await query.edit_message_text("❌ O'chiriladigan admin ID raqamini kiriting:")
            except Exception:
                pass
            exit_kb = ReplyKeyboardMarkup([[KeyboardButton("🔙 Chiqish")]], resize_keyboard=True, one_time_keyboard=True)
            try:
                prompt_msg = await context.bot.send_message(chat_id=uid, text="❌ O'chiriladigan admin ID raqamini kiriting:", reply_markup=exit_kb)
                admin_orders_sessions[uid] = [{'chat_id': prompt_msg.chat_id, 'message_id': prompt_msg.message_id}]
                try:
                    await context.bot.delete_message(chat_id=query.message.chat_id, message_id=query.message.message_id)
                except Exception:
                    pass
            except Exception:
                pass
            return
        if data == "admin_add_courier":
            ud["want_add_courier"] = True
            try:
                await query.edit_message_text("➕ Yetkazib beruvchi ID raqamini kiriting:")
            except Exception:
                pass
            exit_kb = ReplyKeyboardMarkup([[KeyboardButton("🔙 Chiqish")]], resize_keyboard=True, one_time_keyboard=True)
            try:
                prompt_msg = await context.bot.send_message(chat_id=uid, text="➕ Yetkazib beruvchi ID raqamini kiriting:", reply_markup=exit_kb)
                admin_orders_sessions[uid] = [{'chat_id': prompt_msg.chat_id, 'message_id': prompt_msg.message_id}]
                try:
                    await context.bot.delete_message(chat_id=query.message.chat_id, message_id=query.message.message_id)
                except Exception:
                    pass
            except Exception:
                pass
            return
        if data == "admin_remove_courier":
            ud["want_remove_courier"] = True
            try:
                await query.edit_message_text("❌ O'chiriladigan yetkazib beruvchi ID raqamini kiriting:")
            except Exception:
                pass
            exit_kb = ReplyKeyboardMarkup([[KeyboardButton("🔙 Chiqish")]], resize_keyboard=True, one_time_keyboard=True)
            try:
                prompt_msg = await context.bot.send_message(chat_id=uid, text="❌ O'chiriladigan yetkazib beruvchi ID raqamini kiriting:", reply_markup=exit_kb)
                admin_orders_sessions[uid] = [{'chat_id': prompt_msg.chat_id, 'message_id': prompt_msg.message_id}]
                try:
                    await context.bot.delete_message(chat_id=query.message.chat_id, message_id=query.message.message_id)
                except Exception:
                    pass
            except Exception:
                pass
            return
        # Admin: mark a product as out-of-stock / back-in-stock
        if data == "admin_mark_product":
            # show categories (admin view — includes all products and their availability)
            rows = [[InlineKeyboardButton(cat, callback_data=f"amark_cat_{cat}")] for cat in menu_data.keys()]
            rows.append([InlineKeyboardButton('◀️ Bekor', callback_data='admin_panel')])
            try:
                await query.edit_message_text('Kategoriya tanlang (mahsulotni tugadi/bor qilib belgilash):', reply_markup=InlineKeyboardMarkup(rows))
            except Exception:
                pass
            await query.answer(); return
        
        # Admin: Menyuni tahrirlash -- open categories and product editor
        if data == "admin_edit_menu":
            rows = []
            for cat in menu_data.keys():
                rows.append([
                    InlineKeyboardButton(cat, callback_data=f"amenu_cat_{cat}"),
                    InlineKeyboardButton("🗑️", callback_data=f"amenu_delete_cat_{cat}")
                ])
            rows.append([InlineKeyboardButton("➕ Kategoriya qo'shish", callback_data="amenu_add_category")])
            rows.append([InlineKeyboardButton('◀️ Bekor', callback_data='admin_panel')])
            try:
                await query.edit_message_text('Menyuni tahrirlash — kategoriya tanlang:', reply_markup=InlineKeyboardMarkup(rows))
            except Exception:
                pass
            await query.answer(); return

        if data.startswith('amenu_cat_'):
            cat = data.split('_', 2)[2]
            rows = [[InlineKeyboardButton(f"{name} — {info.get('price',0)} so'm", callback_data=f"amenu_prod_{cat}|{name}")] for name, info in menu_data.get(cat, {}).items()]
            rows.append([InlineKeyboardButton("➕ Mahsulot qo'shish", callback_data=f"amenu_add_product_{cat}")])
            rows.append([InlineKeyboardButton('◀️ Orqaga', callback_data='admin_edit_menu'), InlineKeyboardButton('🔙 Admin panel', callback_data='admin_panel')])
            try:
                await query.edit_message_text(f"{cat} — mahsulotlarni tanlang:", reply_markup=InlineKeyboardMarkup(rows))
            except Exception:
                pass
            await query.answer(); return

        if data.startswith('amenu_prod_'):
            rest = data.split('_', 2)[2]
            if '|' not in rest:
                await query.answer('Noto\'g\'ri buyruq', show_alert=True); return
            cat, prod = rest.split('|', 1)
            info = menu_data.get(cat, {}).get(prod)
            if not info:
                await query.answer('Mahsulot topilmadi', show_alert=True); return
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✏️ Narxni tahrirlash", callback_data=f"amenu_edit_price_{cat}|{prod}"), InlineKeyboardButton("✏️ Tavsifni tahrirlash", callback_data=f"amenu_edit_desc_{cat}|{prod}")],
                [InlineKeyboardButton("🖼️ Rasmni tahrirlash", callback_data=f"amenu_edit_photo_{cat}|{prod}" )],
                [InlineKeyboardButton("🗑️ O'chirish", callback_data=f"amenu_delete_{cat}|{prod}"), InlineKeyboardButton('◀️ Orqaga', callback_data=f'amenu_cat_{cat}')]
            ])
            text = f"{prod}\n\nNarx: {info.get('price',0)} so'm\n\n{info.get('desc','')}"
            try:
                await query.edit_message_text(text, reply_markup=kb)
            except Exception:
                pass
            await query.answer(); return

        if data.startswith('amenu_delete_') and not data.startswith('amenu_delete_cat_'):
            rest = data.split('amenu_delete_',1)[1]
            if '|' not in rest:
                await query.answer('Noto\'g\'ri buyruq', show_alert=True); return
            cat, prod = rest.split('|',1)
            if cat in menu_data and prod in menu_data[cat]:
                try:
                    del menu_data[cat][prod]
                    persist_menu()
                except Exception:
                    pass
                try:
                    refresh_category_views(context, cat)
                except Exception:
                    pass
                try:
                    await query.edit_message_text(f"✅ '{prod}' o'chirildi.", reply_markup=admin_panel_kb())
                except Exception:
                    pass
                await query.answer(); return
            else:
                await query.answer('Mahsulot topilmadi', show_alert=True); return

        if data.startswith('amenu_delete_cat_'):
            # Show confirmation prompt before deleting a category
            cat_to_delete = data.split('amenu_delete_cat_', 1)[1]
            kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Ha, o'chirish", callback_data=f"amenu_confirm_delete_cat_{cat_to_delete}_yes"),
                    InlineKeyboardButton("❌ Yo'q, bekor", callback_data=f"amenu_confirm_delete_cat_{cat_to_delete}_no"),
                ]
            ])
            try:
                await query.edit_message_text(
                    f"Kategoriya '{cat_to_delete}' va ichidagi barcha mahsulotlar o'chirilsinmi?",
                    reply_markup=kb,
                )
            except Exception:
                pass
            await query.answer(); return

        if data.startswith('amenu_confirm_delete_cat_'):
            # Handle confirmation for deleting a category: yes/no
            rest = data.split('amenu_confirm_delete_cat_', 1)[1]
            try:
                cat_name, decision = rest.rsplit('_', 1)
            except Exception:
                await query.answer('Noto\'g\'ri buyruq', show_alert=True); return

            def _render_category_list_kb():
                rows_local = []
                for cat in menu_data.keys():
                    rows_local.append([
                        InlineKeyboardButton(cat, callback_data=f"amenu_cat_{cat}"),
                        InlineKeyboardButton("🗑️", callback_data=f"amenu_delete_cat_{cat}")
                    ])
                rows_local.append([InlineKeyboardButton("➕ Kategoriya qo'shish", callback_data="amenu_add_category")])
                rows_local.append([InlineKeyboardButton('◀️ Bekor', callback_data='admin_panel')])
                return InlineKeyboardMarkup(rows_local)

            if decision == 'yes':
                if cat_name in menu_data:
                    try:
                        del menu_data[cat_name]
                        persist_menu()
                    except Exception as e:
                        log.warning(f"Kategoriyani o'chirishda xato: {e}")
                        await query.answer('Kategoriyani o\'chirishda xatolik', show_alert=True)
                        return
                    # Try refresh user category views tied to this category
                    try:
                        refresh_category_views(context, cat_name)
                    except Exception:
                        pass
                    # Delete confirmation message and send fresh list
                    try:
                        await context.bot.delete_message(chat_id=query.message.chat_id, message_id=query.message.message_id)
                    except Exception:
                        pass
                    try:
                        await context.bot.send_message(chat_id=uid, text="Menyuni tahrirlash — kategoriya tanlang:", reply_markup=_render_category_list_kb())
                    except Exception:
                        # fallback: edit same message if delete failed
                        try:
                            await query.edit_message_text("Menyuni tahrirlash — kategoriya tanlang:", reply_markup=_render_category_list_kb())
                        except Exception:
                            pass
                    await query.answer('✅ Kategoriya o\'chirildi')
                    return
                else:
                    await query.answer('Kategoriya topilmadi', show_alert=True)
                    return
            elif decision == 'no':
                # Delete confirmation message and return to list without changes
                try:
                    await context.bot.delete_message(chat_id=query.message.chat_id, message_id=query.message.message_id)
                except Exception:
                    pass
                try:
                    await context.bot.send_message(chat_id=uid, text="Menyuni tahrirlash — kategoriya tanlang:", reply_markup=_render_category_list_kb())
                except Exception:
                    # fallback to editing
                    try:
                        await query.edit_message_text("Menyuni tahrirlash — kategoriya tanlang:", reply_markup=_render_category_list_kb())
                    except Exception:
                        pass
                await query.answer('Bekor qilindi')
                return
            else:
                await query.answer('Noto\'g\'ri tanlov', show_alert=True)
                return

        if data.startswith('amenu_add_category'):
            ud['amenu_adding_category'] = True
            try:
                # remember this inline prompt so we can delete it when the admin finishes/cancels
                ud['amenu_last_prompt'] = {'chat_id': query.message.chat_id, 'message_id': query.message.message_id}
                await query.edit_message_text('Yangi kategoriya nomini yuboring: (masalan: Ichimliklar)')
            except Exception:
                pass
            await query.answer(); return

        if data.startswith('amenu_add_product_'):
            cat = data.split('amenu_add_product_',1)[1]
            # Start step-by-step product creation: ask for name first
            ud['amenu_add_product_step'] = 'name'
            ud['amenu_add_product_cat'] = cat
            # record the prompt message so we can delete/edit it later
            try:
                # store the message we will edit (query.message) as last prompt
                ud['amenu_last_prompt'] = {'chat_id': query.message.chat_id, 'message_id': query.message.message_id}
                await query.edit_message_text("Iltimos, mahsulot nomini yuboring:")
            except Exception:
                pass
            await query.answer(); return

        if data.startswith('amenu_edit_price_'):
            rest = data.split('amenu_edit_price_',1)[1]
            if '|' not in rest:
                await query.answer('Noto\'g\'ri buyruq', show_alert=True); return
            cat, prod = rest.split('|',1)
            ud['amenu_edit_price'] = (cat, prod)
            try:
                ud['amenu_last_prompt'] = {'chat_id': query.message.chat_id, 'message_id': query.message.message_id}
                await query.edit_message_text('Yangi narxni yuboring (son bilan, faqat raqam):')
            except Exception:
                pass
            await query.answer(); return

        if data.startswith('amenu_edit_desc_'):
            rest = data.split('amenu_edit_desc_',1)[1]
            if '|' not in rest:
                await query.answer('Noto\'g\'ri buyruq', show_alert=True); return
            cat, prod = rest.split('|',1)
            ud['amenu_edit_desc'] = (cat, prod)
            try:
                ud['amenu_last_prompt'] = {'chat_id': query.message.chat_id, 'message_id': query.message.message_id}
                await query.edit_message_text('Yangi tavsif matnini yuboring:')
            except Exception:
                pass
            await query.answer(); return

        if data.startswith('amenu_edit_photo_'):
            rest = data.split('amenu_edit_photo_',1)[1]
            if '|' not in rest:
                await query.answer('Noto\'g\'ri buyruq', show_alert=True); return
            cat, prod = rest.split('|',1)
            # set state so text_handler (photo) will handle next photo message
            ud['amenu_edit_photo'] = (cat, prod)
            try:
                ud['amenu_last_prompt'] = {'chat_id': query.message.chat_id, 'message_id': query.message.message_id}
                await query.edit_message_text('Iltimos, yangi rasmini yuboring (rasm yuboring):')
            except Exception:
                try:
                    # fallback: send prompt
                    sent = await context.bot.send_message(chat_id=uid, text='Iltimos, yangi rasmini yuboring (rasm yuboring):')
                    ud['amenu_last_prompt'] = {'chat_id': sent.chat_id, 'message_id': sent.message_id}
                except Exception:
                    pass
            await query.answer(); return

        if data.startswith('amark_cat_'):
            # pick category -> show all products (including unavailable) with status
            cat = data.split('_', 2)[2]
            rows = []
            for name, info in menu_data.get(cat, {}).items():
                status = "(Tugadi)" if not info.get('available', True) else "(Bor)"
                rows.append([InlineKeyboardButton(f"{name} {status}", callback_data=f"amark_prod_{cat}|{name}")])
            rows.append([InlineKeyboardButton('◀️ Orqaga', callback_data='admin_mark_product'), InlineKeyboardButton('🔙 Admin panel', callback_data='admin_panel')])
            try:
                await query.edit_message_text(f"{cat} — mahsulotlarni tanlang:", reply_markup=InlineKeyboardMarkup(rows))
            except Exception:
                pass
            await query.answer(); return

        if data.startswith('amark_prod_'):
            # show product with buttons to mark available/unavailable
            rest = data.split('amark_prod_',1)[1]
            if '|' not in rest:
                await query.answer('Noto\'g\'ri buyruq', show_alert=True); return
            cat, prod = rest.split('|',1)
            if cat not in menu_data or prod not in menu_data[cat]:
                await query.answer('Mahsulot topilmadi', show_alert=True); return
            info = menu_data[cat][prod]
            current_status = "Bor" if info.get('available', True) else "Tugadi"
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton('✅ Bor', callback_data=f'amark_set_{cat}|{prod}_available'), InlineKeyboardButton('❌ Tugadi', callback_data=f'amark_set_{cat}|{prod}_unavailable')],
                [InlineKeyboardButton('◀️ Orqaga', callback_data=f'amark_cat_{cat}')]
            ])
            try:
                await query.edit_message_text(f"{prod}\n\nJoriy holat: {current_status}\n\nMahsulotni bor yoki tugadi deb belgilang:", reply_markup=kb)
            except Exception:
                pass
            await query.answer(); return

        if data.startswith('amark_set_'):
            rest = data.split('amark_set_',1)[1]
            action = None
            if rest.endswith('_available'):
                action = 'available'; core = rest[:-len('_available')]
            elif rest.endswith('_unavailable'):
                action = 'unavailable'; core = rest[:-len('_unavailable')]
            else:
                await query.answer('Noto\'g\'ri buyruq', show_alert=True); return
            if '|' not in core:
                await query.answer('Noto\'g\'ri buyruq', show_alert=True); return
            cat, prod = core.split('|',1)
            if cat not in menu_data or prod not in menu_data[cat]: await query.answer('Mahsulot topilmadi', show_alert=True); return
            menu_data[cat][prod]['available'] = (action == 'available')
            persist_menu()
            # Update any recent category messages we know about so users see the change immediately
            try:
                for (chat_id, c), msg_id in list(last_category_messages.items()):
                    if c == cat:
                        try:
                            await context.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=f"📋 {cat} menyusi:", reply_markup=product_list_kb(cat))
                        except Exception:
                            # ignore failures (message deleted or no permission)
                            try:
                                # if editing failed, remove mapping to avoid repeated failures
                                last_category_messages.pop((chat_id, c), None)
                            except Exception:
                                pass
            except Exception:
                pass
            # Notify admin and go back to category view
            try:
                state_text = '✅ Mahsulot bor qilib belgilandi.' if action == 'available' else '✅ Mahsulot tugadi deb belgilandi.'
                await query.edit_message_text(state_text, reply_markup=admin_panel_kb())
            except Exception:
                pass
            await query.answer(); return
    # Payment callbacks (user finishing checkout)
    if data == 'pay_cash' or data == 'pay_card':
        is_cash = (data == 'pay_cash')
        pending = context.user_data.get('pending_order')
        if not pending:
            await query.answer("Hech qanday buyurtma topilmadi.", show_alert=True); return

        # If user chose card and we have a provider token, send Telegram Invoice
        if (not is_cash) and PAYMENT_PROVIDER_TOKEN:
            try:
                payload = f"pay_pending_{update.effective_user.id}_{int(time.time())}"
                prices = [LabeledPrice("Buyurtma", int(pending['total']))]
                # store pending invoice so successful_payment handler can create order
                context.user_data['pending_invoice'] = {'payload': payload, 'pending_order': pending}
                await context.bot.send_invoice(
                    chat_id=update.effective_user.id,
                    title=f"Buyurtma — {pending.get('original_text','')[:64]}",
                    description=(pending.get('original_text','') or 'Buyurtma to‘lovi'),
                    payload=payload,
                    provider_token=PAYMENT_PROVIDER_TOKEN,
                    currency='UZS',
                    prices=prices,
                )
                try:
                    await query.edit_message_text("✅ To'lov varaqasi yuborildi. Iltimos, to'lovni tugating.")
                    # also provide a reply keyboard with an exit button so user can easily close the flow
                    try:
                        exit_kb = ReplyKeyboardMarkup([[KeyboardButton('🔙 Chiqish')]], resize_keyboard=True, one_time_keyboard=True)
                        await context.bot.send_message(chat_id=update.effective_user.id, text="Agar tugatsangiz, '🔙 Chiqish' tugmasini bosing.", reply_markup=exit_kb)
                    except Exception:
                        pass
                except Exception:
                    pass
                return
            except Exception as e:
                log.warning(f"Invoice yuborishda xato: {e}")
                # fallback to create order as unpaid card order below

        # Fallback / cash flow: create order immediately (existing behavior)
        # remove pending_order from user_data now that we will persist as an order
        context.user_data.pop('pending_order', None)
        order_counter += 1; order_number = order_counter
        order = {
            'order_number': order_number,
            'user_id': update.effective_user.id,
            'user_name': update.effective_user.full_name,
            'user_username': update.effective_user.username or '',
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
            'payment': 'cash' if is_cash else 'card',
            'paid': False,
        }
        # If cash or card (we require OTP confirmation at delivery), generate OTP
        if True:
            otp = generate_otp()
            order['otp'] = otp
        orders.append(order)

        cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"❌ Bekor qilish #{order_number}", callback_data=f"cancel_order_{order_number}")]])
        sent = await query.message.reply_text(f"✅ Buyurtmangiz #{order_number} qabul qilindi!\n\n{order.get('original_text')}\n\n⏳ Bekor qilish uchun 30 soniyangiz bor.", reply_markup=cancel_kb)
        order['user_msg'] = {'chat_id': sent.chat_id, 'message_id': sent.message_id}
        try:
            await query.edit_message_text("Buyurtma qabul qilindi. Kanalga e'lon qilish 30s ichida amalga oshiriladi.")
        except Exception:
            pass

        persist_orders()
        t = asyncio.create_task(handle_order_expiry(order_number, context.bot))
        expiry_tasks[order_number] = t

        # Send OTP to user (for both cash and card flows we generate OTP)
        try:
            exit_kb = ReplyKeyboardMarkup([[KeyboardButton('🔙 Chiqish')]], resize_keyboard=True, one_time_keyboard=True)
            await context.bot.send_message(chat_id=order['user_id'], text=f"Sizning buyurtmangiz uchun tasdiq kodi (OTP): {order['otp']}. Ushbu kodni yetkazib beruvchiga yetkazilganda berishingiz kerak.", reply_markup=exit_kb)
        except Exception as e:
            log.warning(f"OTP yuborishda xato: {e}")
        return

    # --- Super-admin inline tahrir callbacklari ---
    if data.startswith('sa_inc_') or data.startswith('sa_dec_') or data.startswith('sa_add_') or data.startswith('sa_done_') or data.startswith('sa_canceledit_'):
        if uid not in admins:
            await query.answer('Sizda ruxsat yo\'q', show_alert=True); return

        parts = data.split('_')
        # format: sa_inc_<order>_<idx>
        action = parts[1] if len(parts) > 1 else ''
        if action in ('inc', 'dec'):
            try:
                order_num = int(parts[2]); idx = int(parts[3])
            except Exception:
                await query.answer('Noto\'g\'ri buyruq', show_alert=True); return
            order = find_order(order_num)
            if not order: await query.answer('Buyurtma topilmadi', show_alert=True); return
            items = list(order.get('items', []))
            if idx < 0 or idx >= len(items): await query.answer('Indeks xato', show_alert=True); return
            it = items[idx]
            if ' x' in it:
                name, qty_str = it.rsplit(' x', 1)
                try: qty = int(qty_str)
                except Exception: qty = 1
            else:
                name = it; qty = 1
            if action == 'inc': qty += 1
            else: qty = max(1, qty - 1)
            items[idx] = f"{name} x{qty}"
            # recompute total
            total = 0
            for it2 in items:
                if ' x' in it2:
                    nm, q = it2.rsplit(' x', 1); q = int(q)
                else:
                    nm = it2; q = 1
                total += product_price(nm) * q
            order['items'] = items
            order['total'] = total
            persist_orders()
            # update superadmin message
            sam = order.get('superadmin_msg')
            if sam:
                try:
                    await context.bot.edit_message_text(chat_id=sam['chat_id'], message_id=sam['message_id'], text=build_superadmin_order_text(order), reply_markup=build_superadmin_kb(order), parse_mode='HTML')
                except Exception:
                    pass
            await query.answer('Yangilandi')
            return

        if action == 'add':
            try: order_num = int(parts[2])
            except Exception: await query.answer('Noto\'g\'ri buyruq', show_alert=True); return
            # prompt admin to send product as: Name | qty
            context.user_data['sa_adding_order'] = order_num
            await query.answer('Iltimos, mahsulot nomi va miqdorini "Nomi | miqdor" formatida yuboring.')
            try: await query.edit_message_text('Mahsulot qo\'shish uchun nom va miqdorni yuboring (masalan: Lavash | 1)')
            except Exception: pass
            return

        if action == 'done':
            try: order_num = int(parts[2])
            except Exception: await query.answer('Noto\'g\'ri buyruq', show_alert=True); return
            order = find_order(order_num)
            if not order: await query.answer('Buyurtma topilmadi', show_alert=True); return
            # post to channel
            order['status'] = 'Kanalda'
            try:
                kanal_text = f"🆕 Yangi buyurtma #{order_num}!\n\n{order.get('original_text','')}\n\n👤 {order.get('user')}\n📞 {normalize_phone(order.get('phone'))}\n📍 https://www.google.com/maps/search/?api=1&query={order.get('loc')}"
                msg = await context.bot.send_message(chat_id=BUYURTMALAR_CHANNEL_ID, text=kanal_text, reply_markup=generate_admin_order_kb(order, show_cancel=False, show_edit=False))
                order['admin_msgs'] = [{'admin_id': BUYURTMALAR_CHANNEL_ID, 'chat_id': msg.chat_id, 'message_id': msg.message_id, 'text': order.get('original_text','')}]
                persist_orders()
            except Exception as e:
                log.warning(f"Kanalga yuborishda xato (sa_done): {e}")
            # update superadmin message to indicate done
            sam = order.get('superadmin_msg')
            if sam:
                try:
                    await context.bot.edit_message_text(chat_id=sam['chat_id'], message_id=sam['message_id'], text=build_superadmin_order_text(order) + "\n\n✅ Kanalga yuborildi.")
                except Exception:
                    pass
            await query.answer('Buyurtma kanalga yuborildi')
            return

        if action == 'canceledit':
            try: order_num = int(parts[2])
            except Exception: await query.answer('Noto\'g\'ri buyruq', show_alert=True); return
            order = find_order(order_num)
            if not order: await query.answer('Buyurtma topilmadi', show_alert=True); return
            sam = order.get('superadmin_msg')
            if sam:
                try:
                    await context.bot.edit_message_text(chat_id=sam['chat_id'], message_id=sam['message_id'], text=build_superadmin_order_text(order) + "\n\n❌ Tahrirlash bekor qilindi.")
                except Exception:
                    pass
            order.pop('superadmin_msg', None)
            persist_orders()
            await query.answer('Tahrirlash bekor qilindi')
            return

        # Admin-triggered item-level edit flow (opens inline editor)
        if data.startswith('admin_edit_'):
            try:
                order_num = int(data.split('_')[-1])
            except Exception:
                await query.answer('Noto\'g\'ri buyruq', show_alert=True); return
            order = find_order(order_num)
            if not order:
                await query.answer('Buyurtma topilmadi', show_alert=True); return
            log.info(f"admin_edit callback received for order {order_num} by admin {uid}")
            # prepare proposed_items copy
            order['proposed_items'] = list(order.get('items', []))
            # compute proposed total
            total = 0
            for it in order['proposed_items']:
                if ' x' in it:
                    nm, q = it.rsplit(' x', 1); q = int(q)
                else:
                    nm = it; q = 1
                total += product_price(nm) * q
            order['proposed_total'] = total
            order['proposed_by_admin'] = uid
            persist_orders()
            # send editor to admin
            try:
                txt = f"✏️ Buyurtma #{order_num} tahriri (admin tomonidan).\n\nJoriy mahsulotlar:\n" + "\n".join(order['proposed_items']) + f"\n\nJami: {order['proposed_total']} so'm"
                msg = await context.bot.send_message(chat_id=uid, text=txt, reply_markup=build_admin_edit_kb(order))
                order['admin_edit_msg'] = {'chat_id': msg.chat_id, 'message_id': msg.message_id}
                persist_orders()
                await query.answer('Tahrirlash oynasi ochildi')
            except Exception as e:
                log.warning(f"Admin edit window send failed for order {order_num}: {e}")
                # fallback: notify admin and show alert
                try:
                    await context.bot.send_message(chat_id=uid, text=f"Tahrirlash oynasi ochilmadi (order #{order_num}). Iltimos /start ni bosing yoki admin panelni tekshiring.")
                except Exception:
                    pass
                await query.answer('Tahrirlash oynasi ochilmadi – adminga xabar yuborildi', show_alert=True)
            return
        
            # --- Admin edit (ae_) callbacks: inc/dec/add/done/cancel and pick product ---
            if data.startswith('ae_inc_') or data.startswith('ae_dec_') or data.startswith('ae_add_') or data.startswith('ae_done_') or data.startswith('ae_cancel_') or data.startswith('ae_pick_'):
                if uid not in admins:
                    await query.answer('Sizda ruxsat yo\'q', show_alert=True); return
                parts = data.split('_')
                # inc/dec format: ae_inc_<order>_<idx>
                if parts[1] in ('inc','dec'):
                    try:
                        order_num = int(parts[2]); idx = int(parts[3])
                    except Exception:
                        await query.answer('Noto\'g\'ri buyruq', show_alert=True); return
                    order = find_order(order_num)
                    if not order or 'proposed_items' not in order:
                        await query.answer('No edit session', show_alert=True); return
                    items = list(order['proposed_items'])
                    if idx < 0 or idx >= len(items): await query.answer('Indeks xato', show_alert=True); return
                    it = items[idx]
                    if ' x' in it:
                        name, qty_str = it.rsplit(' x', 1)
                        try: qty = int(qty_str)
                        except Exception: qty = 1
                    else:
                        name = it; qty = 1
                    if parts[1] == 'inc': qty += 1
                    else: qty = max(1, qty - 1)
                    items[idx] = f"{name} x{qty}"
                    # recompute total
                    total = 0
                    for it2 in items:
                        if ' x' in it2:
                            nm, q = it2.rsplit(' x', 1); q = int(q)
                        else:
                            nm = it2; q = 1
                        total += product_price(nm) * q
                    order['proposed_items'] = items
                    order['proposed_total'] = total
                    persist_orders()
                    # update admin edit message
                    ae_msg = order.get('admin_edit_msg')
                    txt = f"✏️ Buyurtma #{order_num} tahriri (admin tomonidan).\n\nJoriy mahsulotlar:\n" + "\n".join(order['proposed_items']) + f"\n\nJami: {order['proposed_total']} so'm"
                    try:
                        if ae_msg:
                            await context.bot.edit_message_text(chat_id=ae_msg['chat_id'], message_id=ae_msg['message_id'], text=txt, reply_markup=build_admin_edit_kb(order))
                        else:
                            await query.edit_message_text(txt, reply_markup=build_admin_edit_kb(order))
                    except Exception:
                        pass
                    await query.answer('Yangilandi')
                    return

                # add product -> show categories
                if parts[1] == 'add':
                    try: order_num = int(parts[2])
                    except Exception: await query.answer('Noto\'g\'ri buyruq', show_alert=True); return
                    # build categories kb
                    rows = [[InlineKeyboardButton(cat, callback_data=f"ae_pick_{order_num}_cat_{cat}")] for cat in menu_data.keys()]
                    rows.append([InlineKeyboardButton('◀️ Bekor', callback_data=f'ae_cancel_{order_num}')])
                    try:
                        await query.edit_message_text('Kategoriya tanlang:', reply_markup=InlineKeyboardMarkup(rows))
                    except Exception:
                        pass
                    await query.answer(); return

                # pick callbacks (category -> products, or product select)
                if parts[1] == 'pick':
                    # format: ae_pick_<order>_cat_<cat>  OR ae_pick_<order>_prod_<cat>|<prod>
                    try:
                        order_num = int(parts[2])
                    except Exception:
                        await query.answer('Noto\'g\'ri buyruq', show_alert=True); return
                    sub = parts[3]
                    order = find_order(order_num)
                    if not order: await query.answer('Buyurtma topilmadi', show_alert=True); return
                    if sub == 'cat':
                        cat = '_'.join(parts[4:])
                        # build products list
                        rows = [[InlineKeyboardButton(f"{name} — {info['price']} so'm", callback_data=f"ae_pick_{order_num}_prod_{cat}|{name}")] for name, info in menu_data.get(cat, {}).items()]
                        rows.append([InlineKeyboardButton('◀️ Orqaga', callback_data=f"ae_add_{order_num}")])
                        try: await query.edit_message_text(f"{cat} menyusi:", reply_markup=InlineKeyboardMarkup(rows))
                        except Exception: pass
                        await query.answer(); return
                    if sub == 'prod':
                        rest = '_'.join(parts[4:])
                        # rest is like <cat>|<name>
                        if '|' not in rest:
                            await query.answer('Noto\'g\'ri format', show_alert=True); return
                        cat, prod = rest.split('|',1)
                        # append product x1
                        items = list(order.get('proposed_items', []))
                        items.append(f"{prod} x1")
                        total = 0
                        for it2 in items:
                            if ' x' in it2:
                                nm, q = it2.rsplit(' x', 1); q = int(q)
                            else:
                                nm = it2; q = 1
                            total += product_price(nm) * q
                        order['proposed_items'] = items
                        order['proposed_total'] = total
                        persist_orders()
                        ae_msg = order.get('admin_edit_msg')
                        txt = f"✏️ Buyurtma #{order_num} tahriri (admin tomonidan).\n\nJoriy mahsulotlar:\n" + "\n".join(order['proposed_items']) + f"\n\nJami: {order['proposed_total']} so'm"
                        try:
                            if ae_msg:
                                await context.bot.edit_message_text(chat_id=ae_msg['chat_id'], message_id=ae_msg['message_id'], text=txt, reply_markup=build_admin_edit_kb(order))
                            else:
                                await query.edit_message_text(txt, reply_markup=build_admin_edit_kb(order))
                        except Exception:
                            pass
                        await query.answer('Mahsulot qo\'shildi')
                        return

                # done -> send confirmation to user
                if parts[1] == 'done':
                    try: order_num = int(parts[2])
                    except Exception: await query.answer('Noto\'g\'ri buyruq', show_alert=True); return
                    order = find_order(order_num)
                    if not order or 'proposed_items' not in order: await query.answer('No edit session', show_alert=True); return
                    # send to user for confirmation
                    user_id = order.get('user_id')
                    confirm_txt = (
                        f"📣 Buyurtmangiz uchun tahrir taklifi mavjud.\n\nOldingi: \n" + "\n".join(order.get('items', [])) + f"\n\nYangi: \n" + "\n".join(order['proposed_items']) + f"\n\nJami: {order['proposed_total']} so'm\n\nAgar rozisiz, 'Qabul qilaman' tugmasini bosing.")
                    kb = InlineKeyboardMarkup([[InlineKeyboardButton('✅ Qabul qilaman', callback_data=f'ae_user_confirm_{order_num}_approve'), InlineKeyboardButton('❌ Rad etaman', callback_data=f'ae_user_confirm_{order_num}_reject')]])
                    try:
                        await context.bot.send_message(chat_id=user_id, text=confirm_txt, reply_markup=kb)
                        await query.edit_message_text('✅ Taklif mijozga yuborildi. Javobni kuting.', reply_markup=admin_panel_kb())
                        persist_orders()
                    except Exception as e:
                        await query.answer('Foydalanuvchiga yuborilmadi', show_alert=True); log.warning(f"Taklif yuborishda xato: {e}")
                    return

                # cancel
                if parts[1] == 'cancel':
                    try: order_num = int(parts[2])
                    except Exception: await query.answer('Noto\'g\'ri buyruq', show_alert=True); return
                    order = find_order(order_num)
                    if not order: await query.answer('Buyurtma topilmadi', show_alert=True); return
                    # remove proposed fields
                    order.pop('proposed_items', None); order.pop('proposed_total', None); order.pop('proposed_by_admin', None)
                    ae_msg = order.get('admin_edit_msg')
                    try:
                        if ae_msg:
                            await context.bot.edit_message_text(chat_id=ae_msg['chat_id'], message_id=ae_msg['message_id'], text='Tahrirlash bekor qilindi.')
                    except Exception:
                        pass
                    persist_orders()
                    await query.answer('Tahrirlash bekor qilindi')
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
        # delete the user's confirmation message to avoid chat clutter
        try:
            if order.get('user_msg'):
                um = order.pop('user_msg', None)
                if um:
                    try:
                        await context.bot.delete_message(chat_id=um['chat_id'], message_id=um['message_id'])
                    except Exception:
                        pass
        except Exception:
            pass
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
        # Prefer explicit user fields if present, otherwise fall back to order['user'] string
        u_name = order.get('user_name') or order.get('user') or 'Noma\'lum'
        u_username = order.get('user_username') or ''
        username_display = f"@{u_username}" if u_username else '—'
        order_phone = order.get('phone') or ''
        profile_phone = users_info.get(order.get('user_id'), {}).get('phone') if order.get('user_id') in users_info else None
        # Build phone lines: show both order phone and profile phone if both exist and differ
        phone_lines = []
        if order_phone:
            phone_lines.append(f"Buyurtma telefoni: {phone_html_link(order_phone)}")
        if profile_phone and profile_phone != order_phone:
            phone_lines.append(f"Profil telefoni: {phone_html_link(profile_phone)}")
        if not phone_lines:
            phone_lines_text = "Tel: Noma'lum"
        else:
            phone_lines_text = "\n".join(phone_lines)
        courier_text = (
            f"🚚 Siz #{order_num} buyurtmani qabul qildingiz.\n\n"
            f"{html.escape(order.get('original_text',''))}\n\n"
            f"Ism: {html.escape(u_name)}\n"
            f"Username: {html.escape(username_display)}\n"
            f"{phone_lines_text}\n"
            f"Manzil: https://www.google.com/maps/search/?api=1&query={html.escape(order.get('loc'))}"
        )
        # include payment type info for courier so they know how to collect/verify payment
        try:
            pay_type = order.get('payment', '—')
            paid_flag = " (to'lov onlayn amalga oshirilgan)" if order.get('paid') else ''
            courier_text = courier_text + f"\n\nTo'lov turi: {pay_type}{paid_flag}\n"
            if pay_type == 'card':
                courier_text = courier_text + "\n⚠️ Mijoz onlayn to'lovni tanlagan. Yetkazib berishda mijozdan to'lov kvitansiyasini (screenshot yoki bank ilovasidagi chek) so'rang va shu chatga rasm sifatida yuboring. Cheksiz yetkazilgan deb belgilash mumkin emas.\n"
        except Exception:
            pass
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
        # If payment was card, first require OTP confirmation, then ask for receipt photo
        if order.get('payment') == 'card':
            context.user_data['expecting_otp_for'] = order_num
            try:
                await context.bot.send_message(chat_id=uid, text=f"⚠️ Mijoz onlayn to'lovni tanlagan. Avvalo mijozdan OTP kodni oling va quyidagi ko'rsatmaga asosan tasdiqlang. OTP tasdiqlangandan so'ng sizdan chek rasmini yuborishingiz so'raladi.")
            except Exception:
                pass
            await query.answer('OTP kodini kiriting...')
            return

        # other non-cash (no verification required): finalize immediately
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
    # --- Qayta buyurtma (reorder) ---
    if data.startswith('reorder_'):
        try:
            order_num = int(data.split('_')[-1])
        except Exception:
            await query.answer("Noto'g'ri buyruq", show_alert=True); return
        order = find_order(order_num)
        if not order:
            await query.answer('Buyurtma topilmadi', show_alert=True); return
        # ensure only the original user can reorder their own order
        if uid != order.get('user_id'):
            await query.answer('Bu buyurtma sizga tegishli emas', show_alert=True); return
        # build cart from previous order items (items are like 'Name xN')
        new_cart = {}
        for it in order.get('items', []):
            if ' x' in it:
                name, qty_s = it.rsplit(' x', 1)
                try: qty = int(qty_s)
                except Exception: qty = 1
            else:
                name = it; qty = 1
            new_cart[name] = new_cart.get(name, 0) + qty
        ud = context.user_data
        ud['cart'] = new_cart
        # start checkout: ask for phone (same as the normal checkout flow)
        ud['checkout_state'] = 'ask_phone'
        prompt = "Iltimos, bog'lanish mumkin bo'lgan raqamni kiriting (masalan: +998901234567):"
        try:
            sent = await context.bot.send_message(chat_id=uid, text=prompt)
            ud['last_prompt_msg'] = {'chat_id': sent.chat_id, 'message_id': sent.message_id}
        except Exception:
            try:
                await query.message.reply_text(prompt)
            except Exception:
                pass
        try:
            await query.answer('✅ Savat yangilandi — to‘lov uchun telefon kiriting')
        except Exception:
            pass
        return
    if data.startswith("cat_"):
        cat = data.split("_", 1)[1]
        try:
            await query.edit_message_text(f"📋 {cat} menyusi:", reply_markup=product_list_kb(cat))
            # remember last category view for this chat so we can update it when availability changes
            try:
                last_category_messages[(query.message.chat_id, cat)] = query.message.message_id
            except Exception:
                # if we can't access message fields, ignore
                pass
        except Exception:
            pass
    elif data == "back_categories":
        try:
            await query.edit_message_text("Kategoriya tanlang:", reply_markup=category_menu_kb())
        except BadRequest as e:
            # This can happen if the current message has no editable text (e.g. a photo message).
            # Fall back: send a new message with the category keyboard and try to delete the old message.
            try:
                await context.bot.send_message(chat_id=query.message.chat_id, text="Kategoriya tanlang:", reply_markup=category_menu_kb())
                try:
                    await context.bot.delete_message(chat_id=query.message.chat_id, message_id=query.message.message_id)
                except Exception:
                    pass
            except Exception:
                # last-resort: ignore
                pass
    elif data.startswith("prod_"):
        _, rest = data.split("_", 1); cat, prod = rest.split("|")
        ud.update({"current_cat": cat, "current_prod": prod, "current_qty": 1})
        info = menu_data[cat][prod]
        text = f"🍽 {prod}\n\n💰 Narxi: {info.get('price',0)} so‘m\n\n{info.get('desc','')}"
        # If product has a photo saved (file_id), send photo view; otherwise edit text
        photo = info.get('photo')
        if photo:
            try:
                # send photo message with caption + keyboard, then delete the previous message
                sent = await context.bot.send_photo(chat_id=query.message.chat_id, photo=photo, caption=text, reply_markup=quantity_kb(cat, prod, 1))
                try:
                    await context.bot.delete_message(chat_id=query.message.chat_id, message_id=query.message.message_id)
                except Exception:
                    pass
            except Exception:
                # fallback to text if sending photo fails
                try:
                    await query.edit_message_text(text, reply_markup=quantity_kb(cat, prod, 1))
                except Exception:
                    pass
        else:
            try:
                await query.edit_message_text(text, reply_markup=quantity_kb(cat, prod, 1))
            except Exception:
                pass
    elif data.startswith("qty_"):
        _, rest = data.split("_", 1); cat, prod, op = rest.split("|")
        qty = ud.get("current_qty", 1); qty = max(1, qty - 1) if op == "dec" else qty + 1
        ud["current_qty"] = qty; await query.edit_message_reply_markup(reply_markup=quantity_kb(cat, prod, qty))
    elif data.startswith("add_"):
        _, rest = data.split("_", 1); prod, qty_str = rest.split("|"); qty = int(qty_str)
        cart = ud["cart"]; cart[prod] = cart.get(prod, 0) + qty
        text, _ = cart_text_and_total(cart)
        msg_text = f"✅ {prod} x{qty} savatga qo‘shildi.\n\n{text}"
        try:
            await query.edit_message_text(msg_text, reply_markup=cart_menu_kb(bool(cart)))
        except BadRequest:
            # If the current message is a media (photo) message, edit_message_text will fail.
            # Fallback: send a new message with the cart text and delete the old message to avoid duplicates.
            try:
                sent = await context.bot.send_message(chat_id=query.message.chat_id, text=msg_text, reply_markup=cart_menu_kb(bool(cart)))
                try:
                    await context.bot.delete_message(chat_id=query.message.chat_id, message_id=query.message.message_id)
                except Exception:
                    pass
            except Exception:
                # if even sending fails, ignore to avoid crashing
                pass
    elif data == "view_cart": text, _ = cart_text_and_total(ud["cart"]); await query.edit_message_text(text, reply_markup=cart_menu_kb(bool(ud["cart"])))
    elif data == "clear_cart": ud["cart"] = {}; await query.edit_message_text("🧹 Savat tozalandi.", reply_markup=cart_menu_kb(False))
    elif data == "checkout":
        if not ud.get("cart"): await query.edit_message_text("🛒 Savat bo‘sh.", reply_markup=category_menu_kb()); return
        # Ask for phone as plain text (user types it) rather than using request_contact.
        ud["checkout_state"] = "ask_phone"
        prompt = "Iltimos, bog'lanish mumkin bo'lgan raqamni kiriting (masalan: +998901234567):"
        # send phone prompt and remember its message id so we can delete it later
        try:
            sent = await query.message.reply_text(prompt)
            ud['last_prompt_msg'] = {'chat_id': sent.chat_id, 'message_id': sent.message_id}
        except Exception:
            try:
                # fallback: send directly to user
                sent = await context.bot.send_message(chat_id=update.effective_user.id, text=prompt)
                ud['last_prompt_msg'] = {'chat_id': sent.chat_id, 'message_id': sent.message_id}
            except Exception:
                pass
        try:
            await query.delete_message()
        except Exception:
            pass

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

        # Mark the order as canceled instead of deleting it so we keep a record.
        # This prevents accidental loss of all orders when UI exit/cleanup flows run.
        order['status'] = 'Bekor qilindi'
        order['canceled_by'] = update.effective_user.id
        order['canceled_at'] = datetime.now(timezone.utc).isoformat()
        persist_orders()
        return

    # Admin: exit from active-orders view and cleanup messages
    if data == 'admin_orders_exit' and uid in admins:
        # delete all messages and transient prompts for this admin's session
        try:
            await clear_admin_session(uid, context, ud)
        except Exception:
            pass
        # Restore admin panel on the original query message
        try:
            await query.edit_message_text("🔑 Admin panelga xush kelibsiz!", reply_markup=admin_panel_kb())
        except Exception:
            pass
        await query.answer()
        return

    # --- User confirmation for admin-proposed edit ---
    if data.startswith('ae_user_confirm_'):
        # format: ae_user_confirm_<order>_approve|reject
        parts = data.split('_')
        try: order_num = int(parts[3]); action = parts[4]
        except Exception:
            await query.answer('Noto\'g\'ri buyruq', show_alert=True); return
        order = find_order(order_num)
        if not order:
            await query.answer('Buyurtma topilmadi', show_alert=True); return
        uid = update.effective_user.id
        if uid != order.get('user_id'):
            await query.answer('Bu tasdiq sizga tegishli emas', show_alert=True); return
        if action == 'approve':
            # apply proposed
            if 'proposed_items' not in order:
                await query.answer('Hech qanday taklif topilmadi', show_alert=True); return
            order['items'] = list(order['proposed_items'])
            order['total'] = order.get('proposed_total', order.get('total', 0))
            # cleanup
            order.pop('proposed_items', None); order.pop('proposed_total', None)
            prop_by = order.pop('proposed_by_admin', None)
            persist_orders()
            # update channel/admin msgs
            for am in order.get('admin_msgs', []):
                try:
                    await context.bot.edit_message_text(chat_id=am['chat_id'], message_id=am['message_id'], text=order.get('original_text',''))
                except Exception:
                    pass
            # update superadmin message
            sam = order.get('superadmin_msg')
            if sam:
                try:
                    await context.bot.edit_message_text(chat_id=sam['chat_id'], message_id=sam['message_id'], text=build_superadmin_order_text(order), reply_markup=build_superadmin_kb(order), parse_mode='HTML')
                except Exception:
                    pass
            # notify admin who proposed
            if prop_by:
                try:
                    await context.bot.send_message(chat_id=prop_by, text=f"✅ Mijoz buyurtma #{order_num} tahririni qabul qildi.")
                except Exception:
                    pass
            await query.edit_message_text('✅ Sizning o\'zgartirishlaringiz qabul qilindi. Rahmat!')
            return
        else:
            # rejected
            order.pop('proposed_items', None); order.pop('proposed_total', None); prop_by = order.pop('proposed_by_admin', None)
            persist_orders()
            if prop_by:
                try: await context.bot.send_message(chat_id=prop_by, text=f"❌ Mijoz buyurtma #{order_num} tahririni rad etdi.")
                except Exception: pass
            await query.edit_message_text('❌ Siz o\'zgartirishni rad qildingiz.')
            return

# ========== XABAR HANDLERLARI ==========
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (o'zgarishsiz)
    uid = update.effective_user.id; text = (update.message.text or "").strip(); ud = context.user_data; ud.setdefault("cart", {})
    # Courier receipt photo flow: if courier is expected to submit a payment receipt image
    try:
        if uid in couriers and ud.get('expecting_receipt_for') and update.message.photo:
            order_num = int(ud.get('expecting_receipt_for'))
            order = find_order(order_num)
            if not order:
                await update.message.reply_text('Buyurtma topilmadi.'); ud.pop('expecting_receipt_for', None); return
            # save highest-resolution photo file_id as receipt proof
            file_id = update.message.photo[-1].file_id
            order['receipt_photo'] = file_id
            # finalize delivery
            order['status'] = 'Yetkazib berildi'
            order['collected_amount'] = order.get('total')
            cid = uid
            rec = earnings.get(cid, {'total': 0, 'deliveries': []})
            rec['total'] = rec.get('total', 0) + order.get('total', 0)
            rec.setdefault('deliveries', []).append(order_num)
            earnings[cid] = rec
            persist_earnings()
            persist_orders()
            # notify user with friendly message
            try:
                await context.bot.send_message(chat_id=order['user_id'], text=f"✅ Sizning #{order_num} buyurtmangiz yetkazib berildi. Yoqimli ishtaha! 🍽️")
            except Exception as e:
                log.warning(f"Foydalanuvchiga yetkazildi xabarida xato: {e}")
            # edit courier message to indicate delivered and attach note
            try:
                await context.bot.edit_message_text(chat_id=order['courier_msg']['chat_id'], message_id=order['courier_msg']['message_id'], text="✅ Yetkazildi (Onlayn to'lov, chek yuklandi)")
            except Exception:
                pass
            # send receipt photo to payments channel for records
            try:
                await context.bot.send_photo(chat_id=PAYMENTS_CHANNEL_ID, photo=file_id, caption=f"[CHEK] Buyurtma #{order_num} — Yetkazib beruvchi: {cid} — Mijoz: {order.get('user')} — Jami: {order.get('total')} so'm")
            except Exception:
                pass
            ud.pop('expecting_receipt_for', None)
            await update.message.reply_text('✅ Chek qabul qilindi, buyurtma yetkazildi va yozildi. Rahmat!')
            return
    except Exception as e:
        log.warning(f"Receipt photo handling error: {e}")
    # Courier OTP flow: if courier was asked to provide OTP for an order
    if uid in couriers and ud.get('expecting_otp_for'):
        try:
            order_num = int(ud.get('expecting_otp_for'))
            order = find_order(order_num)
            if not order:
                await update.message.reply_text('Buyurtma topilmadi.'); ud.pop('expecting_otp_for', None); return
            # compare OTP
            if text == str(order.get('otp')):
                # OTP correct
                # If payment was cash -> finalize immediately
                if order.get('payment') == 'cash':
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
                # If payment was card -> ask courier to upload receipt photo
                elif order.get('payment') == 'card':
                    ud.pop('expecting_otp_for', None)
                    context.user_data['expecting_receipt_for'] = order_num
                    try:
                        await context.bot.send_message(chat_id=uid, text=f"✅ OTP tasdiqlandi. Endi iltimos mijozdan chekni (screenshot yoki bank ilovasidagi kvitansiya) so'rang va shu chatga rasm sifatida yuboring. Cheksiz buyurtma tasdiqlanmaydi.")
                    except Exception:
                        pass
                    await update.message.reply_text('Iltimos, chek rasmini yuboring...')
                    return
                else:
                    # fallback finalize
                    order['status'] = 'Yetkazib berildi'
                    persist_orders()
                    try: await context.bot.send_message(chat_id=order['user_id'], text=f"✅ Sizning #{order_num} buyurtmangiz yetkazib berildi.")
                    except Exception as e: log.warning(f"Foydalanuvchiga yetkazildi xabarida xato: {e}")
                    try: await context.bot.edit_message_text(chat_id=order['courier_msg']['chat_id'], message_id=order['courier_msg']['message_id'], text="✅ Yetkazildi")
                    except Exception: pass
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
        # If user pressed exit while viewing a user session (history/menu/etc.), clear session messages
        if text == "🔙 Chiqish" and (ud.get('history_messages') or ud.get('menu_messages') or ud.get('suggest_prompt') or ud.get('last_prompt_msg')):
            try:
                try:
                    await update.message.delete()
                except Exception:
                    pass
                # Use centralized helper to clear recorded user session messages
                try:
                    prompt_mid = await clear_user_session(uid, context, ud)
                except Exception:
                    prompt_mid = None

                # removed brittle range-based deletion — rely on recorded messages only

                # restore main user reply keyboard
                user_kb = ReplyKeyboardMarkup([
                    [KeyboardButton("🍔 Menyu"), KeyboardButton("Taklif va shikoyatlar")],
                    [KeyboardButton("🧾 Buyurtmalar tarixi")]
                ], resize_keyboard=True, one_time_keyboard=False)
                try:
                    sent_w = await context.bot.send_message(chat_id=uid, text="🍔 Fast Food botiga xush kelibsiz! Quyidagi tugmalardan foydalaning:", reply_markup=user_kb)
                    ud['welcome_msg'] = {'chat_id': sent_w.chat_id, 'message_id': sent_w.message_id, 'text': "🍔 Fast Food botiga xush kelibsiz! Quyidagi tugmalardan foydalaning:"}
                except Exception:
                    pass
            except Exception:
                pass
            return
    if uid in admins:
        # Support reply-keyboard exit button from admin orders view
        # If admin is composing a reply to a suggestion, forward their message to the target user
        if ud.get('want_reply_to'):
            try:
                info = ud.pop('want_reply_to', None)
                if info:
                    target = info.get('target_user')
                    chan_msg_id = info.get('channel_msg_id')
                    # Forward whatever the admin just sent to the target user (this includes text, media, etc.)
                    try:
                        # copy the admin's message to the user so it appears sent by the bot (anonymous)
                        try:
                            await context.bot.copy_message(chat_id=target, from_chat_id=uid, message_id=update.message.message_id)
                        except Exception:
                            # fallback: if copy_message fails (older clients), send text or media manually
                            if update.message.text:
                                await context.bot.send_message(chat_id=target, text=update.message.text)
                            elif update.message.photo:
                                # send largest photo
                                photo = update.message.photo[-1].file_id
                                await context.bot.send_photo(chat_id=target, photo=photo, caption=update.message.caption or '')
                            elif update.message.sticker:
                                await context.bot.send_sticker(chat_id=target, sticker=update.message.sticker.file_id)
                            elif update.message.document:
                                await context.bot.send_document(chat_id=target, document=update.message.document.file_id, caption=update.message.caption or '')
                            else:
                                # as last resort, send text representation
                                txt = update.message.text or '[media]'
                                await context.bot.send_message(chat_id=target, text=txt)
                        # send a short confirmation to admin (will be deleted shortly)
                        try:
                            resp = await context.bot.send_message(chat_id=uid, text='✅ Javob mijozga yuborildi.')
                            async def _del_later(cid, mid, delay=6):
                                try:
                                    await asyncio.sleep(delay)
                                    await context.bot.delete_message(chat_id=cid, message_id=mid)
                                except Exception:
                                    pass
                            try:
                                asyncio.create_task(_del_later(resp.chat_id, resp.message_id, 6))
                            except Exception:
                                pass
                        except Exception:
                            pass
                    except Exception:
                        # fallback: send as text if forward failed
                        try:
                            if update.message.text:
                                await context.bot.send_message(chat_id=target, text=update.message.text)
                                await update.message.reply_text('✅ Javob mijozga yuborildi.')
                            else:
                                await update.message.reply_text('❌ Xabar yuborilmadi. Iltimos, matn yoki media yuboring va qayta urinib ko‘ring.')
                        except Exception:
                            pass
                    # Post admin's reply anonymously as a reply to the original suggestion in the suggestions channel,
                    # and also clean up admin-side forwarded copies and prompts.
                    try:
                        if chan_msg_id:
                            try:
                                # copy admin's message into the suggestions channel as a reply_to the original message
                                try:
                                    await context.bot.copy_message(chat_id=SUGGESTIONS_CHANNEL_ID, from_chat_id=uid, message_id=update.message.message_id, reply_to_message_id=chan_msg_id)
                                except Exception:
                                    # fallback: send text or caption as bot reply
                                    if update.message.text:
                                        await context.bot.send_message(chat_id=SUGGESTIONS_CHANNEL_ID, text=update.message.text, reply_to_message_id=chan_msg_id)
                                    elif update.message.photo:
                                        photo = update.message.photo[-1].file_id
                                        await context.bot.send_photo(chat_id=SUGGESTIONS_CHANNEL_ID, photo=photo, caption=update.message.caption or '', reply_to_message_id=chan_msg_id)
                                    else:
                                        await context.bot.send_message(chat_id=SUGGESTIONS_CHANNEL_ID, text='✅ Javob berildi.', reply_to_message_id=chan_msg_id)
                            except Exception:
                                # ignore failures posting into channel
                                pass
                    except Exception:
                        pass
                    try:
                        # remove admin's own sent message to avoid clutter
                        try:
                            await update.message.delete()
                        except Exception:
                            pass
                        # delete any recorded prompt/forward copies we stored in admin_orders_sessions
                        try:
                            sent_prompts = admin_orders_sessions.pop(uid, [])
                            try:
                                await _safe_delete_session_messages(context, uid, sent_prompts)
                            except Exception:
                                pass
                        except Exception:
                            pass
                    except Exception:
                        pass
            except Exception as e:
                log.warning(f"Admin reply error: {e}")
            return
        if text == "🔙 Chiqish":
            # delete the user's own reply message (the '🔙 Chiqish' text) to avoid leaving it in chat
            try:
                await update.message.delete()
            except Exception:
                pass
            # central cleanup of admin session prompts/messages and transient state
            try:
                await clear_admin_session(uid, context, ud)
            except Exception:
                pass
                # Best-effort: also remove any stored admin_orders_sessions entries (redundant safe-guard)
                try:
                    sent_msgs = admin_orders_sessions.pop(uid, [])
                    try:
                        await _safe_delete_session_messages(context, uid, sent_msgs)
                    except Exception:
                        pass
                except Exception:
                    pass
            # restore admin panel
            try:
                await context.bot.send_message(chat_id=uid, text="🔑 Admin panelga xush kelibsiz!", reply_markup=admin_panel_kb())
            except Exception:
                pass
            return
        if ud.get("want_broadcast"):
            # Forward the exact admin message to all users so media + captions are preserved
            ud.pop("want_broadcast", None)
            sent, failed = 0, 0
            from_chat_id = update.message.chat_id
            msg_id = update.message.message_id
            for user_id in list(users):
                # don't forward the broadcast back to the admin who sent it
                if user_id == uid:
                    continue
                try:
                    await context.bot.forward_message(chat_id=user_id, from_chat_id=from_chat_id, message_id=msg_id)
                    sent += 1
                except Exception as e:
                    failed += 1
                    log.warning(f"Broadcastda xato ({user_id}): {e}")
            try:
                await update.message.reply_text(f"✅ Xabar yuborildi.\nMuvaffaqiyatli: {sent}\nXatolik: {failed}", reply_markup=admin_panel_kb())
            except Exception:
                pass
            # cleanup any admin prompt messages (e.g., the 'enter message' prompt)
            try:
                sent_prompts = admin_orders_sessions.pop(uid, [])
                try:
                    await _safe_delete_session_messages(context, uid, sent_prompts)
                except Exception:
                    pass
            except Exception:
                pass
            return
        if ud.get("want_add_admin"):
            ud.pop("want_add_admin", None)
            try:
                admins.add(int(text))
                try:
                    await update.message.delete()
                except Exception:
                    pass
                try:
                    await context.bot.send_message(chat_id=uid, text=f"✅ {text} admin sifatida qo‘shildi.", reply_markup=admin_panel_kb())
                except Exception:
                    pass
                # cleanup prompt message (only delete messages that were sent into admin's private chat)
                try:
                    sent_prompts = admin_orders_sessions.pop(uid, [])
                    try:
                        await _safe_delete_session_messages(context, uid, sent_prompts)
                    except Exception:
                        pass
                except Exception:
                    pass
                try:
                    sa_text = (
                        f"[ADMIN QO'SHILDI] {datetime.now(timezone.utc).isoformat()}\n"
                        f"Qo'shgan admin: {uid} ({update.effective_user.full_name})\n"
                        f"Yangi admin: {text}"
                    )
                    await report_superadmin(context.bot, sa_text)
                except Exception as e:
                    log.warning(f"Superadminga admin add hisobotini yuborishda xato: {e}")
            except ValueError:
                resp = None
                try:
                    resp = await update.message.reply_text("❌ Xato ID.", reply_markup=admin_panel_kb())
                except Exception:
                    pass
                # delete the admin's input message to avoid clutter
                try:
                    await update.message.delete()
                except Exception:
                    pass
                # cleanup prompt messages (only delete messages that were sent into admin's private chat)
                try:
                    sent_prompts = admin_orders_sessions.pop(uid, [])
                    try:
                        await _safe_delete_session_messages(context, uid, sent_prompts)
                    except Exception:
                        pass
                except Exception:
                    pass
                # schedule deletion of the bot's error reply after a short delay
                if resp:
                    async def _del_later(cid, mid, delay=6):
                        try:
                            await asyncio.sleep(delay)
                            await context.bot.delete_message(chat_id=cid, message_id=mid)
                        except Exception:
                            pass
                    try:
                        asyncio.create_task(_del_later(resp.chat_id, resp.message_id, 6))
                    except Exception:
                        pass
                return
        if ud.get("want_remove_admin"):
            ud.pop("want_remove_admin", None)
            try:
                rem_id = int(text)
                if rem_id == ADMIN_ID:
                    resp = None
                    try:
                        resp = await update.message.reply_text("⚠️ Asosiy adminni o‘chira olmaysiz.", reply_markup=admin_panel_kb())
                    except Exception:
                        pass
                    # delete admin's own input
                    try:
                        await update.message.delete()
                    except Exception:
                        pass
                    # cleanup prompt
                    try:
                        sent_prompts = admin_orders_sessions.pop(uid, [])
                        try:
                            await _safe_delete_session_messages(context, uid, sent_prompts)
                        except Exception:
                            pass
                    except Exception:
                        pass
                    # schedule deletion of the info reply
                    if resp:
                        async def _del_later(cid, mid, delay=6):
                            try:
                                await asyncio.sleep(delay)
                                await context.bot.delete_message(chat_id=cid, message_id=mid)
                            except Exception:
                                pass
                        try:
                            asyncio.create_task(_del_later(resp.chat_id, resp.message_id, 6))
                        except Exception:
                            pass
                elif rem_id in admins:
                    # remove admin and delete admin's input to avoid clutter
                    try:
                        await update.message.delete()
                    except Exception:
                        pass
                    admins.discard(rem_id)
                    try:
                        await update.message.reply_text(f"✅ {rem_id} adminlikdan olib tashlandi.", reply_markup=admin_panel_kb())
                    except Exception:
                        pass
                    # cleanup prompt
                    try:
                        sent_prompts = admin_orders_sessions.pop(uid, [])
                        try:
                            await _safe_delete_session_messages(context, uid, sent_prompts)
                        except Exception:
                            pass
                    except Exception:
                        pass
                    try:
                        sa_text = (
                            f"[ADMIN O'CHIRILDI] {datetime.now(timezone.utc).isoformat()}\n"
                            f"O'chirgan admin: {uid} ({update.effective_user.full_name})\n"
                            f"O'chirilgan admin: {rem_id}"
                        )
                        await report_superadmin(context.bot, sa_text)
                    except Exception as e:
                        log.warning(f"Superadminga admin remove hisobotini yuborishda xato: {e}")
                else:
                    resp = None
                    try:
                        resp = await update.message.reply_text("ℹ️ Bu ID adminlar ro‘yxatida yo‘q.", reply_markup=admin_panel_kb())
                    except Exception:
                        pass
                    try:
                        await update.message.delete()
                    except Exception:
                        pass
                    # cleanup prompt
                    try:
                        sent_prompts = admin_orders_sessions.pop(uid, [])
                        try:
                            await _safe_delete_session_messages(context, uid, sent_prompts)
                        except Exception:
                            pass
                    except Exception:
                        pass
                    if resp:
                        async def _del_later(cid, mid, delay=6):
                            try:
                                await asyncio.sleep(delay)
                                await context.bot.delete_message(chat_id=cid, message_id=mid)
                            except Exception:
                                pass
                        try:
                            asyncio.create_task(_del_later(resp.chat_id, resp.message_id, 6))
                        except Exception:
                            pass
            except ValueError:
                resp = None
                try:
                    resp = await update.message.reply_text("❌ Xato ID.", reply_markup=admin_panel_kb())
                except Exception:
                    pass
                try:
                    await update.message.delete()
                except Exception:
                    pass
                try:
                    sent_prompts = admin_orders_sessions.pop(uid, [])
                    try:
                        await _safe_delete_session_messages(context, uid, sent_prompts)
                    except Exception:
                        pass
                except Exception:
                    pass
                if resp:
                    async def _del_later(cid, mid, delay=6):
                        try:
                            await asyncio.sleep(delay)
                            await context.bot.delete_message(chat_id=cid, message_id=mid)
                        except Exception:
                            pass
                    try:
                        asyncio.create_task(_del_later(resp.chat_id, resp.message_id, 6))
                    except Exception:
                        pass
                return
        if ud.get("want_add_courier"):
            ud.pop("want_add_courier", None)
            try:
                cid = int(text)
                # delete admin input to avoid clutter
                try:
                    await update.message.delete()
                except Exception:
                    pass
                couriers.add(cid); persist_couriers()
                try:
                    await context.bot.send_message(chat_id=uid, text=f"✅ {cid} yetkazib beruvchi sifatida qo‘shildi.", reply_markup=admin_panel_kb())
                except Exception:
                    pass
                # cleanup prompt (only delete messages that were sent into admin's private chat)
                try:
                    sent_prompts = admin_orders_sessions.pop(uid, [])
                    try:
                        await _safe_delete_session_messages(context, uid, sent_prompts)
                    except Exception:
                        pass
                except Exception:
                    pass
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
            except ValueError:
                resp = None
                try:
                    resp = await update.message.reply_text("❌ Xato ID.", reply_markup=admin_panel_kb())
                except Exception:
                    pass
                try:
                    await update.message.delete()
                except Exception:
                    pass
                try:
                    sent_prompts = admin_orders_sessions.pop(uid, [])
                    try:
                        await _safe_delete_session_messages(context, uid, sent_prompts)
                    except Exception:
                        pass
                except Exception:
                    pass
                if resp:
                    async def _del_later(cid, mid, delay=6):
                        try:
                            await asyncio.sleep(delay)
                            await context.bot.delete_message(chat_id=cid, message_id=mid)
                        except Exception:
                            pass
                    try:
                        asyncio.create_task(_del_later(resp.chat_id, resp.message_id, 6))
                    except Exception:
                        pass
                return
        if ud.get("want_remove_courier"):
            ud.pop("want_remove_courier", None)
            try:
                rcid = int(text)
                if rcid in couriers:
                    try:
                        await update.message.delete()
                    except Exception:
                        pass
                    couriers.discard(rcid); persist_couriers()
                    try:
                        await context.bot.send_message(chat_id=uid, text=f"✅ {rcid} yetkazib beruvchi ro'yxatidan olib tashlandi.", reply_markup=admin_panel_kb())
                    except Exception:
                        pass
                    # cleanup prompt (only delete messages that were sent into admin's private chat)
                    try:
                        sent_prompts = admin_orders_sessions.pop(uid, [])
                        try:
                            await _safe_delete_session_messages(context, uid, sent_prompts)
                        except Exception:
                            pass
                    except Exception:
                        pass
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
                    resp = None
                    try:
                        resp = await update.message.reply_text("ℹ️ Bu ID yetkazib beruvchilar ro‘yxatida yo‘q.", reply_markup=admin_panel_kb())
                    except Exception:
                        pass
                    try:
                        await update.message.delete()
                    except Exception:
                        pass
                    # cleanup prompt
                    try:
                        sent_prompts = admin_orders_sessions.pop(uid, [])
                        try:
                            await _safe_delete_session_messages(context, uid, sent_prompts)
                        except Exception:
                            pass
                    except Exception:
                        pass
                    if resp:
                        async def _del_later(cid, mid, delay=6):
                            try:
                                await asyncio.sleep(delay)
                                await context.bot.delete_message(chat_id=cid, message_id=mid)
                            except Exception:
                                pass
                        try:
                            asyncio.create_task(_del_later(resp.chat_id, resp.message_id, 6))
                        except Exception:
                            pass
            except ValueError:
                resp = None
                try:
                    resp = await update.message.reply_text("❌ Xato ID.", reply_markup=admin_panel_kb())
                except Exception:
                    pass
                try:
                    await update.message.delete()
                except Exception:
                    pass
                try:
                    sent_prompts = admin_orders_sessions.pop(uid, [])
                    try:
                        await _safe_delete_session_messages(context, uid, sent_prompts)
                    except Exception:
                        pass
                except Exception:
                    pass
                if resp:
                    async def _del_later(cid, mid, delay=6):
                        try:
                            await asyncio.sleep(delay)
                            await context.bot.delete_message(chat_id=cid, message_id=mid)
                        except Exception:
                            pass
                    try:
                        asyncio.create_task(_del_later(resp.chat_id, resp.message_id, 6))
                    except Exception:
                        pass
                return
        # Admin: menu-edit text flows
        if ud.get('amenu_adding_category'):
            ud.pop('amenu_adding_category', None)
            cat_name = text.strip()
            if not cat_name:
                # cleanup admin input and prompts
                try:
                    await update.message.delete()
                except Exception:
                    pass
                try:
                    lp = ud.pop('amenu_last_prompt', None)
                    if lp:
                        try:
                            await context.bot.delete_message(chat_id=lp.get('chat_id'), message_id=lp.get('message_id'))
                        except Exception:
                            pass
                except Exception:
                    pass
                try:
                    sent = admin_orders_sessions.pop(uid, [])
                    try:
                        await _safe_delete_session_messages(context, uid, sent)
                    except Exception:
                        pass
                except Exception:
                    pass
                await context.bot.send_message(chat_id=uid, text="❌ Bo'sh nom qabul qilinmaydi.", reply_markup=admin_panel_kb())
                return
            if cat_name in menu_data:
                try:
                    await update.message.delete()
                except Exception:
                    pass
                try:
                    lp = ud.pop('amenu_last_prompt', None)
                    if lp:
                        try:
                            await context.bot.delete_message(chat_id=lp.get('chat_id'), message_id=lp.get('message_id'))
                        except Exception:
                            pass
                except Exception:
                    pass
                try:
                    sent = admin_orders_sessions.pop(uid, [])
                    try:
                        await _safe_delete_session_messages(context, uid, sent)
                    except Exception:
                        pass
                except Exception:
                    pass
                await context.bot.send_message(chat_id=uid, text="ℹ️ Bunday kategoriya allaqachon mavjud.", reply_markup=admin_panel_kb())
                return
            menu_data[cat_name] = {}
            persist_menu()
            # try to delete the admin's input to avoid clutter
            try:
                await update.message.delete()
            except Exception:
                pass
            # cleanup prompts/sessions and return updated menu view
            try:
                lp = ud.pop('amenu_last_prompt', None)
                if lp:
                    try:
                        await context.bot.delete_message(chat_id=lp.get('chat_id'), message_id=lp.get('message_id'))
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                sent = admin_orders_sessions.pop(uid, [])
                try:
                    await _safe_delete_session_messages(context, uid, sent)
                except Exception:
                    pass
            except Exception:
                pass
            # send updated categories list (return to admin edit menu)
            try:
                rows = [[InlineKeyboardButton(cat, callback_data=f"amenu_cat_{cat}")] for cat in menu_data.keys()]
                rows.append([InlineKeyboardButton("➕ Kategoriya qo'shish", callback_data="amenu_add_category")])
                rows.append([InlineKeyboardButton('◀️ Bekor', callback_data='admin_panel')])
                await context.bot.send_message(chat_id=uid, text='Menyuni tahrirlash — kategoriya tanlang:', reply_markup=InlineKeyboardMarkup(rows))
            except Exception:
                # fallback: show admin panel
                try:
                    await context.bot.send_message(chat_id=uid, text=f"✅ '{cat_name}' nomli kategoriya qo'shildi.", reply_markup=admin_panel_kb())
                except Exception:
                    pass
            return
        # Admin: step-by-step product creation flow
        if ud.get('amenu_add_product_step'):
            step = ud.get('amenu_add_product_step')
            cat = ud.get('amenu_add_product_cat')
            # Helper: delete last bot prompt if present
            async def _cleanup_last_prompt():
                lp = ud.pop('amenu_last_prompt', None)
                if lp:
                    try:
                        await context.bot.delete_message(chat_id=lp['chat_id'], message_id=lp['message_id'])
                    except Exception:
                        pass

            # If admin sent a photo (for photo step)
            if step == 'photo' and update.message.photo:
                # save photo file_id
                file_id = update.message.photo[-1].file_id
                ud['amenu_new_photo'] = file_id
                # cleanup previous messages
                try:
                    await update.message.delete()
                except Exception:
                    pass
                await _cleanup_last_prompt()
                # finalize product
                name = ud.pop('amenu_new_name', None)
                price = ud.pop('amenu_new_price', None)
                desc = ud.pop('amenu_new_desc', '')
                photo = ud.pop('amenu_new_photo', None)
                ud.pop('amenu_add_product_step', None); ud.pop('amenu_add_product_cat', None)
                if not name or price is None:
                    await context.bot.send_message(chat_id=uid, text='❌ Mahsulot nomi yoki narxi topilmadi. Qayta urinib ko\'ring.', reply_markup=admin_panel_kb())
                    return
                if cat not in menu_data: menu_data[cat] = {}
                entry = {'price': price, 'desc': desc, 'available': True}
                if photo: entry['photo'] = photo
                menu_data[cat][name] = entry
                persist_menu()
                # send updated category view
                try:
                    rows = [[InlineKeyboardButton(f"{n} — {i.get('price',0)} so'm", callback_data=f"amenu_prod_{cat}|{n}")] for n,i in menu_data.get(cat,{}).items()]
                    rows.append([InlineKeyboardButton('◀️ Orqaga', callback_data='admin_edit_menu'), InlineKeyboardButton('🔙 Admin panel', callback_data='admin_panel')])
                    await context.bot.send_message(chat_id=uid, text=f"{cat} — mahsulotlarni tanlang:", reply_markup=InlineKeyboardMarkup(rows))
                    # cleanup any stored admin session prompts
                    try:
                        sent = admin_orders_sessions.pop(uid, [])
                        try:
                            await _safe_delete_session_messages(context, uid, sent)
                        except Exception:
                            pass
                    except Exception:
                        pass
                except Exception:
                    pass
                try:
                    refresh_category_views(context, cat)
                except Exception:
                    pass
                return

            # Otherwise handle text steps
            if step == 'name' and text:
                ud['amenu_new_name'] = text.strip()
                # delete admin's text to avoid clutter
                try:
                    await update.message.delete()
                except Exception:
                    pass
                # delete last bot prompt
                await (lambda: _cleanup_last_prompt())()
                # ask for price
                try:
                    sent = await context.bot.send_message(chat_id=uid, text='Iltimos, mahsulot narxini kiriting (faqat raqam):')
                    ud['amenu_last_prompt'] = {'chat_id': sent.chat_id, 'message_id': sent.message_id}
                except Exception:
                    pass
                ud['amenu_add_product_step'] = 'price'
                return

            if step == 'price' and text:
                try:
                    price = int(text.strip())
                except Exception:
                    await update.message.reply_text('Narx butun son bo\'lishi kerak. Iltimos faqat raqam yuboring.')
                    return
                ud['amenu_new_price'] = price
                try:
                    await update.message.delete()
                except Exception:
                    pass
                await (lambda: _cleanup_last_prompt())()
                # ask for description
                try:
                    sent = await context.bot.send_message(chat_id=uid, text='Mahsulot tavsifini yuboring:')
                    ud['amenu_last_prompt'] = {'chat_id': sent.chat_id, 'message_id': sent.message_id}
                except Exception:
                    pass
                ud['amenu_add_product_step'] = 'desc'
                return

            if step == 'desc' and text is not None:
                ud['amenu_new_desc'] = text.strip()
                try:
                    await update.message.delete()
                except Exception:
                    pass
                await (lambda: _cleanup_last_prompt())()
                # ask for photo (optional)
                try:
                    sent = await context.bot.send_message(chat_id=uid, text="Iltimos, mahsulot rasmini yuboring (yubormasangiz 'skip' deb yozing):")
                    ud['amenu_last_prompt'] = {'chat_id': sent.chat_id, 'message_id': sent.message_id}
                except Exception:
                    pass
                ud['amenu_add_product_step'] = 'photo'
                return

            # allow skipping photo by sending 'skip'
            if step == 'photo' and text.lower() in ('skip','/skip'):
                # finalize without photo
                await (lambda: _cleanup_last_prompt())()
                try:
                    await update.message.delete()
                except Exception:
                    pass
                name = ud.pop('amenu_new_name', None)
                price = ud.pop('amenu_new_price', None)
                desc = ud.pop('amenu_new_desc', '')
                ud.pop('amenu_add_product_step', None); ud.pop('amenu_add_product_cat', None)
                if not name or price is None:
                    await context.bot.send_message(chat_id=uid, text='❌ Ma\'lumot yetarli emas, qayta urinib ko\'ring.', reply_markup=admin_panel_kb())
                    return
                if cat not in menu_data: menu_data[cat] = {}
                menu_data[cat][name] = {'price': price, 'desc': desc, 'available': True}
                persist_menu()
                try:
                    rows = [[InlineKeyboardButton(f"{n} — {i.get('price',0)} so'm", callback_data=f"amenu_prod_{cat}|{n}")] for n,i in menu_data.get(cat,{}).items()]
                    rows.append([InlineKeyboardButton('◀️ Orqaga', callback_data='admin_edit_menu'), InlineKeyboardButton('🔙 Admin panel', callback_data='admin_panel')])
                    await context.bot.send_message(chat_id=uid, text=f"{cat} — mahsulotlarni tanlang:", reply_markup=InlineKeyboardMarkup(rows))
                    # cleanup any stored admin session prompts
                    try:
                        sent = admin_orders_sessions.pop(uid, [])
                        try:
                            await _safe_delete_session_messages(context, uid, sent)
                        except Exception:
                            pass
                    except Exception:
                        pass
                except Exception:
                    pass
                return
        if ud.get('amenu_edit_price'):
            cat_prod = ud.pop('amenu_edit_price', None)
            if not cat_prod:
                await update.message.reply_text('Noto\'g\'ri holat.'); return
            cat, prod = cat_prod
            try:
                new_price = int(text.strip())
            except Exception:
                await update.message.reply_text('Narx butun son bo\'lishi kerak.'); return
            if cat in menu_data and prod in menu_data[cat]:
                menu_data[cat][prod]['price'] = new_price
                persist_menu()
                try:
                    refresh_category_views(context, cat)
                except Exception:
                    pass
                # delete admin input and any stored prompts/sessions to avoid leftovers
                try:
                    await update.message.delete()
                except Exception:
                    pass
                try:
                    lp = ud.pop('amenu_last_prompt', None)
                    if lp:
                        try:
                            await context.bot.delete_message(chat_id=lp.get('chat_id'), message_id=lp.get('message_id'))
                        except Exception:
                            pass
                except Exception:
                    pass
                try:
                    sent = admin_orders_sessions.pop(uid, [])
                    try:
                        await _safe_delete_session_messages(context, uid, sent)
                    except Exception:
                        pass
                except Exception:
                    pass
                await context.bot.send_message(chat_id=uid, text=f"✅ '{prod}' narxi yangilandi: {new_price} so'm", reply_markup=admin_panel_kb())
            else:
                try:
                    await update.message.delete()
                except Exception:
                    pass
                try:
                    lp = ud.pop('amenu_last_prompt', None)
                    if lp:
                        try:
                            await context.bot.delete_message(chat_id=lp.get('chat_id'), message_id=lp.get('message_id'))
                        except Exception:
                            pass
                except Exception:
                    pass
                try:
                    sent = admin_orders_sessions.pop(uid, [])
                    try:
                        await _safe_delete_session_messages(context, uid, sent)
                    except Exception:
                        pass
                except Exception:
                    pass
                await context.bot.send_message(chat_id=uid, text='Mahsulot topilmadi', reply_markup=admin_panel_kb())
            return
        if ud.get('amenu_edit_desc'):
            cat_prod = ud.pop('amenu_edit_desc', None)
            if not cat_prod:
                await update.message.reply_text('Noto\'g\'ri holat.'); return
            cat, prod = cat_prod
            new_desc = text.strip()
            if cat in menu_data and prod in menu_data[cat]:
                menu_data[cat][prod]['desc'] = new_desc
                persist_menu()
                try:
                    refresh_category_views(context, cat)
                except Exception:
                    pass
                # cleanup admin input and prompts
                try:
                    await update.message.delete()
                except Exception:
                    pass
                try:
                    lp = ud.pop('amenu_last_prompt', None)
                    if lp:
                        try:
                            await context.bot.delete_message(chat_id=lp.get('chat_id'), message_id=lp.get('message_id'))
                        except Exception:
                            pass
                except Exception:
                    pass
                try:
                    sent = admin_orders_sessions.pop(uid, [])
                    try:
                        await _safe_delete_session_messages(context, uid, sent)
                    except Exception:
                        pass
                except Exception:
                    pass
                await context.bot.send_message(chat_id=uid, text=f"✅ '{prod}' tavsifi yangilandi.", reply_markup=admin_panel_kb())
            else:
                try:
                    await update.message.delete()
                except Exception:
                    pass
                try:
                    lp = ud.pop('amenu_last_prompt', None)
                    if lp:
                        try:
                            await context.bot.delete_message(chat_id=lp.get('chat_id'), message_id=lp.get('message_id'))
                        except Exception:
                            pass
                except Exception:
                    pass
                try:
                    sent = admin_orders_sessions.pop(uid, [])
                    try:
                        await _safe_delete_session_messages(context, uid, sent)
                    except Exception:
                        pass
                except Exception:
                    pass
                await context.bot.send_message(chat_id=uid, text='Mahsulot topilmadi', reply_markup=admin_panel_kb())
            return
        # Admin: handle photo upload for editing product image
        if ud.get('amenu_edit_photo'):
            # expecting a photo message from admin
            if update.message.photo:
                cat, prod = ud.pop('amenu_edit_photo', (None, None))
                # take highest-resolution photo file_id
                file_id = update.message.photo[-1].file_id
                # cleanup admin message and last prompt
                try:
                    await update.message.delete()
                except Exception:
                    pass
                try:
                    lp = ud.pop('amenu_last_prompt', None)
                    if lp:
                        try:
                            await context.bot.delete_message(chat_id=lp['chat_id'], message_id=lp['message_id'])
                        except Exception:
                            pass
                except Exception:
                    pass
                if not cat or not prod:
                    try:
                        await context.bot.send_message(chat_id=uid, text='Noto\'g\'ri holat — qayta urinib ko\'ring.', reply_markup=admin_panel_kb())
                    except Exception:
                        pass
                    return
                # save to menu_data
                try:
                    if cat not in menu_data:
                        menu_data[cat] = {}
                    menu_data[cat].setdefault(prod, {})['photo'] = file_id
                    persist_menu()
                    try:
                        refresh_category_views(context, cat)
                    except Exception:
                        pass
                    try:
                        # cleanup any stored admin session prompts
                        try:
                            sent = admin_orders_sessions.pop(uid, [])
                            try:
                                await _safe_delete_session_messages(context, uid, sent)
                            except Exception:
                                pass
                        except Exception:
                            pass
                        await context.bot.send_message(chat_id=uid, text=f"✅ '{prod}' uchun yangi rasm saqlandi.", reply_markup=admin_panel_kb())
                    except Exception:
                        pass
                except Exception as e:
                    log.warning(f"Rasmni saqlashda xato: {e}")
                return
            else:
                # if admin sent non-photo, prompt again
                await update.message.reply_text('Iltimos, faqat rasm yuboring yoki /cancel bilan bekor qiling.')
                return
    # Admin adding product via super-admin add flow
    if uid in admins and ud.get('sa_adding_order'):
        try:
            order_num = int(ud.pop('sa_adding_order'))
        except Exception:
            await update.message.reply_text('Noto\'g\'ri buyruq yoki vaqt tugadi.'); return
        order = find_order(order_num)
        if not order:
            await update.message.reply_text('Buyurtma topilmadi.'); return
        # expect text like: Name | qty
        if '|' not in text:
            await update.message.reply_text('Format: Nomi | miqdor (masalan: Lavash | 1)'); return
        name_part, qty_part = text.split('|', 1)
        name = name_part.strip()
        try: qty = int(qty_part.strip())
        except Exception:
            await update.message.reply_text('Miqdor butun son bo\'lishi kerak.'); return
        items = list(order.get('items', []))
        items.append(f"{name} x{qty}")
        # recompute total
        total = 0
        for it in items:
            if ' x' in it:
                nm, q = it.rsplit(' x', 1); q = int(q)
            else:
                nm = it; q = 1
            total += product_price(nm) * q
        order['items'] = items
        order['total'] = total
        persist_orders()
        # update superadmin message if exists
        sam = order.get('superadmin_msg')
        if sam:
            try:
                await context.bot.edit_message_text(chat_id=sam['chat_id'], message_id=sam['message_id'], text=build_superadmin_order_text(order), reply_markup=build_superadmin_kb(order), parse_mode='HTML')
            except Exception:
                pass
        await update.message.reply_text('✅ Mahsulot qo\'shildi va super-admin oynasi yangilandi.')
        return
    # (previous simple text-edit flow removed; admin uses item-level editor now)

    # --- Quick reply handlers for regular users (reply-keyboard buttons) ---
    # If user is in profile setup (first-start questionnaire), handle that first
    if uid not in admins and ud.get('profile_setup') == 'name':
        # Capture the user's provided full name, save to users_info and finish onboarding
        name = text.strip()
        if not name:
            try:
                await update.message.reply_text("Iltimos, ismingizni yozing:")
            except Exception:
                pass
            return
        # persist name in users_info (phone will be collected during checkout)
        try:
            users_info[uid] = {'name': name, 'phone': '', 'username': update.effective_user.username or ''}
            persist_users_info()
        except Exception:
            pass
        # cleanup and show main keyboard
        try:
            await update.message.delete()
        except Exception:
            pass
        ud.pop('profile_setup', None)
        try:
            user_kb = ReplyKeyboardMarkup([
                [KeyboardButton("🍔 Menyu"), KeyboardButton("Taklif va shikoyatlar")],
                [KeyboardButton("🧾 Buyurtmalar tarixi")]
            ], resize_keyboard=True, one_time_keyboard=False)
            await context.bot.send_message(chat_id=uid, text=f"✅ Profilingiz saqlandi. Salom, {name}!", reply_markup=user_kb)
        except Exception:
            pass
        return

    if uid not in admins:
        # If the user pressed the exit button while viewing menu, restore main keyboard
        if text in ('🔙 Chiqish', 'Bekor qilish', '❌ Bekor qilish'):
            try:
                await update.message.delete()
            except Exception:
                pass
            # delete stored menu messages (exit button, category message, remove message)
            try:
                menu_msgs = ud.pop('menu_messages', None)
                if menu_msgs:
                    for m in menu_msgs:
                        try:
                            await context.bot.delete_message(chat_id=m.get('chat_id'), message_id=m.get('message_id'))
                        except Exception:
                            pass
            except Exception:
                pass
            # delete stored history messages if present (messages shown by 'Buyurtmalar tarixi')
            try:
                history_msgs = ud.pop('history_messages', None)
                if history_msgs:
                    for m in history_msgs:
                        try:
                            await context.bot.delete_message(chat_id=m.get('chat_id'), message_id=m.get('message_id'))
                        except Exception:
                            pass
            except Exception:
                pass
            # If the user was in the suggestions/complaints flow, cancel it and delete any previously sent suggestion messages and the suggest prompt
            try:
                # delete suggestion messages in suggestions channel that we stored earlier
                try:
                    sent_sugs = ud.pop('sent_suggestions', [])
                    for m in sent_sugs:
                        try:
                            await context.bot.delete_message(chat_id=m.get('chat_id'), message_id=m.get('message_id'))
                        except Exception:
                            pass
                except Exception:
                    pass
                # delete the bot's suggest prompt message (if we stored it)
                try:
                    sp = ud.pop('suggest_prompt', None)
                    if sp:
                        try:
                            await context.bot.delete_message(chat_id=sp.get('chat_id'), message_id=sp.get('message_id'))
                        except Exception:
                            pass
                except Exception:
                    pass
                ud.pop('contact_admin', None)
            except Exception:
                pass
            try:
                user_kb = ReplyKeyboardMarkup([
                    [KeyboardButton("🍔 Menyu"), KeyboardButton("Taklif va shikoyatlar")],
                    [KeyboardButton("🧾 Buyurtmalar tarixi")]
                ], resize_keyboard=True, one_time_keyboard=False)
                try:
                    sent_w = await context.bot.send_message(chat_id=uid, text="🍔 Fast Food botiga xush kelibsiz! Quyidagi tugmalardan foydalaning:", reply_markup=user_kb)
                    # store welcome message id so it can be deleted next time menu is opened
                    try:
                        ud['welcome_msg'] = {'chat_id': sent_w.chat_id, 'message_id': sent_w.message_id, 'text': "🍔 Fast Food botiga xush kelibsiz! Quyidagi tugmalardan foydalaning:"}
                    except Exception:
                        pass
                except Exception:
                    pass
            except Exception:
                pass
            return

        # Show categories when user presses the reply 'Menyu' button
        if text == "🍔 Menyu":
            try:
                # delete the welcome message (if stored) so it doesn't remain while in-menu
                try:
                    wm = ud.pop('welcome_msg', None)
                    if wm:
                        try:
                            await context.bot.delete_message(chat_id=wm.get('chat_id'), message_id=wm.get('message_id'))
                        except Exception:
                            pass
                except Exception:
                    pass
                # Remove the main reply keyboard first so the original buttons disappear,
                # then send a single-button reply keyboard with only '🔙 Chiqish'.
                menu_msgs = []
                try:
                    sent_rm = await context.bot.send_message(chat_id=uid, text='\u200b', reply_markup=ReplyKeyboardRemove())
                    menu_msgs.append({'chat_id': sent_rm.chat_id, 'message_id': sent_rm.message_id})
                except Exception:
                    pass
                try:
                    exit_kb = ReplyKeyboardMarkup([[KeyboardButton('🔙 Chiqish')]], resize_keyboard=True, one_time_keyboard=True)
                    sent_exit = await context.bot.send_message(chat_id=uid, text='chiqish uchun:', reply_markup=exit_kb)
                    menu_msgs.append({'chat_id': sent_exit.chat_id, 'message_id': sent_exit.message_id})
                except Exception:
                    pass
                # Show the inline category menu (categories use inline keyboard)
                try:
                    sent_cat = await context.bot.send_message(chat_id=uid, text="Kategoriya tanlang:", reply_markup=category_menu_kb())
                    menu_msgs.append({'chat_id': sent_cat.chat_id, 'message_id': sent_cat.message_id})
                except Exception:
                    pass
                # store message ids so we can delete them when user exits the menu 
                if menu_msgs:
                    ud['menu_messages'] = menu_msgs
            except Exception:
                pass
            try:
                await update.message.delete()
            except Exception:
                pass
            return

        # Show order history
        if text == "🧾 Buyurtmalar tarixi":
            try:
                # Instead of removing the reply keyboard permanently, show a one-time
                # exit reply-button so the user can go back and restore the main keyboard.
                try:
                    # First try to delete any stored welcome/menu messages that still carry a reply keyboard
                    try:
                        wm = ud.pop('welcome_msg', None)
                        if wm:
                            try:
                                await context.bot.delete_message(chat_id=wm.get('chat_id'), message_id=wm.get('message_id'))
                            except Exception:
                                pass
                    except Exception:
                        pass
                    # Also remove any lingering menu prompts
                    try:
                        menu_msgs = ud.pop('menu_messages', None)
                        if menu_msgs:
                            for m in menu_msgs:
                                try:
                                    await context.bot.delete_message(chat_id=m.get('chat_id'), message_id=m.get('message_id'))
                                except Exception:
                                    pass
                    except Exception:
                        pass
                    # Send an exit reply keyboard so the client keeps showing a button to return
                    exit_kb = ReplyKeyboardMarkup([[KeyboardButton('🔙 Chiqish')]], resize_keyboard=True, one_time_keyboard=True)
                    history_msgs = []
                    try:
                        prompt_msg = await context.bot.send_message(chat_id=uid, text='🔙 Chiqish tugmasini bosing:', reply_markup=exit_kb)
                        history_msgs.append({'chat_id': prompt_msg.chat_id, 'message_id': prompt_msg.message_id})
                    except Exception:
                        pass
                except Exception:
                    pass
                user_orders = [o for o in orders if o.get('user_id') == uid]
                if not user_orders:
                    await update.message.reply_text("Siz hali buyurtma bermagansiz.")
                    try: await update.message.delete()
                    except Exception: pass
                    return
                for o in reversed(user_orders):
                    dt_str = datetime.fromisoformat(o.get('dt')).strftime('%Y-%m-%d %H:%M')
                    parts = (
                        f"#{o['order_number']} — {o.get('status')}\n"
                        f"🛒 {', '.join(o.get('items', []))}\n"
                        f"💰 {o.get('total')} so'm\n"
                        f"🕒 {dt_str}"
                    )
                    try:
                        # add a "Qayta buyurtma" button under each order
                        kb = InlineKeyboardMarkup([[InlineKeyboardButton('🔁 Qayta buyurtma', callback_data=f"reorder_{o['order_number']}")]])
                        sent = await context.bot.send_message(chat_id=uid, text=parts, reply_markup=kb)
                        try:
                            history_msgs.append({'chat_id': sent.chat_id, 'message_id': sent.message_id})
                        except Exception:
                            pass
                    except Exception:
                        try:
                            sent = await context.bot.send_message(chat_id=uid, text=parts)
                            try:
                                history_msgs.append({'chat_id': sent.chat_id, 'message_id': sent.message_id})
                            except Exception:
                                pass
                        except Exception:
                            pass
                try: await update.message.delete()
                except Exception: pass
                # persist history message ids in user_data so we can delete them when user exits
                try:
                    if history_msgs:
                        ud['history_messages'] = history_msgs
                except Exception:
                    pass
            except Exception:
                pass
            return

        # (Personal data button removed) — no direct profile button on main keyboard

        # Send a message to admins (customer suggestions/complaints)
        if text == "Taklif va shikoyatlar":
            ud['contact_admin'] = True
            try:
                # Explicitly remove any reply keyboard first to clear client state
                try:
                    sent_rm = await context.bot.send_message(chat_id=uid, text='\u200b', reply_markup=ReplyKeyboardRemove())
                    try:
                        await context.bot.delete_message(chat_id=sent_rm.chat_id, message_id=sent_rm.message_id)
                    except Exception:
                        pass
                except Exception:
                    pass
                # Delete any previously sent suggestion messages (in suggestions channel) so the user starts fresh
                try:
                    sent_sugs = ud.pop('sent_suggestions', [])
                    for m in sent_sugs:
                        try:
                            await context.bot.delete_message(chat_id=m.get('chat_id'), message_id=m.get('message_id'))
                        except Exception:
                            pass
                except Exception:
                    pass
                # If there are stored menu messages (exit keyboard), delete them so they don't persist
                try:
                    menu_msgs = ud.pop('menu_messages', None)
                    if menu_msgs:
                        for m in menu_msgs:
                            try:
                                await context.bot.delete_message(chat_id=m.get('chat_id'), message_id=m.get('message_id'))
                            except Exception:
                                pass
                except Exception:
                    pass
                # Remove any stored welcome message to avoid duplicates
                try:
                    wm = ud.pop('welcome_msg', None)
                    if wm:
                        try:
                            await context.bot.delete_message(chat_id=wm.get('chat_id'), message_id=wm.get('message_id'))
                        except Exception:
                            pass
                except Exception:
                    pass
                # Show a one-time cancel button so the user can abort the contact flow and store the prompt so we can delete it if user cancels
                try:
                    cancel_kb = ReplyKeyboardMarkup([[KeyboardButton('Bekor qilish')]], resize_keyboard=True, one_time_keyboard=True)
                    sent_prompt = await context.bot.send_message(chat_id=uid, text="Iltimos, taklif yoki shikoyatingizni yozib qoldiring:", reply_markup=cancel_kb)
                    try:
                        ud['suggest_prompt'] = {'chat_id': sent_prompt.chat_id, 'message_id': sent_prompt.message_id}
                    except Exception:
                        pass
                except Exception:
                    try:
                        sent_prompt = await context.bot.send_message(chat_id=uid, text="Iltimos, taklif yoki shikoyatingizni yozib qoldiring:")
                        try:
                            ud['suggest_prompt'] = {'chat_id': sent_prompt.chat_id, 'message_id': sent_prompt.message_id}
                        except Exception:
                            pass
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                await update.message.delete()
            except Exception:
                pass
            return

    # If user is sending a message intended for admins (contact flow)
    if ud.get('contact_admin'):
        try:
            msg = text
            ud.pop('contact_admin', None)
            try:
                # Compose enriched suggestion containing username, stored or full name, and phone if available
                tg_un = update.effective_user.username or ''
                username_display = f"@{tg_un}" if tg_un else "—"
                prof = users_info.get(uid, {})
                saved_name = prof.get('name') or update.effective_user.full_name
                phone_val = prof.get('phone') or ud.get('phone') or "Noma'lum"
                send_text = (
                    f"[Mijoz xabari]\n"
                    f"Ism: {html.escape(saved_name)}\n"
                    f"Username: {html.escape(username_display)}\n"
                    f"ID: {uid}\n"
                    f"Telefon: {html.escape(phone_val)}\n\n"
                    f"{html.escape(msg)}"
                )
                # send suggestion/complaint to the dedicated suggestions channel
                try:
                    # add a reply button so admins can reply directly to this user
                    kb = InlineKeyboardMarkup([[InlineKeyboardButton('↩️ Javob berish', callback_data=f'reply_sug_{uid}_{str(uid)}')]])
                    # Note: we'll include target user id in callback_data; message_id appended after send for reference
                    sent_msg = await context.bot.send_message(chat_id=SUGGESTIONS_CHANNEL_ID, text=send_text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
                    # update callback_data to include the actual channel message id (so callback carries both user_id and channel_msg_id)
                    try:
                        await context.bot.edit_message_reply_markup(chat_id=SUGGESTIONS_CHANNEL_ID, message_id=sent_msg.message_id, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('↩️ Javob berish', callback_data=f'reply_sug_{uid}_{sent_msg.message_id}')]]))
                    except Exception:
                        pass
                    # record sent suggestion so it can be removed later if user cancels
                    try:
                        ud.setdefault('sent_suggestions', []).append({'chat_id': sent_msg.chat_id, 'message_id': sent_msg.message_id})
                    except Exception:
                        pass
                    # remove the suggest prompt (we already delivered the content)
                    try:
                        sp = ud.pop('suggest_prompt', None)
                        if sp:
                            try:
                                await context.bot.delete_message(chat_id=sp.get('chat_id'), message_id=sp.get('message_id'))
                            except Exception:
                                pass
                    except Exception:
                        pass
                except Exception:
                    # fallback to superadmin report if suggestions channel fails
                    try:
                        await report_superadmin(context.bot, send_text)
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                # send confirmation and restore main keyboard so user returns to the app flow
                user_kb = ReplyKeyboardMarkup([
                    [KeyboardButton("🍔 Menyu"), KeyboardButton("Taklif va shikoyatlar")],
                    [KeyboardButton("🧾 Buyurtmalar tarixi")]
                ], resize_keyboard=True, one_time_keyboard=False)
                sent = await context.bot.send_message(chat_id=uid, text="✅ Xabaringiz adminga yuborildi. Tez orada javob olasiz.", reply_markup=user_kb)
                # remember welcome message so we can clean it up later
                try:
                    context.user_data['welcome_msg'] = {'chat_id': sent.chat_id, 'message_id': sent.message_id, 'text': "🍔 Fast Food botiga xush kelibsiz! Quyidagi tugmalardan foydalaning:"}
                except Exception:
                    pass
            except Exception:
                pass
            try:
                await update.message.delete()
            except Exception:
                pass
        except Exception:
            pass
        return
    if ud.get("checkout_state") == "ask_phone" and text:
        # user typed their phone as plain text — normalize and validate
        norm = normalize_phone(text)
        # simple digits count validation (require at least 9 digits)
        digits_only = re.sub(r"\D", "", norm)
        if len(digits_only) < 9:
            try:
                await update.message.reply_text("Noto'g'ri telefon formati. Iltimos, quyidagi formatda kiriting: +998901234567")
            except Exception:
                pass
            return
        ud["phone"] = norm
        ud["checkout_state"] = "ask_location"
        # delete previous bot prompt (phone ask) if stored
        try:
            lp = ud.pop('last_prompt_msg', None)
            if lp:
                try:
                    await context.bot.delete_message(chat_id=lp['chat_id'], message_id=lp['message_id'])
                except Exception:
                    pass
        except Exception:
            pass
        kb = ReplyKeyboardMarkup([[KeyboardButton("📍 Lokatsiyani ulashish", request_location=True)]], resize_keyboard=True, one_time_keyboard=True)
        # send location prompt and remember it
        try:
            sent = await context.bot.send_message(chat_id=update.effective_user.id, text="📍 Iltimos, manzilingizni yuboring:", reply_markup=kb)
            ud['last_prompt_msg'] = {'chat_id': sent.chat_id, 'message_id': sent.message_id}
        except Exception:
            try:
                await update.message.reply_text("📍 Iltimos, manzilingizni yuboring:", reply_markup=kb)
            except Exception:
                pass
        # delete the user's phone text message to avoid leaving it in chat
        try:
            await update.message.delete()
        except Exception:
            pass
        return
    await start(update, context)




async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = context.user_data
    # If this contact was shared as part of checkout flow
    if ud.get("checkout_state") == "ask_phone" and update.message.contact:
        # store normalized phone from shared contact
        ud["phone"] = normalize_phone(update.message.contact.phone_number)
        ud["checkout_state"] = "ask_location"
        # delete the previous bot prompt (phone ask) if we stored it
        try:
            lp = ud.pop('last_prompt_msg', None)
            if lp:
                try:
                    await context.bot.delete_message(chat_id=lp['chat_id'], message_id=lp['message_id'])
                except Exception:
                    pass
        except Exception:
            pass
        kb = ReplyKeyboardMarkup([[KeyboardButton("📍 Lokatsiyani ulashish", request_location=True)]], resize_keyboard=True, one_time_keyboard=True)
        # send location prompt and remember it so we can delete after location provided
        try:
            sent = await context.bot.send_message(chat_id=update.effective_user.id, text="📍 Endi manzilingizni yuboring:", reply_markup=kb)
            ud['last_prompt_msg'] = {'chat_id': sent.chat_id, 'message_id': sent.message_id}
        except Exception:
            try:
                await update.message.reply_text("📍 Endi manzilingizni yuboring:", reply_markup=kb)
            except Exception:
                pass
        # remove the user's shared contact message so phone doesn't linger in chat
        try:
            await update.message.delete()
        except Exception:
            pass
        return

    # If this contact was shared as part of profile setup (first-start)
    if ud.get('profile_setup') == 'phone' and update.message.contact:
        name = ud.pop('profile_name', None) or update.effective_user.full_name
        phone = normalize_phone(update.message.contact.phone_number)
        # persist to users_info
        users_info[update.effective_user.id] = {'name': name, 'phone': phone, 'username': update.effective_user.username or ''}
        try:
            persist_users_info()
        except Exception:
            pass
        # cleanup any prompt we stored for profile
        try:
            lp = ud.pop('profile_last_prompt', None)
            if lp:
                try:
                    await context.bot.delete_message(chat_id=lp['chat_id'], message_id=lp['message_id'])
                except Exception:
                    pass
        except Exception:
            pass
        ud.pop('profile_setup', None)
        ud.pop('profile_name', None)
        # send confirmation and show main keyboard
        try:
            await context.bot.send_message(chat_id=update.effective_user.id, text=f"✅ Profilingiz saqlandi. Salom, {name}!", reply_markup=ReplyKeyboardRemove())
        except Exception:
            pass
        try:
            user_kb = ReplyKeyboardMarkup([
                [KeyboardButton("🍔 Menyu"), KeyboardButton("Taklif va shikoyatlar")],
                [KeyboardButton("🧾 Buyurtmalar tarixi")]
            ], resize_keyboard=True, one_time_keyboard=False)
            try:
                sent_w = await context.bot.send_message(chat_id=update.effective_user.id, text="🍔 Fast Food botiga xush kelibsiz! Quyidagi tugmalardan foydalaning:", reply_markup=user_kb)
                try:
                    context.user_data['welcome_msg'] = {'chat_id': sent_w.chat_id, 'message_id': sent_w.message_id, 'text': "🍔 Fast Food botiga xush kelibsiz! Quyidagi tugmalardan foydalaning:"}
                except Exception:
                    pass
            except Exception:
                pass
        except Exception:
            pass
        # remove shared contact message
        try:
            await update.message.delete()
        except Exception:
            pass
        return

async def location_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global order_counter
    ud = context.user_data
    if ud.get("checkout_state") == "ask_location" and update.message.location:
        loc: Location = update.message.location; ud["checkout_state"] = None
        cart = ud.get("cart", {}); cart_summary, total = cart_text_and_total(cart)
        # Saqlab qo'yamiz va foydalanuvchidan to'lov turini so'raymiz (Naqd yoki Kart)
        # prefer phone collected during this checkout; fall back to saved profile phone if available
        phone_val = ud.get('phone') or users_info.get(update.effective_user.id, {}).get('phone') or "Noma'lum"
        ud['pending_order'] = {
            'items': [f"{k} x{v}" for k, v in cart.items()],
            'total': total,
            'phone': phone_val,
            'loc': f"{loc.latitude:.5f},{loc.longitude:.5f}",
            'dt': datetime.now(timezone.utc).isoformat(),
            'original_text': cart_summary
        }
        ud["cart"] = {}
        # delete the previous bot prompt (location ask) if we stored it
        try:
            lp = ud.pop('last_prompt_msg', None)
            if lp:
                try:
                    await context.bot.delete_message(chat_id=lp['chat_id'], message_id=lp['message_id'])
                except Exception:
                    pass
        except Exception:
            pass
        # delete the user's location message to avoid leaving it in chat
        try:
            await update.message.delete()
        except Exception:
            pass
        # payment choice keyboard
        pay_kb = InlineKeyboardMarkup([[InlineKeyboardButton("💵 Naqd (cash)", callback_data="pay_cash") , InlineKeyboardButton("💳 Kartasi", callback_data="pay_card")]])
        # Explicitly remove any lingering reply keyboard (some clients keep it visible)
        try:
            await context.bot.send_message(chat_id=update.effective_user.id, text='\u200b', reply_markup=ReplyKeyboardRemove())
        except Exception:
            pass
        try:
            await context.bot.send_message(chat_id=update.effective_user.id, text="To'lov turini tanlang:", reply_markup=pay_kb)
        except Exception:
            try:
                await update.message.reply_text("To'lov turini tanlang:", reply_markup=pay_kb)
            except Exception:
                pass
        return

# ========== ASOSIY FUNKSIYA ==========
def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN topilmadi. Iltimos, muhit o'zgaruvchisini (env var) BOT_TOKEN sifatida o'rnating.")
    async def startup_reschedule(app):
        global order_counter
        if orders: order_counter = max((o.get("order_number", 0) for o in orders), default=0)
        for o in list(orders):
            if o.get("status") == "Kutilyapti":
                created = datetime.fromisoformat(o["dt"])
                if (datetime.now(timezone.utc) - created).total_seconds() < 60: 
                    task = asyncio.create_task(handle_order_expiry(o["order_number"], app.bot))
                    expiry_tasks[o["order_number"]] = task

    async def _run():
        app = ApplicationBuilder().token(BOT_TOKEN).post_init(startup_reschedule).build()
        app.add_handler(CommandHandler("start", start)); app.add_handler(CommandHandler("help", help_command))
        app.add_handler(CallbackQueryHandler(callback_handler))
        # Telegram Payments handlers
        app.add_handler(PreCheckoutQueryHandler(precheckout_handler))
        app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))
        app.add_handler(MessageHandler(filters.CONTACT, contact_handler)); app.add_handler(MessageHandler(filters.LOCATION, location_handler))
        # Accept all message types here so admin broadcasts containing media are handled
        app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, text_handler))
        # Explicit initialization to avoid ExtBot initialization errors
        await app.initialize()
        # Wrap common send methods to record bot-sent messages for cleanup
        try:
            bot = app.bot
            # send_message
            _orig_send_message = bot.send_message
            async def _wrapped_send_message(*args, **kwargs):
                msg = await _orig_send_message(*args, **kwargs)
                try:
                    if getattr(msg.chat, 'type', None) == 'private':
                        _record_bot_message(msg.chat_id, msg.message_id)
                except Exception:
                    pass
                return msg
            bot.send_message = _wrapped_send_message  # type: ignore

            # send_photo
            _orig_send_photo = bot.send_photo
            async def _wrapped_send_photo(*args, **kwargs):
                msg = await _orig_send_photo(*args, **kwargs)
                try:
                    if getattr(msg.chat, 'type', None) == 'private':
                        _record_bot_message(msg.chat_id, msg.message_id)
                except Exception:
                    pass
                return msg
            bot.send_photo = _wrapped_send_photo  # type: ignore

            # send_document
            _orig_send_document = bot.send_document
            async def _wrapped_send_document(*args, **kwargs):
                msg = await _orig_send_document(*args, **kwargs)
                try:
                    if getattr(msg.chat, 'type', None) == 'private':
                        _record_bot_message(msg.chat_id, msg.message_id)
                except Exception:
                    pass
                return msg
            bot.send_document = _wrapped_send_document  # type: ignore

            # send_sticker
            _orig_send_sticker = bot.send_sticker
            async def _wrapped_send_sticker(*args, **kwargs):
                msg = await _orig_send_sticker(*args, **kwargs)
                try:
                    if getattr(msg.chat, 'type', None) == 'private':
                        _record_bot_message(msg.chat_id, msg.message_id)
                except Exception:
                    pass
                return msg
            bot.send_sticker = _wrapped_send_sticker  # type: ignore

            # forward_message
            _orig_forward_message = bot.forward_message
            async def _wrapped_forward_message(*args, **kwargs):
                msg = await _orig_forward_message(*args, **kwargs)
                try:
                    if getattr(msg.chat, 'type', None) == 'private':
                        _record_bot_message(msg.chat_id, msg.message_id)
                except Exception:
                    pass
                return msg
            bot.forward_message = _wrapped_forward_message  # type: ignore

            # send_media_group (returns list of Messages)
            _orig_send_media_group = bot.send_media_group
            async def _wrapped_send_media_group(*args, **kwargs):
                msgs = await _orig_send_media_group(*args, **kwargs)
                try:
                    for m in msgs or []:
                        if getattr(m.chat, 'type', None) == 'private':
                            _record_bot_message(m.chat_id, m.message_id)
                except Exception:
                    pass
                return msgs
            bot.send_media_group = _wrapped_send_media_group  # type: ignore

            # send_invoice
            _orig_send_invoice = bot.send_invoice
            async def _wrapped_send_invoice(*args, **kwargs):
                msg = await _orig_send_invoice(*args, **kwargs)
                try:
                    if getattr(msg.chat, 'type', None) == 'private':
                        _record_bot_message(msg.chat_id, msg.message_id)
                except Exception:
                    pass
                return msg
            bot.send_invoice = _wrapped_send_invoice  # type: ignore
        except Exception as e:
            log.warning(f"Bot send wrappers init failed: {e}")
        try:
            await app.start()
            log.info("Bot ishga tushdi.")
            await app.updater.start_polling()
            # Keep the application running
            stop_event = asyncio.Event()
            try:
                await stop_event.wait()
            except asyncio.CancelledError:
                pass
        finally:
            try:
                # Ensure polling stops before shutdown
                try:
                    await app.updater.stop()
                except Exception:
                    pass
                await app.stop()
            finally:
                await app.shutdown()

    # Run the async runner
    asyncio.run(_run())

if __name__ == "__main__":
    main()