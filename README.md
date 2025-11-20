# 🤖 Dostavka Bot - Avtomatik MySQL Integratsiyasi

Telegram bot oziq-ovqat yetkazib berish uchun avtomatik MySQL database bilan.

## ✨ Xususiyatlar

- 🍕 Mahsulot katalogi kategoriyalar bilan
- 🛒 Savat funksionaligi
- 📱 Buyurtmalar boshqaruvi
- 👤 Foydalanuvchi profillari
- 🔐 Admin panel statistika bilan
- 💾 **Avtomatik MySQL setup** (Database o'zi yaratiladi!)
- 🌍 Manzilga yetkazib berish

## 🚀 Oson O'rnatish (3 qadam)

### 1️⃣ Fayllarni yuklab oling
```bash
# Loyiha papkasiga o'ting
cd dostavka_bot
```

### 2️⃣ Environment sozlang
```bash
# .env faylini yarating (yoki mavjudini tahrirlang)
```

`.env` faylida faqat ushbu ma'lumotlarni kiriting:
```env
# Bot Token (BotFather dan oling)
BOT_TOKEN=your_telegram_bot_token

# MySQL parol (bo'sh bo'lsa, bo'sh qoldiring)
DB_PASSWORD=your_mysql_password

# Admin ID (telegram da /start bosib ID ni oling)
ADMIN_ID=your_telegram_user_id
```

### 3️⃣ Avtomatik setup ishga tushiring
```bash
python setup_mysql.py
```

**Hammasi! 🎉** Bot avtomatik ravishda:
- Zarur packagelarni tekshiradi
- MySQL serverga ulanadi
- Database yaratadi (agar yo'q bo'lsa)
- Jadvallarni yaratadi
- Standart mahsulotlarni qo'shadi
- Hamma narsani tekshiradi

### 4️⃣ Botni ishga tushiring
```bash
python bot.py
```

## 🛠 Qo'shimcha Sozlamalar

Agar standard sozlamalar mos kelmasa, `.env` da qo'shimcha parametrlar:

```env
# Database konfiguratsiyasi
DB_HOST=localhost          # MySQL server manzili
DB_PORT=3306              # MySQL port
DB_NAME=dostavka_bot      # Database nomi
DB_USER=root              # MySQL foydalanuvchi

# Qo'shimcha sozlamalar
DEBUG=false               # Debug rejimi
LOG_LEVEL=INFO           # Log darajasi
```

## 🔧 Muammolarni Hal Qilish

### MySQL ulanmayapti?
```bash
# Windows da:
net start mysql

# Linux/Mac da:
sudo systemctl start mysql
```

### Package yo'qmi?
```bash
pip install -r requirements.txt
```

### Database yaratilmayaptimi?
Setup script quyidagi xatolarni avtomatik aniqlaydi:
- ❌ MySQL server ishlamayapti
- ❌ Parol xato
- ❌ Ruxsat yo'q
- ❌ Package yo'q

## 📊 Loyiha Tuzilishi

```
dostavka_bot/
├── bot.py                 # Bot kirish nuqtasi
├── bot_utils.py           # Bot logikasi (MySQL bilan)
├── models.py              # Database modellari
├── database.py            # Avtomatik MySQL setup
├── setup_mysql.py         # O'rnatish scripti
├── migrate_to_mysql.py    # JSON dan ko'chirish (ixtiyoriy)
├── test_database.py       # Database test
├── requirements.txt       # Python dependencies
├── .env                   # Konfiguratsiya
└── README.md             # Bu fayl
```

## 🎮 Admin Komandalar

Bot ishga tushgandan keyin admin sifatida:

- 📦 **Buyurtmalar** - faol buyurtmalarni ko'rish
- ✍️ **Menyu tahrirlash** - mahsulot qo'shish/o'chirish  
- 📢 **Broadcast** - hammaga xabar yuborish
- ✉️ **Foydalanuvchiga yozish** - shaxsiy xabar
- ➕ **Admin qo'shish** - yangi admin tayinlash

## 🗄️ Database Arxitekturasi

### Jadvallar:
- **users** - Foydalanuvchi ma'lumotlari
- **categories** - Mahsulot kategoriyalari  
- **products** - Menyu elementi va narxlar
- **orders** - Mijoz buyurtmalari
- **order_items** - Buyurtma tarkibi
- **cart_items** - Savat mazmuni
- **admin_sessions** - Admin sessiyalari
- **admin_logs** - Admin amaliyotlar logi

## 🔄 JSON dan ko'chirish (Ixtiyoriy)

Agar sizda eski JSON fayllar mavjud bo'lsa:

```bash
python migrate_to_mysql.py
```

Bu script avtomatik ravishda:
- `users.json` → `users` jadvali
- `orders.json` → `orders` + `order_items` jadvallari  
- `menu.json` → `categories` + `products` jadvallari
- `carts.json` → `cart_items` jadvali

## 💡 Afzalliklar

### JSON vs MySQL:

| Xususiyat | JSON | MySQL |
|-----------|------|-------|
| Samaradorlik | 🐌 Sekin | ⚡ Tez |
| Xavfsizlik | 📄 Oddiy | 🔒 Professional |
| Backup | 🤔 Qo'lda | 🔄 Avtomatik |
| Scalability | 📈 Cheklangan | 🚀 Kengayuvchan |
| Concurrent Users | 👤 1 | 👥 Ko'p |
| Reporting | ❌ Yo'q | 📊 SQL |

## 📞 Yordam

Muammo bo'lsa:

1. **Setup script ishga tushiring**: `python setup_mysql.py`
2. **Database test qiling**: `python test_database.py`  
3. **Log faylni ko'ring**: `bot.log`
4. **Environment tekshiring**: `.env` fayl to'g'rimi?

## 🎯 Keyingi Bosqichlar

Bot ishga tushgandan keyin qo'shishingiz mumkin:

- 💳 **To'lov tizimlari** - Click, Payme
- 📊 **Statistika** - sotuvlar hisoboti
- 🔔 **SMS bildirishnomalar** 
- 🖼️ **Rasm yuklash** - mahsulot rasmlari
- 🏪 **Ko'p filiallar** - turli manzillar

## 📄 Litsenziya

MIT License - erkin foydalanish va o'zgartirish.

---

**🎉 Botingiz tayyor! Yaxshi biznes!** 🚀