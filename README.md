# delivery_bot

Telegram delivery bot (Fast Food) — buyurtma, kuryer va admin oqimlari bilan.

Quick start

1. Create a virtual environment and install deps:

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

2. Set environment variable `BOT_TOKEN` or edit `bot.py` (recommended: use env var):

```powershell
setx BOT_TOKEN "<your-token-here>"
```

3. Run the bot:

```bash
python bot.py
```

Notes:
- Data files: `users.json`, `orders.json`, `couriers.json`, `earnings.json` are stored next to the script. They are ignored in `.gitignore` by default to avoid leaking runtime data.
- Add your `BUYURTMALAR_CHANNEL_ID` and `SUPERADMIN_CHANNEL_ID` in `bot.py` or set them via environment if you refactor.
