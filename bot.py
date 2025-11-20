# bot.py
# Telegram bot requests library bilan
import json
import time
import requests
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

# ========== SOZLAMALAR ==========
BOT_TOKEN = "8447079141:AAEekMNhdb0DK2E0fmcNEhr650VkBHFMCSY"  
ADMIN_ID = 5788278697               
admins = {ADMIN_ID}

USERS_FILE = "users.json"
ORDERS_FILE = "orders.json"

# ========== YUKLAMALAR VA SAQLASH UTILITYLARI ==========
def load_json(fname, default):
    try:
        if os.path.exists(fname):
            with open(fname, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"Faylni yuklashda xatolik ({fname}): {e}")
    return default

def save_json(fname, data):
    tmp = fname + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, fname)
    except Exception as e:
        print(f"Faylni saqlashda xatolik ({fname}): {e}")

# Foydalanuvchilar va buyurtmalarni fayldan yuklash
_users_data = load_json(USERS_FILE, [])
users = set(int(x) for x in _users_data)

_orders_data = load_json(ORDERS_FILE, [])
orders = _orders_data if isinstance(_orders_data, list) else []

order_counter = max((o.get("order_number", 0) for o in orders), default=0)

# ========== MENYU & KLAVIATURALAR ==========
menu_data = {
    "Ichimliklar": { 
        "Coca Cola 0.5l": {"price": 8000, "desc": "Salqin ichimlik"},
        "Coca Cola 1l": {"price": 11000, "desc": "Salqin ichimlik"},
        "Coca Cola 1.5l": {"price": 14000, "desc": "Salqin ichimlik"}, 
        "Fanta": {"price": 7000, "desc": "Mevali lazzat"}
    },
    "Fast Food": {
        "Burger": {"price": 25000, "desc": "Go'shtli burger"}, 
        "Hot Dog": {"price": 18000, "desc": "Sosiska non ichida"}
    },
    "Taomlar": {
        "Palov": {"price": 35000, "desc": "An'anaviy o'zbek taomi"}, 
        "Manti": {"price": 30000, "desc": "Bug'da pishirilgan manti"}
    },
}

# ========== YORDAMCHI FUNKSIYALAR ==========
def persist_users(): save_json(USERS_FILE, list(users))
def persist_orders(): save_json(ORDERS_FILE, orders)
def find_order(order_number: int): return next((o for o in orders if int(o.get("order_number", -1)) == int(order_number)), None)

def admin_panel_kb():
    return {
        'inline_keyboard': [
            [{'text': "📦 Faol buyurtmalar", 'callback_data': "admin_orders"}],
            [{'text': "🧹 Barcha buyurtmalarni tozalash", 'callback_data': "admin_clear_all_orders"}],
            [{'text': "📢 Broadcast", 'callback_data': "admin_broadcast"}],
            [{'text': "➕ Yangi admin", 'callback_data': "admin_add"}],
            [{'text': "❌ Adminni olib tashlash", 'callback_data': "admin_remove"}],
        ]
    }

def category_menu_kb():
    return {
        'inline_keyboard': [
            [{'text': "🥤 Ichimliklar", 'callback_data': "cat_Ichimliklar"}],
            [{'text': "🍔 Fast Food", 'callback_data': "cat_Fast Food"}],
            [{'text': "🍛 Taomlar", 'callback_data': "cat_Taomlar"}],
            [{'text': "🛒 Savat", 'callback_data': "view_cart"}],
        ]
    }

def product_list_kb(category: str):
    buttons = []
    for name, info in menu_data[category].items():
        buttons.append([{'text': f"{name} — {info['price']} so'm", 'callback_data': f"prod_{category}|{name}"}])
    buttons.append([
        {'text': "◀️ Ortga", 'callback_data': "back_categories"}, 
        {'text': "🛒 Savat", 'callback_data': "view_cart"}
    ])
    return {'inline_keyboard': buttons}

def quantity_kb(category: str, product: str, qty: int):
    return {
        'inline_keyboard': [
            [
                {'text': "➖", 'callback_data': f"qty_{category}|{product}|dec"},
                {'text': str(qty), 'callback_data': "noop"},
                {'text': "➕", 'callback_data': f"qty_{category}|{product}|inc"}
            ],
            [{'text': "🛒 Savatga qo'shish", 'callback_data': f"add_{product}|{qty}"}],
            [{'text': "◀️ Menyuga qaytish", 'callback_data': "back_categories"}]
        ]
    }

