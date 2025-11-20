# Telegram Delivery Bot - Ma'lumotlar bazasi bilan

Bu loyiha to'liq funksional yetkazib berish boti bo'lib, MySQL ma'lumotlar bazasi bilan ishlaydi.

## 🚀 Xususiyatlari

- ✅ **To'liq ma'lumotlar bazasi integratsiyasi** (MySQL + SQLAlchemy)
- ✅ **Foydalanuvchilar boshqaruvi** (ro'yxatdan o'tish, profil)
- ✅ **Mahsulotlar katalogi** (kategoriyalar, qidiruv)
- ✅ **Savat tizimi** (qo'shish, o'chirish, miqdorni o'zgartirish)
- ✅ **Buyurtma jarayoni** (telefon, manzil, tasdiqlash)
- ✅ **Admin panel** (buyurtmalarni boshqarish)
- ✅ **Real-time xabarlar** (mijoz va admin o'rtasida)

## 📋 Talablar

- Python 3.8+
- MySQL 5.7+ yoki MariaDB
- Telegram Bot Token

## 🔧 O'rnatish

### 1. Repository'ni klonlash
```bash
git clone https://github.com/sardorbek0648/delivery_bot.git
cd delivery_bot
```

### 2. Virtual environment yaratish
```bash
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate
```

### 3. Kutubxonalarni o'rnatish
```bash
pip install -r requirements.txt
```

### 4. Ma'lumotlar bazasini sozlash

#### MySQL o'rnatish (Windows):
1. [MySQL Community Server](https://dev.mysql.com/downloads/mysql/) yuklab oling
2. O'rnatish jarayonida root parolini o'rnating
3. MySQL Workbench o'rnating (ixtiyoriy)

#### Ma'lumotlar bazasini yaratish:
```bash
python setup_database.py
```

### 5. Konfiguratsiya fayli yaratish
```bash
# .env.example faylini .env ga nusxalang
cp .env.example .env
```

`.env` faylini tahrirlang:
```env
# MySQL ma'lumotlar bazasi
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_mysql_password
DB_NAME=delivery_bot

# Telegram Bot Token (@BotFather dan olinadi)
BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrSTUvwxyz

# Admin user ID'lari
ADMIN_IDS=123456789,987654321

DEBUG=False
TIMEZONE=Asia/Tashkent
```

### 6. Telegram Bot yaratish
1. [@BotFather](https://t.me/botfather) ga murojaat qiling
2. `/newbot` buyrug'ini yuboring
3. Bot nomi va username'ini kiriting
4. Olingan tokenni `.env` fayliga yozing

### 7. Botni ishga tushirish
```bash
python database_bot.py
```

## 📁 Fayl tuzilishi

```
delivery_bot/
├── models.py              # Ma'lumotlar bazasi modellari
├── database.py            # Database boshqaruv servislari
├── database_bot.py        # Asosiy bot kodi
├── setup_database.py      # Database o'rnatish skripti
├── requirements.txt       # Python kutubxonalari
├── .env.example          # Konfiguratsiya namunasi
├── .env                  # Konfiguratsiya fayli (o'zingiz yarating)
└── README_DATABASE.md    # Ushbu fayl
```

## 🗃️ Ma'lumotlar bazasi sxemasi

### Jadvallar:
- **users** - Foydalanuvchilar
- **categories** - Mahsulot kategoriyalari  
- **products** - Mahsulotlar
- **orders** - Buyurtmalar
- **order_items** - Buyurtma elementlari
- **cart_items** - Savat elementlari
- **admin_sessions** - Admin sessiyalari
- **admin_logs** - Admin amaliyotlari

## 🎮 Foydalanish

### Foydalanuvchi uchun:
1. `/start` - Botni ishga tushirish
2. **🍽️ Menyu** - Mahsulotlar katalogi
3. **🛒 Savat** - Tanlangan mahsulotlar
4. **📋 Buyurtmalarim** - Buyurtmalar tarixi

### Admin uchun:
- Yangi buyurtmalar haqida avtomatik xabarlar
- Buyurtmalarni tasdiqlash/rad etish
- Buyurtma holatini yangilash

## 🔄 Asosiy funksiyalar

### Mahsulot qo'shish (Admin):
```python
# Kategoriya yaratish
category = category_service.create_category("🍕 Pizza", "Mazali pitsalar")

# Mahsulot qo'shish  
product = product_service.create_product(
    name="Margarita Pizza",
    price=45000,
    category_id=category.id,
    description="Pomidor sousi, mozzarella pishloqi, bazilika"
)
```

### Buyurtma jarayoni:
1. **Mahsulot tanlash** → Savat
2. **Telefon raqam** → Aloqa ma'lumoti
3. **Manzil** → Yetkazib berish joyi
4. **Tasdiqlash** → Buyurtma yaratish
5. **Admin tasdiqi** → Jarayon yakunlanishi

## 🚨 Muammolarni hal qilish

### Ma'lumotlar bazasi ulanishi:
```bash
# Ulanishni tekshirish
python -c "from database import initialize_database; initialize_database()"
```

### MySQL xatoliklari:
1. MySQL service ishga tushirish:
   ```bash
   # Windows
   net start mysql
   ```

2. Parolni tekshirish:
   ```bash
   mysql -u root -p
   ```

3. Ma'lumotlar bazasi mavjudligini tekshirish:
   ```sql
   SHOW DATABASES;
   USE delivery_bot;
   SHOW TABLES;
   ```

### Bot xatoliklari:
- Bot tokenini tekshiring
- Internet ulanishini tekshiring  
- Admin ID'larini to'g'rilang

## 📊 Monitoring va Logs

Bot ishini kuzatish:
```bash
# Log faylini ko'rish
tail -f bot.log

# Ma'lumotlar bazasi holatini tekshirish  
python -c "
from database import db_manager
print('DB Status:', db_manager.test_connection())
"
```

## 🔐 Xavfsizlik

- `.env` faylini git'ga qo'shmang
- MySQL parolini kuchli qiling
- Admin ID'larini faqat ishonchli odamlarga bering
- Ma'lumotlar bazasini muntazam backup qiling

## 📈 Kengaytirish

Qo'shimcha funksiyalar qo'shish mumkin:
- To'lov tizimlari (Click, Payme)
- Geolokatsiya bilan yetkazib berish masofasi
- Mahsulot rasmlari
- Aksiya va chegirmalar
- Yetkazib beruvchilar tizimi
- Hisobot va statistika

## 🤝 Yordam

Savollar yoki muammolar bo'lsa:
1. Issues bo'limiga murojaat qiling
2. Telegram: [@your_support_bot](https://t.me/your_support_bot)
3. Email: support@delivery.uz

## 📄 Litsenziya

MIT License - batafsil ma'lumot uchun LICENSE faylini ko'ring.

---
**Muvaffaqiyatli ishlatish! 🚀🍕**