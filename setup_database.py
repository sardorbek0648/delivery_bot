# Ma'lumotlar bazasi o'rnatish skripti

import mysql.connector
from mysql.connector import Error
import os
from dotenv import load_dotenv

load_dotenv()

def create_database():
    """MySQL ma'lumotlar bazasini yaratish"""
    
    # MySQL ulanish ma'lumotlari
    host = os.getenv('DB_HOST', 'localhost')
    port = int(os.getenv('DB_PORT', 3306))
    user = os.getenv('DB_USER', 'root')
    password = os.getenv('DB_PASSWORD', '')
    database_name = os.getenv('DB_NAME', 'delivery_bot')
    
    try:
        # MySQL serveriga ulanish (ma'lumotlar bazasisiz)
        connection = mysql.connector.connect(
            host=host,
            port=port,
            user=user,
            password=password
        )
        
        if connection.is_connected():
            cursor = connection.cursor()
            
            # Ma'lumotlar bazasini yaratish
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {database_name} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            print(f"✅ Ma'lumotlar bazasi '{database_name}' muvaffaqiyatli yaratildi!")
            
            # Foydalanuvchiga ruxsat berish (agar kerak bo'lsa)
            cursor.execute(f"GRANT ALL PRIVILEGES ON {database_name}.* TO '{user}'@'localhost'")
            cursor.execute("FLUSH PRIVILEGES")
            
            cursor.close()
            connection.close()
            return True
            
    except Error as e:
        print(f"❌ MySQL xatoligi: {e}")
        return False
    
    except Exception as e:
        print(f"❌ Xatolik: {e}")
        return False

def test_connection():
    """Ma'lumotlar bazasi ulanishini tekshirish"""
    
    host = os.getenv('DB_HOST', 'localhost')
    port = int(os.getenv('DB_PORT', 3306))
    user = os.getenv('DB_USER', 'root')
    password = os.getenv('DB_PASSWORD', '')
    database_name = os.getenv('DB_NAME', 'delivery_bot')
    
    try:
        connection = mysql.connector.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database_name
        )
        
        if connection.is_connected():
            print(f"✅ Ma'lumotlar bazasiga muvaffaqiyatli ulandi!")
            connection.close()
            return True
            
    except Error as e:
        print(f"❌ Ulanishda xatolik: {e}")
        return False

if __name__ == "__main__":
    print("🔧 Ma'lumotlar bazasini sozlash...")
    
    if create_database():
        if test_connection():
            print("✅ Barcha sozlamalar muvaffaqiyatli!")
            print("\nKeyingi qadamlar:")
            print("1. .env faylini to'ldiring")
            print("2. pip install -r requirements.txt")
            print("3. python database_bot.py")
        else:
            print("❌ Ulanishni tekshirishda muammo!")
    else:
        print("❌ Ma'lumotlar bazasini yaratishda muammo!")