def cart_text_and_total(cart: dict):
    if not cart: return "🛒 Savat bo'sh.", 0
    lines, total, price_map = [], 0, {p: info["price"] for c in menu_data.values() for p, info in c.items()}
    for name, qty in cart.items():
        summa = price_map.get(name, 0) * qty
        total += summa; lines.append(f"• {name} x{qty} — {summa} so'm")
    return "🛒 Savat:\n" + "\n".join(lines) + f"\n\nJami: {total} so'm", total

def cart_menu_kb(has_items: bool):
    rows = [[{'text': "◀️ Menyu", 'callback_data': "back_categories"}]]
    if has_items: 
        rows.insert(0, [
            {'text': "🧹 Tozalash", 'callback_data': "clear_cart"}, 
            {'text': "✅ Buyurtma berish", 'callback_data': "checkout"}
        ])
    return {'inline_keyboard': rows}

def generate_admin_order_kb(order: dict):
    buttons = []
    order_num = order['order_number']
    status = order['status']
    
    if status == 'Tayyorlanmoqda':
        buttons.append({'text': "➡️ Yo'lga chiqdi", 'callback_data': f"set_status_{order_num}_Yo'lda"})
    elif status == "Yo'lda":
        buttons.append({'text': "✅ Yetkazib berildi", 'callback_data': f"set_status_{order_num}_Yetkazib berildi"})
    
    if status != 'Yetkazib berildi':
        buttons.append({'text': f"❌ Bekor qilish", 'callback_data': f"cancel_order_{order_num}"})
        
    return {'inline_keyboard': [buttons]}

