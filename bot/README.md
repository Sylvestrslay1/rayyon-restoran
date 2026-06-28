# Rayyon Telegram Bot

To'liq restoran boti — mijoz buyurtma va bron, xodim panel, admin boshqaruv, proaktiv bildirishnomalar.

## Fayl tuzilmasi

```
bot/
  bot.py           ← Asosiy kirish nuqtasi: routing + poll loop
  core.py          ← Umumiy: API, Telegram, holat, kesh, yordamchilar
  admin.py         ← Admin menyu, hisobotlar, smenalar
  customer.py      ← Mijoz boti: menyu, buyurtma, bron, ball
  staff.py         ← Xodim boti: login, ofitsiant, oshpaz, kassir
  notifications.py ← Fon bildirishnomalar thread
  requirements.txt ← (Standart kutubxona ishlatiladi, paket kerak emas)
```

## Muhit o'zgaruvchilari

| O'zgaruvchi | Majburiy | Tavsif |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | BotFather dan olingan token |
| `RAYYON_ADMIN_PASS` | ✅ | Admin paroli (backend bilan bir xil) |
| `RAYYON_API_URL` | ✅ | Backend URL |
| `TELEGRAM_CHAT_ID` | Tavsiya | Admin chat ID lari (vergul bilan, masalan: `123,456`) |
| `DAILY_REPORT_HOUR` | Ixtiyoriy | Kunlik hisobot soati (standart: `22`) |
| `NOTIF_INTERVAL` | Ixtiyoriy | Bildirishnoma intervali soniyada (standart: `60`) |

## Sozlash

### 1. Bot yaratish
1. `@BotFather` ga `/newbot` yozing
2. Nom bering → token oling: `1234567890:ABCdef...`

### 2. Chat ID olish
1. Botga direct xabar yozing
2. `https://api.telegram.org/bot<TOKEN>/getUpdates` dan `"chat": {"id": ...}` oling

### 3. Ishga tushirish

**Windows:**
```bat
set TELEGRAM_BOT_TOKEN=<token>
set TELEGRAM_CHAT_ID=<chat_id>
set RAYYON_API_URL=https://rayyon-restoran.onrender.com
set RAYYON_ADMIN_PASS=<parol>
python bot/bot.py
```

**Linux/Mac:**
```bash
export TELEGRAM_BOT_TOKEN=<token>
export TELEGRAM_CHAT_ID=<chat_id>
export RAYYON_API_URL=https://rayyon-restoran.onrender.com
export RAYYON_ADMIN_PASS=<parol>
python bot/bot.py
```

### 4. Render.com da ishga tushirish
- **Build Command:** `pip install -r bot/requirements.txt`
- **Start Command:** `python bot/bot.py`

## Buyruqlar

### Hamma uchun
| Buyruq | Tavsif |
|---|---|
| `/start`, `/help` | Bosh menyu (admin yoki mijoz) |
| `/menu` | Taomlar katalogi (buyurtma berish) |
| `/bron` | Stol bron qilish |
| `/ball` | Loyalty ball va daraja ko'rish |
| `/xodim` | Xodim paneliga kirish (PIN orqali) |
| `/cancel` | Joriy oqimni bekor qilish |

### Faqat adminlar uchun
| Buyruq | Tavsif |
|---|---|
| `/orders` | Yangi QR buyurtmalar |
| `/reservations` | Yangi/tasdiqlangan bronlar |
| `/stollar` | Hozir band stollar |
| `/smena` | Ochiq smenalar |
| `/inventar` | Kam bo'lib ketgan mahsulotlar |
| `/mijozlar` | Top 10 mijoz |
| `/bugun` | Bugungi daromad/foyda |
| `/hafta` | Haftalik hisobot (kunlar grafigi) |
| `/oy` | Oylik hisobot |
| `/xodimlar` | Aktiv xodimlar ro'yxati |

## Proaktiv bildirishnomalar (avtomatik)

Bot har `NOTIF_INTERVAL` soniyada quyidagilarni tekshirib, xabar yuboradi:

| Hodisa | Qachon xabar keladi |
|---|---|
| 📅 Yangi bron | Saytdan bron qilingan zahoti |
| 📦 Yangi buyurtma | QR menyu orqali buyurtma berilganda |
| 🧾 Hisob so'rash | Stol kassirga hisob so'raganda |
| ⚠️ Kam inventar | Birinchi aniqlanganda (kun davomida bir marta) |
| 📊 Kunlik hisobot | Har kuni `DAILY_REPORT_HOUR` soatda avtomatik |

## Rol tizimi (`_user_roles`)

Bot har foydalanuvchi chat ID si uchun rolni eslab qoladi:
- **Admin** — `TELEGRAM_CHAT_ID` da ro'yxatdagi chat ID lar
- **Staff** — PIN bilan kirgan xodimlar (`/start` bosganda xodim paneliga qaytadi)
- **Customer** — boshqa barcha foydalanuvchilar

## Xavfsizlik

- `bot/config.py` `.gitignore` ga qo'shilgan — hech qachon GitHub ga pushlanmaydi
- Admin callbacklari faqat `TELEGRAM_CHAT_ID` da ko'rsatilgan chatlarga ishlaydi
- Mijoz va xodim callbacklari barcha chatlarga ochiq (c_ va s_ prefikslar)
