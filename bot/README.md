# Rayyon Telegram Bot

Buyurtmalar va bronlar uchun Telegram bildirishnomalar boti.

## Sozlash

### 1. Bot yaratish
1. Telegram da `@BotFather` ga yozing
2. `/newbot` → nom bering → `@rayyon_restoran_bot`
3. Token oling: `1234567890:ABCdef...`

### 2. Chat ID olish
Bot yaratilgandan keyin:
1. Botni guruhga qo'shing yoki direct message yozing
2. `https://api.telegram.org/bot<TOKEN>/getUpdates` oching
3. `chat.id` ni oling

### 3. Render.com da muhit o'zgaruvchilarini qo'shish
Render dashboard → rayyon-restoran → Environment:
```
TELEGRAM_BOT_TOKEN = 1234567890:ABCdef...
TELEGRAM_CHAT_ID   = -1001234567890
```

### 4. Botni local ishga tushirish
```bash
set TELEGRAM_BOT_TOKEN=<token>
set TELEGRAM_CHAT_ID=<chat_id>
set RAYYON_API_URL=https://rayyon-restoran.onrender.com
set RAYYON_ADMIN_PASS=rayyon2024
python bot/bot.py
```

## Komandalar
- `/start` — Bosh menyu
- `/orders` — Yangi buyurtmalar
- `/reservations` — Yangi bronlar

## Ishlash prinsipi
- Saytda buyurtma yoki bron qilinsa → Telegram ga xabar keladi
- Xabar ostidagi tugmalar orqali status o'zgartiriladi
- Admin panel bilan sinxronlashadi