# ========== TELEGRAM BOT SINFAR ==========
class TelegramBot:
    def __init__(self, token):
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.last_update_id = 0
        self.user_states = {}
        
    def send_message(self, chat_id, text, reply_markup=None):
        url = f"{self.base_url}/sendMessage"
        data = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'HTML'
        }
        if reply_markup:
            data['reply_markup'] = json.dumps(reply_markup)
        try:
            response = requests.post(url, data=data, timeout=10)
            result = response.json()
            if result.get('ok'):
                # Yuborilgan xabarni log qilish
                short_text = text[:50] + "..." if len(text) > 50 else text
                print(f"📤 Bot → {chat_id}: {short_text}")
            return result
        except Exception as e:
            print(f"❌ Xabar yuborishda xato: {e}")
            return None
            
    def edit_message_text(self, chat_id, message_id, text, reply_markup=None):
        url = f"{self.base_url}/editMessageText"
        data = {
            'chat_id': chat_id,
            'message_id': message_id,
            'text': text,
            'parse_mode': 'HTML'
        }
        if reply_markup:
            data['reply_markup'] = json.dumps(reply_markup)
        try:
            response = requests.post(url, data=data, timeout=10)
            return response.json()
        except Exception as e:
            print(f"❌ Xabar tahrirlashda xato: {e}")
            return None
            
    def edit_message_reply_markup(self, chat_id, message_id, reply_markup):
        url = f"{self.base_url}/editMessageReplyMarkup"
        data = {
            'chat_id': chat_id,
            'message_id': message_id,
            'reply_markup': json.dumps(reply_markup)
        }
        try:
            response = requests.post(url, data=data, timeout=10)
            return response.json()
        except Exception as e:
            print(f"❌ Tugmalarni tahrirlashda xato: {e}")
            return None
            
    def delete_message(self, chat_id, message_id):
        url = f"{self.base_url}/deleteMessage"
        data = {
            'chat_id': chat_id,
            'message_id': message_id
        }
        try:
            response = requests.post(url, data=data, timeout=10)
            return response.json()
        except Exception as e:
            print(f"❌ Xabarni o'chirishda xato: {e}")
            return None
            
    def answer_callback_query(self, callback_query_id, text=None):
        url = f"{self.base_url}/answerCallbackQuery"
        data = {'callback_query_id': callback_query_id}
        if text:
            data['text'] = text
        try:
            requests.post(url, data=data, timeout=5)
        except Exception as e:
            print(f"❌ Callback javob berishda xato: {e}")
            
    def get_updates(self):
        url = f"{self.base_url}/getUpdates"
        data = {'offset': self.last_update_id + 1, 'timeout': 5}
        try:
            response = requests.get(url, params=data, timeout=10)
            return response.json()
        except requests.exceptions.Timeout:
            print(f"⏰ Timeout - internet sekin ishlayapti...")
            return {'ok': True, 'result': []}
        except requests.exceptions.ConnectionError:
            print(f"🌐 Internet ulanishida muammo - qayta urinish...")
            return None
        except Exception as e:
            print(f"❌ Updates olishda xato: {e}")
            return None
            
    def handle_start(self, chat_id, user_data):
        user_id = user_data['id']
        user_name = user_data.get('first_name', 'Foydalanuvchi')
        
        print(f"👤 {user_name} ({user_id}) → /start")
        
        if user_id not in users:
            users.add(user_id)
            persist_users()
            print(f"✅ Yangi foydalanuvchi ro'yxatga qo'shildi: {user_name}")
            
        # ID xabarini yuborish
        try:
            self.send_message(chat_id, f"Salom, {user_name}! 👋\nSizning Telegram ID raqamingiz: `{user_id}`")
        except Exception as e:
            print(f"ID xabarini yuborishda xato: {e}")
            
        self.user_states[user_id] = {"cart": {}}
        
        if user_id in admins:
            self.send_message(chat_id, "🔑 Admin panelga xush kelibsiz!", admin_panel_kb())
        else:
            self.send_message(chat_id, "🍔 Fast Food botiga xush kelibsiz!", category_menu_kb())

    def handle_callback_query(self, callback_query):
        chat_id = callback_query['message']['chat']['id']
        user_id = callback_query['from']['id']
        data = callback_query['data']
        message_id = callback_query['message']['message_id']
        user_name = callback_query['from'].get('first_name', 'Foydalanuvchi')
        
        print(f"🔘 {user_name} ({user_id}) → {data}")
        
        self.answer_callback_query(callback_query['id'])
        
        if user_id not in self.user_states:
            self.user_states[user_id] = {"cart": {}}
        
        ud = self.user_states[user_id]
        ud.setdefault("cart", {})

        # ADMIN FUNKSIONALI
        if user_id in admins:
            if data == "admin_orders":
                active_orders = [o for o in orders if o.get("status") != "Yetkazib berildi"]
                if not active_orders:
                    self.edit_message_text(chat_id, message_id, "📂 Hozircha faol buyurtmalar yo'q.", admin_panel_kb())
                    return

                self.edit_message_text(chat_id, message_id, "📦 Faol buyurtmalar ro'yxati alohida yuborilmoqda:", admin_panel_kb())
                for o in reversed(active_orders):
                    dt_str = datetime.fromisoformat(o.get("dt")).strftime('%Y-%m-%d %H:%M')
                    order_text = (
                        f"#{o['order_number']} — **{o['status'].upper()}**\n"
                        f"👤 {o['user']}\n📞 {o['phone']}\n"
                        f"🛒 {', '.join(o.get('items', []))}\n💰 {o['total']} so'm\n"
                        f"📍 https://www.google.com/maps/search/?api=1&query={o['loc']}\n"
                        f"🕒 {dt_str}"
                    )
                    self.send_message(chat_id, order_text, generate_admin_order_kb(o))
                return
            
            if data == "admin_clear_all_orders":
                global order_counter
                orders.clear()
                order_counter = 0
                persist_orders()
                self.edit_message_text(chat_id, message_id, "✅ Barcha buyurtmalar tarixi muvaffaqiyatli tozalandi!", admin_panel_kb())
                return
                
            if data.startswith("set_status_"):
                try: 
                    _, _, order_num_str, new_status = data.split("_")
                    order_num = int(order_num_str)
                except (ValueError, IndexError): 
                    self.answer_callback_query(callback_query['id'], "Noto'g'ri buyruq", show_alert=True)
                    return

                order = find_order(order_num)
                if not order: 
                    self.answer_callback_query(callback_query['id'], "Buyurtma topilmadi", show_alert=True)
                    return
                
                order['status'] = new_status
                persist_orders()
                
                current_text = callback_query['message']['text']
                self.edit_message_text(chat_id, message_id, current_text + f"\n\n✅ Status \"{new_status}\" ga o'zgartirildi.", generate_admin_order_kb(order))
                
                try: 
                    self.send_message(order['user_id'], f"🔔 Sizning #{order_num} buyurtmangizning holati \"{new_status}\" ga o'zgardi.")
                except Exception as e: 
                    print(f"Foydalanuvchiga status o'zgarishi haqida yuborishda xato: {e}")
                return
                
            # broadcast, add/remove admin
            if data == "admin_broadcast": 
                ud["want_broadcast"] = True
                self.edit_message_text(chat_id, message_id, "📢 Yuboriladigan xabarni yozing:", admin_panel_kb())
                return
            if data == "admin_add": 
                ud["want_add_admin"] = True
                self.edit_message_text(chat_id, message_id, "➕ Yangi admin ID raqamini kiriting:", admin_panel_kb())
                return
            if data == "admin_remove": 
                ud["want_remove_admin"] = True
                self.edit_message_text(chat_id, message_id, "❌ O'chiriladigan admin ID raqamini kiriting:", admin_panel_kb())
                return

        # FOYDALANUVCHI FUNKSIONALI
        if data.startswith("cat_"): 
            cat = data.split("_", 1)[1]
            self.edit_message_text(chat_id, message_id, f"📋 {cat} menyusi:", product_list_kb(cat))
        elif data == "back_categories": 
            self.edit_message_text(chat_id, message_id, "Kategoriya tanlang:", category_menu_kb())
        elif data.startswith("prod_"):
            _, rest = data.split("_", 1)
            cat, prod = rest.split("|")
            ud.update({"current_cat": cat, "current_prod": prod, "current_qty": 1})
            info = menu_data[cat][prod]
            text = f"🍽 {prod}\n\n💰 Narxi: {info['price']} so'm\n\n{info['desc']}"
            self.edit_message_text(chat_id, message_id, text, quantity_kb(cat, prod, 1))
        elif data.startswith("qty_"):
            _, rest = data.split("_", 1)
            cat, prod, op = rest.split("|")
            qty = ud.get("current_qty", 1)
            qty = max(1, qty - 1) if op == "dec" else qty + 1
            ud["current_qty"] = qty
            self.edit_message_reply_markup(chat_id, message_id, quantity_kb(cat, prod, qty))
        elif data.startswith("add_"):
            _, rest = data.split("_", 1)
            prod, qty_str = rest.split("|")
            qty = int(qty_str)
            cart = ud["cart"]
            cart[prod] = cart.get(prod, 0) + qty
            text, _ = cart_text_and_total(cart)
            self.edit_message_text(chat_id, message_id, f"✅ {prod} x{qty} savatga qo'shildi.\n\n{text}", cart_menu_kb(bool(cart)))
        elif data == "view_cart": 
            text, _ = cart_text_and_total(ud["cart"])
            self.edit_message_text(chat_id, message_id, text, cart_menu_kb(bool(ud["cart"])))
        elif data == "clear_cart": 
            ud["cart"] = {}
            self.edit_message_text(chat_id, message_id, "🧹 Savat tozalandi.", cart_menu_kb(False))
        elif data == "checkout":
            if not ud.get("cart"): 
                self.edit_message_text(chat_id, message_id, "🛒 Savat bo'sh.", category_menu_kb())
                return
            ud["checkout_state"] = "ask_phone"
            kb = {
                'keyboard': [
                    [{'text': "📞 Raqamni ulashish", 'request_contact': True}]
                ],
                'resize_keyboard': True, 
                'one_time_keyboard': True
            }
            self.send_message(chat_id, "📞 Iltimos, telefon raqamingizni yuboring:", kb)
            self.delete_message(chat_id, message_id)
        
        # BUYURTMANI BEKOR QILISH
        elif data.startswith("cancel_order_"):
            try: 
                order_num = int(data.split("_")[-1])
            except (ValueError, IndexError): 
                self.answer_callback_query(callback_query['id'], "Noto'g'ri buyruq", show_alert=True)
                return

            order_index = -1
            for i, o in enumerate(orders):
                if o.get("order_number") == order_num:
                    order_index = i
                    break
            
            if order_index == -1: 
                self.answer_callback_query(callback_query['id'], "Buyurtma topilmadi", show_alert=True)
                return
            order = orders[order_index]

            is_user_canceling = (user_id == order["user_id"])
            is_admin_canceling = (user_id in admins)

            if is_user_canceling and order['status'] != 'Kutilyapti':
                self.answer_callback_query(callback_query['id'], "⏳ Faqat 'Kutilyapti' holatidagi buyurtmani bekor qila olasiz!", show_alert=True)
                return
            
            if is_admin_canceling and order['status'] == 'Yetkazib berildi':
                 self.answer_callback_query(callback_query['id'], "Bu buyurtma allaqachon yetkazilgan.", show_alert=True)
                 return

            # Admin xabarlarini tahrirlash/o'chirish
            for am in order.get("admin_msgs", []):
                try: 
                    self.edit_message_text(am["chat_id"], am["message_id"], f"❌ Buyurtma #{order_num} bekor qilindi.")
                except: 
                    pass

            # Foydalanuvchi xabarini tahrirlash
            try: 
                self.edit_message_text(chat_id, message_id, f"❌ Buyurtma #{order_num} bekor qilindi.")
            except: 
                pass
            
            # Admin bekor qilsa, foydalanuvchiga xabar berish
            if is_admin_canceling and not is_user_canceling:
                try: 
                    self.send_message(order["user_id"], f"⚠️ Sizning #{order_num} buyurtmangiz admin tomonidan bekor qilindi.")
                except Exception as e: 
                    print(f"Foydalanuvchiga bekor qilish haqida yuborishda xato: {e}")

            # Buyurtmani ro'yxatdan o'chirish
            del orders[order_index]
            persist_orders()

    def handle_text_message(self, message):
        chat_id = message['chat']['id']
        user_id = message['from']['id']
        text = message.get('text', '').strip()
        user_name = message['from'].get('first_name', 'Foydalanuvchi')
        
        print(f"💬 {user_name} ({user_id}) → {text}")
        
        if user_id not in self.user_states:
            self.user_states[user_id] = {"cart": {}}
        
        ud = self.user_states[user_id]
        ud.setdefault("cart", {})

        if user_id in admins:
            if ud.get("want_broadcast"):
                ud.pop("want_broadcast", None)
                sent, failed = 0, 0
                print(f"📢 Admin broadcast boshlandi: '{text[:30]}...'")
                for user_id_broadcast in list(users):
                    try: 
                        self.send_message(user_id_broadcast, text)
                        sent += 1
                    except Exception as e: 
                        failed += 1
                        print(f"Broadcastda xato ({user_id_broadcast}): {e}")
                print(f"📢 Broadcast tugadi - Muvaffaqiyat: {sent}, Xato: {failed}")
                self.send_message(chat_id, f"✅ Xabar yuborildi.\nMuvaffaqiyatli: {sent}\nXatolik: {failed}", admin_panel_kb())
                return
            if ud.get("want_add_admin"):
                ud.pop("want_add_admin", None)
                try: 
                    admins.add(int(text))
                    self.send_message(chat_id, f"✅ {text} admin sifatida qo'shildi.", admin_panel_kb())
                except ValueError: 
                    self.send_message(chat_id, "❌ Xato ID.", admin_panel_kb())
                return
            if ud.get("want_remove_admin"):
                ud.pop("want_remove_admin", None)
                try:
                    rem_id = int(text)
                    if rem_id == ADMIN_ID: 
                        self.send_message(chat_id, "⚠️ Asosiy adminni o'chira olmaysiz.", admin_panel_kb())
                    elif rem_id in admins: 
                        admins.discard(rem_id)
                        self.send_message(chat_id, f"✅ {rem_id} adminlikdan olib tashlandi.", admin_panel_kb())
                    else: 
                        self.send_message(chat_id, "ℹ️ Bu ID adminlar ro'yxatida yo'q.", admin_panel_kb())
                except ValueError: 
                    self.send_message(chat_id, "❌ Xato ID.", admin_panel_kb())
                return
                
        if ud.get("checkout_state") == "ask_phone" and text:
            ud["phone"] = text
            ud["checkout_state"] = "ask_location"
            kb = {
                'keyboard': [
                    [{'text': "📍 Lokatsiyani ulashish", 'request_location': True}]
                ],
                'resize_keyboard': True, 
                'one_time_keyboard': True
            }
            self.send_message(chat_id, "📍 Iltimos, manzilingizni yuboring:", kb)
            return
            
        # Default - start qayta chaqirish
        self.handle_start(chat_id, message['from'])

    def handle_contact(self, message):
        chat_id = message['chat']['id']
        user_id = message['from']['id']
        user_name = message['from'].get('first_name', 'Foydalanuvchi')
        
        print(f"📞 {user_name} ({user_id}) → Telefon raqam ulashdi")
        
        if user_id not in self.user_states:
            self.user_states[user_id] = {"cart": {}}
            
        ud = self.user_states[user_id]
        
        if ud.get("checkout_state") == "ask_phone" and message.get('contact'):
            ud["phone"] = message['contact']['phone_number']
            ud["checkout_state"] = "ask_location"
            kb = {
                'keyboard': [
                    [{'text': "📍 Lokatsiyani ulashish", 'request_location': True}]
                ],
                'resize_keyboard': True, 
                'one_time_keyboard': True
            }
            self.send_message(chat_id, "📍 Endi manzilingizni yuboring:", kb)

    def handle_location(self, message):
        global order_counter
        chat_id = message['chat']['id']
        user_id = message['from']['id']
        user_name = message['from'].get('first_name', 'Foydalanuvchi')
        
        print(f"📍 {user_name} ({user_id}) → Lokatsiya ulashdi")
        
        if user_id not in self.user_states:
            return
            
        ud = self.user_states[user_id]
        
        if ud.get("checkout_state") == "ask_location" and message.get('location'):
            loc = message['location']
            ud["checkout_state"] = None
            cart = ud.get("cart", {})
            cart_summary, total = cart_text_and_total(cart)
            order_counter += 1
            order_number = order_counter
            
            user_name = message['from'].get('first_name', 'Foydalanuvchi')
            
            order = {
                "order_number": order_number, 
                "user_id": user_id, 
                "user": f"{message['from'].get('first_name', '')} (id: {user_id})",
                "items": [f"{k} x{v}" for k, v in cart.items()], 
                "total": total, 
                "phone": ud.get("phone", "Noma'lum"),
                "loc": f"{loc['latitude']:.5f},{loc['longitude']:.5f}", 
                "dt": datetime.now(timezone.utc).isoformat(),
                "status": "Kutilyapti", 
                "user_msg": None, 
                "admin_msgs": [], 
                "original_text": cart_summary
            }
            orders.append(order)
            ud["cart"] = {}
            
            print(f"🆕 Yangi buyurtma #{order_number} yaratildi - {user_name} ({user_id}) - {total:,} so'm")

            cancel_kb = {
                'inline_keyboard': [
                    [{'text': f"❌ Bekor qilish #{order_number}", 'callback_data': f"cancel_order_{order_number}"}]
                ]
            }
            sent = self.send_message(chat_id, f"✅ Buyurtmangiz #{order_number} qabul qilindi!\n\n{cart_summary}\n\n⏳ Bekor qilish uchun 60 soniyangiz bor.", cancel_kb)
            
            if sent and sent.get('ok'):
                order["user_msg"] = {"chat_id": sent['result']['chat']['id'], "message_id": sent['result']['message_id']}

            # Keyboard ni olib tashlash va menyu ko'rsatish
            remove_kb = {'remove_keyboard': True}
            self.send_message(chat_id, "Asosiy menyu:", remove_kb)
            self.send_message(chat_id, "Yangi buyurtma berish uchun tanlang:", category_menu_kb())

            admin_text = f"🆕 Yangi buyurtma #{order_number}!\n\n{cart_summary}\n\n👤 Mijoz: {order['user']}\n📞 {order['phone']}\n📍 https://www.google.com/maps/search/?api=1&query={order['loc']}"
            for admin_id in list(admins):
                try:
                    msg = self.send_message(admin_id, admin_text, generate_admin_order_kb(order))
                    if msg and msg.get('ok'):
                        order["admin_msgs"].append({
                            "admin_id": admin_id, 
                            "chat_id": msg['result']['chat']['id'], 
                            "message_id": msg['result']['message_id'], 
                            "text": cart_summary
                        })
                except Exception as e: 
                    print(f"Adminga xabar yuborishda xato ({admin_id}): {e}")

            persist_orders()

    def handle_message(self, message):
        if 'text' in message:
            if message['text'].startswith('/start'):
                self.handle_start(message['chat']['id'], message['from'])
            else:
                self.handle_text_message(message)
        elif 'contact' in message:
            self.handle_contact(message)
        elif 'location' in message:
            self.handle_location(message)

    def run(self):
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
                    connection_errors = 0
                    
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
                        time.sleep(30)
                        connection_errors = 0
                    else:
                        time.sleep(2)
                
                time.sleep(1)
                
            except KeyboardInterrupt:
                print("\n⏹️ Bot to'xtatilmoqda...")
                break
            except Exception as e:
                print(f"❌ Umumiy xato: {e}")
                time.sleep(5)

def main():
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN topilmadi!")
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
    bot = TelegramBot(BOT_TOKEN)
    bot.run()

if __name__ == "__main__":
    main()