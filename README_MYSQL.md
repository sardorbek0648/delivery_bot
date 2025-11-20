# Dostavka Bot - MySQL Integration

Telegram bot for food delivery with MySQL database integration.

## Features

- 🍕 Product catalog with categories
- 🛒 Shopping cart functionality
- 📱 Order management system
- 👤 User profiles and history
- 🔐 Admin panel with statistics
- 💾 MySQL database for data persistence
- 🌍 Location-based delivery

## Requirements

- Python 3.8+
- MySQL 5.7+ or MariaDB 10.3+
- Telegram Bot Token

## Installation

### 1. Clone and Setup

```bash
git clone <your-repo>
cd dostavka_bot
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Database Setup

**Install MySQL:**

On Windows:
- Download MySQL from https://dev.mysql.com/downloads/mysql/
- Install MySQL Server and MySQL Workbench

On Ubuntu/Debian:
```bash
sudo apt update
sudo apt install mysql-server
sudo mysql_secure_installation
```

**Create Database:**
```sql
CREATE DATABASE dostavka_bot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'bot_user'@'localhost' IDENTIFIED BY 'your_password';
GRANT ALL PRIVILEGES ON dostavka_bot.* TO 'bot_user'@'localhost';
FLUSH PRIVILEGES;
```

### 4. Environment Configuration

Copy `.env.example` to `.env`:
```bash
copy .env.example .env  # Windows
cp .env.example .env    # Linux/Mac
```

Edit `.env` file:
```env
BOT_TOKEN=your_telegram_bot_token
DB_HOST=localhost
DB_PORT=3306
DB_NAME=dostavka_bot
DB_USER=bot_user
DB_PASSWORD=your_password
ADMIN_ID=your_telegram_user_id
```

### 5. Migrate Existing Data (Optional)

If you have existing JSON data:
```bash
python migrate_to_mysql.py
```

### 6. Initialize Database

```bash
python -c "from database import init_database; init_database()"
```

### 7. Run Bot

```bash
python bot.py
```

## Project Structure

```
dostavka_bot/
├── bot.py              # Bot entry point
├── bot_utils.py        # Bot logic and handlers
├── models.py           # SQLAlchemy database models
├── database.py         # Database connection and utilities
├── migrate_to_mysql.py # Migration script from JSON
├── requirements.txt    # Python dependencies
├── .env               # Environment variables
└── README.md          # This file
```

## Database Schema

### Tables:
- **users**: User profiles and contact info
- **categories**: Product categories
- **products**: Menu items with prices
- **orders**: Customer orders
- **order_items**: Order line items
- **cart_items**: Shopping cart contents
- **admin_sessions**: Admin panel sessions
- **admin_logs**: Admin action logs

## Admin Commands

- `/start` - Start the bot
- `/help` - Show help message
- Admin panel available for configured admin users

## Deployment

### Using systemd (Linux):

Create service file `/etc/systemd/system/dostavka-bot.service`:
```ini
[Unit]
Description=Dostavka Telegram Bot
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/dostavka_bot
Environment=PATH=/path/to/venv/bin
ExecStart=/path/to/venv/bin/python bot.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable dostavka-bot.service
sudo systemctl start dostavka-bot.service
```

### Using Docker:

```dockerfile
FROM python:3.9-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
CMD ["python", "bot.py"]
```

## Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

## License

This project is licensed under the MIT License.

## Support

For support, contact [@your_telegram] or create an issue.