# Rayyon Restoran — Boshqaruv Tizimi

Flask + PostgreSQL / SQLite asosidagi to'liq restoran avtomatlashtirish tizimi.  
Real-time oshxona ekrani (KDS), kassir, ofitsiant, admin panel va mijoz QR-menyu o'z ichiga oladi.

---

## Mundarija

- [Loyiha haqida](#loyiha-haqida)
- [Imkoniyatlar](#imkoniyatlar)
- [Fayl tuzilmasi](#fayl-tuzilmasi)
- [Texnologiyalar](#texnologiyalar)
- [Lokal ishga tushirish](#lokal-ishga-tushirish)
- [Render.com deploy](#rendercom-deploy)
- [Muhit o'zgaruvchilari](#muhit-ozgaruvchilari)
- [Xodim rollari va kirish](#xodim-rollari-va-kirish)
- [API endpointlar](#api-endpointlar)
- [Ma'lumotlar bazasi](#malumotlar-bazasi)
- [Xavfsizlik](#xavfsizlik)
- [Telegram bildirishnomalar](#telegram-bildirishnomalar)

---

## Loyiha haqida

Rayyon — o'zbek restorani uchun yozilgan ichki boshqaruv tizimi. Tizim to'rtta asosiy rolga bo'lingan:

| Panel | Maqsad |
|-------|--------|
| **Admin panel** | Menyu, xodimlar, moliya, inventar, hisobotlar |
| **Kassir** | Stol ochish, buyurtma qabul qilish, to'lov |
| **Oshxona (KDS)** | Real-time buyurtmalar ko'rinishi, tayyor/bekor belgilash |
| **Ofitsiant** | Mobil qurilmada stol xizmati, tayyor taomlarni ko'rish |

Mijozlar QR-kod orqali menyuni ko'rishi va buyurtma berishi mumkin (`menu.html`).

---

## Imkoniyatlar

**Kassir va stollar**
- PIN-kod orqali tizimga kirish (PBKDF2-SHA256, 200 000 iteratsiya)
- Smena ochish / yopish va smena hisoboti
- Stol ochish, buyurtma qo'shish, void qilish
- To'lov: naqd, karta, aralash (split)
- Mijoz qidirish (telefon raqami bo'yicha) — avtomatik chegirma
- Chek chop etish, PDF hisobot

**Oshxona (KDS)**
- Server-Sent Events (SSE) orqali real-time yangilanish
- Buyurtma holati: `pending` → `cooking` → `ready` → `served`
- Tayyor taomda Telegram xabar

**Admin panel**
- Menyu boshqaruvi (kategoriyalar, narxlar, rasm yuklash, stop-list)
- Xodimlar: ro'yxat, rol tayinlash, PIN almashtirish, davomatni kuzatish
- Inventar va retseptlar — taom pishirilganda avtomatik chiqarish
- Moliya: xarajatlar, to'lovlar, oy/hafta/kun hisobotlari
- Galereya, yangiliklar, aktsiyalar
- Analitika: eng ko'p sotilgan taomlar, daromad grafigi, mijozlar statistikasi

**Mijoz QR-menyu**
- Telefonda `menu.html` ochiladi, kategoriyalar bo'yicha filtrlash
- Savatga qo'shish va buyurtma berish

---

## Fayl tuzilmasi

```
rayyon-restaurant/
│
├── backend/
│   ├── app.py              # Flask API — 90+ endpoint
│   ├── database.py         # DB schema, migratsiyalar, get_conn()
│   ├── requirements.txt    # Python paketlar
│   ├── migrate_pins.py     # Eski SHA256 PIN → PBKDF2 ko'chirish skripti
│   └── uploads/            # Yuklangan rasmlar (menyu, galereya)
│
├── admin/
│   ├── index.html          # Admin bosh panel (3000+ qator, SPA)
│   └── login.html          # Admin login sahifasi
│
├── css/
│   └── style.css           # Asosiy sayt uslubi
│
├── js/
│   └── main.js             # Asosiy sayt JS
│
├── cashier.html            # Kassir paneli (PIN, smena, to'lov)
├── kitchen.html            # Oshxona KDS ekrani
├── waiter.html             # Ofitsiant mobil paneli
├── menu.html               # Mijoz QR-menyu
├── staff-login.html        # Xodim umumiy kirish portali
├── checkin.html            # Xodim davomat belgisi
├── loyalty-card.html       # Mijoz sodiqlik kartasi
├── index.html              # Asosiy veb-sayt (landing page)
│
├── sw.js                   # Service Worker (PWA offline)
├── manifest.json           # PWA manifest
├── favicon.ico
├── render.yaml             # Render.com deploy konfiguratsiya
├── runtime.txt             # Python versiya (Render uchun)
├── start.bat               # Windows da lokal ishga tushirish
└── README.md
```

---

## Texnologiyalar

| Qatlam | Texnologiya |
|--------|-------------|
| Backend | Python 3.11, Flask 3.0 |
| Ma'lumotlar bazasi | PostgreSQL (production), SQLite (lokal) |
| PG driver | pg8000 (C-extension yo'q, Render ga mos) |
| Deploy | Render.com (gunicorn, 1 worker) |
| Auth | HMAC token (4 soat TTL), PBKDF2 PIN |
| Real-time | Server-Sent Events (SSE) |
| Rate limiting | flask-limiter |
| Rasm yuklash | werkzeug secure_filename, max 10 MB |
| Cache | Redis (ixtiyoriy, multi-worker uchun) |
| PWA | Service Worker + Web App Manifest |
| Frontend | Vanilla JS + CSS (framework yo'q) |

---

## Lokal ishga tushirish

### Talablar
- Python 3.10+
- pip

### 1. Repozitoriyni klonlash

```bash
git clone https://github.com/username/rayyon-restaurant.git
cd rayyon-restaurant
```

### 2. Paketlarni o'rnatish

```bash
pip install -r backend/requirements.txt
```

### 3. Muhit o'zgaruvchilarini sozlash

```bash
# Windows (PowerShell)
$env:ADMIN_PASSWORD = "kuchli_parolni_bu_yerga_yozing"
$env:SECRET_KEY = "ixtiyoriy_uzun_kalit"

# Linux / Mac
export ADMIN_PASSWORD="kuchli_parolni_bu_yerga_yozing"
export SECRET_KEY="ixtiyoriy_uzun_kalit"
```

`ADMIN_PASSWORD` o'rnatilmasa — admin panelga kirish bloklanadi (xavfsizlik).

### 4. Serverni ishga tushirish

```bash
cd backend
python app.py
```

Yoki Windows da loyiha ildizidan:

```
start.bat
```

Brauzerda: **http://localhost:5000**

### 5. Admin ga kirish

- **URL:** `http://localhost:5000/admin/login.html`
- **Parol:** `ADMIN_PASSWORD` ga o'rnatgan qiymat

### 6. Kassir / Ofitsiant

- Avval admin panelda xodim yarating (Xodimlar bo'limi) va PIN bering
- **Kassir:** `http://localhost:5000/cashier.html`
- **Oshxona:** `http://localhost:5000/kitchen.html`
- **Ofitsiant:** `http://localhost:5000/waiter.html`
- **Xodim portali:** `http://localhost:5000/staff-login.html`

---

## Render.com Deploy

### Bir martalik sozlash

1. GitHub repozitoriyini Render ga ulang
2. `render.yaml` avtomatik aniqlanadi — "Apply" tugmasini bosing
3. PostgreSQL ma'lumotlar bazasi avtomatik yaratiladi (`rayyon-db`)
4. **Render Dashboard → Environment** bo'limida quyidagilarni qo'lda o'rnating:

| Kalit | Qiymat | Majburiy |
|-------|--------|----------|
| `ADMIN_PASSWORD` | Kamida 12 belgili kuchli parol | **Ha** |

Qolgan kalitlar (`SECRET_KEY`, `KITCHEN_TOKEN`, `DATABASE_URL`) `render.yaml` da avtomatik generatsiya qilinadi.

### Yangilash

GitHub `main` branchiga push qilish bilan Render avtomatik qayta deploy qiladi (`autoDeploy: true`).

### Health check

Render serverning tirikligini `/api/health` orqali tekshiradi. Bu endpoint haqiqiy DB query (`SELECT 1`) bajaradi va natijani qaytaradi.

---

## Muhit O'zgaruvchilari

| Kalit | Maqsad | Majburiy |
|-------|--------|----------|
| `ADMIN_PASSWORD` | Admin panel kirish paroli | **Ha** |
| `SECRET_KEY` | Flask sessiya shifrlash kaliti | Tavsiya |
| `DATABASE_URL` | PostgreSQL ulanish URL (Render avtomatik) | Prod da Ha |
| `ALLOWED_ORIGINS` | CORS ruxsat berilgan domenlar, vergul bilan | Tavsiya |
| `KITCHEN_TOKEN` | Oshxona ekrani autentifikatsiya tokeni | Ixtiyoriy |
| `REDIS_URL` | Redis ulanish URL (multi-worker uchun) | Ixtiyoriy |
| `TELEGRAM_BOT_TOKEN` | Telegram bot tokeni | Ixtiyoriy |
| `TELEGRAM_CHAT_ID` | Xabar yuborish uchun chat ID | Ixtiyoriy |
| `FLASK_ENV` | `production` yoki `development` | Ixtiyoriy |
| `SMTP_HOST` | Email bildirishnomalar uchun | Ixtiyoriy |
| `SMTP_PORT` | SMTP port (odatda 587) | Ixtiyoriy |
| `SMTP_USER` | SMTP foydalanuvchi | Ixtiyoriy |
| `SMTP_PASS` | SMTP parol | Ixtiyoriy |

> **Diqqat:** `ALLOWED_ORIGINS` o'rnatilmasa CORS barcha domenga ochiq bo'ladi — production da albatta o'rnating.

---

## Xodim Rollari va Kirish

Tizimda ikki xil kirish usuli mavjud:

### 1. Admin token (email/parol)
Admin login sahifasida parol bilan kiradi. Token 4 soat amal qiladi.

| Rol | Kirish joyi | Ruxsatlar |
|-----|-------------|-----------|
| `admin` | `/admin/login.html` | Hamma narsa |
| `director` | `/admin/login.html` | Hamma narsa |
| `manager` | `/admin/login.html` | Menyu, hisobot, xodimlar |
| `chef` | `/admin/login.html` | Menyu, retsept, inventar |
| `accountant` | `/admin/login.html` | Moliya, hisobot |

### 2. PIN-kod (xodim)
4-6 xonali PIN bilan kiradi. Brute-force himoya: 5 ta noto'g'ri kirishdan so'ng 15 daqiqa bloklash.

| Rol | Kirish joyi | Ruxsatlar |
|-----|-------------|-----------|
| `cashier` | `/cashier.html` | Stol, buyurtma, to'lov, smena |
| `waiter` | `/waiter.html` | Stol ko'rish, buyurtma, tayyor taomlar |
| `kitchen` / `cook` | `/kitchen.html` | Buyurtmalar holati |

---

## API Endpointlar

Barcha API endpointlari `/api/` prefiksi bilan boshlanadi.

### Autentifikatsiya

| Metod | URL | Tavsif | Auth |
|-------|-----|--------|------|
| POST | `/api/login` | Admin login (parol) | Yo'q |
| POST | `/api/logout` | Tokenni o'chirish | Token |
| GET | `/api/auth/check` | Token haqiqiyligini tekshirish | Token |
| POST | `/api/staff/login` | Xodim PIN login | Yo'q |

### Menyu

| Metod | URL | Tavsif | Auth |
|-------|-----|--------|------|
| GET | `/api/menu` | Menyu ro'yxati (kategoriya filtri) | Yo'q |
| POST | `/api/menu` | Yangi taom qo'shish | Token |
| PUT | `/api/menu/<id>` | Taomni tahrirlash | Token |
| DELETE | `/api/menu/<id>` | Taomni o'chirish | Token |
| PUT | `/api/menu/<id>/stoplist` | Stop-list on/off | Token |

### Stollar

| Metod | URL | Tavsif | Auth |
|-------|-----|--------|------|
| GET | `/api/tables` | Barcha stollar holati | Token |
| POST | `/api/tables` | Yangi stol qo'shish | Token |
| PUT | `/api/tables/<id>` | Stol nomini tahrirlash | Token |
| DELETE | `/api/tables/<id>` | Stolni o'chirish | Token |

### Sessiyalar (Stollar xizmati)

| Metod | URL | Tavsif | Auth |
|-------|-----|--------|------|
| POST | `/api/session/open` | Stol ochish | PIN |
| GET | `/api/session/validate` | Sessiya tekshirish | PIN |
| GET | `/api/session/<id>` | Sessiya ma'lumotlari | PIN |
| POST | `/api/session/<id>/order` | Buyurtma qo'shish | PIN |
| POST | `/api/session/<id>/bill` | Hisob-kitob | PIN |
| POST | `/api/session/<id>/close` | To'lov va yopish | PIN |
| PUT | `/api/session/<id>/discount` | Chegirma o'rnatish | PIN |
| PUT | `/api/session/<sid>/item/<iid>/status` | Item holati o'zgartirish | PIN |
| POST | `/api/session/<sid>/item/<iid>/void` | Itemni void qilish | PIN |
| GET | `/api/receipt/<id>` | Chek HTML | Yo'q |

### Smena

| Metod | URL | Tavsif | Auth |
|-------|-----|--------|------|
| POST | `/api/shift/open` | Yangi smena ochish | PIN |
| POST | `/api/shift/current` | Joriy smena ma'lumoti | PIN |
| POST | `/api/shift/<id>/close` | Smenani yopish | PIN |
| POST | `/api/shift/<id>/report` | Smena hisoboti | PIN |
| GET | `/api/shifts` | Smena tarixi | Token |

### Oshxona

| Metod | URL | Tavsif | Auth |
|-------|-----|--------|------|
| GET | `/api/kitchen` | Faol buyurtmalar | Kitchen Token |
| GET | `/api/kitchen/ready` | Tayyor taomlar soni | PIN |
| GET | `/api/events` | SSE real-time oqim | Yo'q |

### Xodimlar

| Metod | URL | Tavsif | Auth |
|-------|-----|--------|------|
| GET | `/api/staff` | Xodimlar ro'yxati | Token |
| POST | `/api/staff` | Xodim qo'shish | Token |
| PUT | `/api/staff/<id>` | Xodimni tahrirlash | Token |
| DELETE | `/api/staff/<id>` | Xodimni o'chirish | Token |
| POST | `/api/staff/checkin` | Davomat belgisi | PIN |
| GET | `/api/attendance` | Davomat tarixi | Token |
| GET | `/api/staff/payroll` | Maosh hisobi | Token |

### Moliya va Hisobotlar

| Metod | URL | Tavsif | Auth |
|-------|-----|--------|------|
| GET | `/api/stats` | Kunlik statistika | Token |
| GET | `/api/analytics` | Analitika (period) | Token |
| GET | `/api/analytics/summary` | Batafsil tahlil | Token |
| GET | `/api/accounting/report` | Moliya hisoboti | Token |
| GET | `/api/payments` | To'lovlar tarixi | Token |
| GET | `/api/expenses` | Xarajatlar | Token |
| POST | `/api/expenses` | Xarajat qo'shish | Token |
| DELETE | `/api/expenses/<id>` | Xarajat o'chirish | Token |

### Inventar

| Metod | URL | Tavsif | Auth |
|-------|-----|--------|------|
| GET | `/api/inventory` | Mahsulotlar ro'yxati | Token |
| POST | `/api/inventory` | Mahsulot qo'shish | Token |
| PUT | `/api/inventory/<id>` | Miqdor/narx yangilash | Token |
| DELETE | `/api/inventory/<id>` | Mahsulot o'chirish | Token |
| GET | `/api/inventory/log` | Harakatlar tarixi | Token |
| GET | `/api/recipes` | Retseptlar | Token |
| POST | `/api/recipes` | Retsept qo'shish | Token |
| DELETE | `/api/recipes/<id>` | Retsept o'chirish | Token |

### Mijozlar (Sodiqlik tizimi)

| Metod | URL | Tavsif | Auth |
|-------|-----|--------|------|
| GET | `/api/customers` | Mijozlar ro'yxati | Token |
| POST | `/api/customers` | Yangi mijoz | Token |
| PUT | `/api/customers/<id>` | Mijoz tahrirlash | Token |
| DELETE | `/api/customers/<id>` | Mijoz o'chirish | Token |
| GET | `/api/customers/lookup?phone=...` | Telefon bo'yicha qidirish | Yo'q |

### Boshqa

| Metod | URL | Tavsif | Auth |
|-------|-----|--------|------|
| GET | `/api/health` | Server va DB holati | Yo'q |
| GET | `/api/settings` | Tizim sozlamalari | Token |
| PUT | `/api/settings` | Sozlamalarni saqlash | Token |
| POST | `/api/upload` | Rasm yuklash | Token |
| GET | `/api/news` | Yangiliklar | Yo'q |
| POST | `/api/news` | Yangilik qo'shish | Token |
| GET | `/api/reservations` | Bronlar | Token |
| POST | `/api/reservations` | Bron qilish | Yo'q |
| GET | `/api/promotions` | Aktsiyalar | Yo'q |
| GET | `/api/gallery` | Galereya | Yo'q |
| GET | `/api/orders` | Buyurtmalar tarixi | Token |

---

## Ma'lumotlar Bazasi

Loyiha ikki rejimda ishlaydi:

- **Lokal:** SQLite (`backend/rayyon.db`) — sozlashsiz ishlaydi
- **Production:** PostgreSQL (pg8000 kutubxonasi orqali)

`DATABASE_URL` o'rnatilgan bo'lsa PostgreSQL, bo'lmasa SQLite avtomatik tanlanadi.

### Asosiy jadvallar

| Jadval | Maqsad |
|--------|--------|
| `menu` | Taomlar, narxlar, kategoriyalar, rasm |
| `tables` | Stollar ro'yxati |
| `sessions` | Ochiq/yopiq stol xizmatlari |
| `order_items` | Buyurtma qatorlari, holati |
| `staff` | Xodimlar, rol, PIN hash, maosh |
| `shifts` | Smenalar tarixi |
| `payments` | To'lovlar (to'lov usuli, summa) |
| `expenses` | Xarajatlar |
| `inventory` | Mahsulotlar ombori |
| `inventory_log` | Inventar harakatlar tarixi |
| `recipes` | Taom retseptlari (mahsulot — miqdor) |
| `customers` | Sodiqlik tizimi — mijozlar |
| `audit_log` | Muhim amallar logi |
| `settings` | Tizim sozlamalari |
| `news` | Yangiliklar |
| `reservations` | Stol bronlari |
| `gallery` | Galereya rasmlari |
| `promotions` | Aktsiyalar |
| `attendance` | Xodim davomat yozuvlari |

Barcha migratsiyalar `database.py` ichida — server ishga tushganda avtomatik bajariladi.

### PIN ko'chirish (eski tizimdan)

Eski SHA256[:8] format pinlarni yangi PBKDF2 formatga o'tkazish:

```bash
cd backend
python migrate_pins.py
```

---

## Xavfsizlik

| Soha | Yechim |
|------|--------|
| Admin parol | `ADMIN_PASSWORD` env var (DB da saqlanmaydi) |
| Admin token | HMAC-SHA256, 4 soatlik TTL, `sessionStorage` |
| PIN | PBKDF2-SHA256, 200 000 iteratsiya, tuz bilan |
| Brute-force | 5 urinishdan so'ng 15 daqiqa IP bloklash |
| Rate limiting | Login: 5/min, DELETE: 10/min, Umumiy: 5000/kun |
| CORS | `ALLOWED_ORIGINS` orqali cheklash |
| XSS | `sessionStorage` (localStorage emas) |
| Fayl yuklash | Kengaytma tekshirish, `secure_filename`, max 10 MB |
| HTTP sarlavhalar | CSP, HSTS, X-Frame-Options, X-Content-Type-Options |
| DB ulanish | Har so'rov uchun avtomatik yopiladi (`teardown_appcontext`) |
| Audit log | Admin amallari `audit_log` jadvalida saqlanadi |

---

## Telegram Bildirishnomalar

Quyidagi hollarda Telegram ga xabar yuboriladi:
- Yangi buyurtma kelganda oshxonaga
- Taom tayyor bo'lganda ofitsiantga
- Smena yopilganda umumiy hisobot

Sozlash uchun:
1. `@BotFather` orqali bot yarating — `TELEGRAM_BOT_TOKEN` oling
2. Botni kanalga/guruhga qo'shing
3. Chat ID ni toping (`@userinfobot` yordamida)
4. Render Environment da ikkalasini o'rnating
