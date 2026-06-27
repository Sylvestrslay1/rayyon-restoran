# Rayyon Restoran — Boshqaruv Tizimi

Flask + PostgreSQL asosidagi to'liq restoran boshqaruv tizimi.

## Tarkib

| Fayl | Maqsad |
|------|--------|
| `backend/app.py` | Flask API (50+ endpoint) |
| `backend/database.py` | DB schema va migratsiyalar |
| `cashier.html` | Kassir paneli (PIN login, to'lov) |
| `kitchen.html` | Oshxona ekrani (real-time KDS) |
| `admin/index.html` | Admin panel |
| `admin/login.html` | Admin login |
| `menu.html` | Mijoz QR menyu |
| `index.html` | Asosiy veb-sayt |

## Ishga tushirish (lokal)

```bash
cd backend
pip install -r requirements.txt
export ADMIN_PASSWORD="kuchli_parol_bu_yerga"
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python app.py
```

Brauzerda: `http://localhost:5000`

## Render.com deploy

1. `render.yaml` faylida barcha sozlamalar tayyor
2. **Majburiy** — Render Dashboard > Environment:
   - `ADMIN_PASSWORD` — admin panel paroli (kamida 12 belgi)
3. **Ixtiyoriy** (tavsiya etiladi):
   - `REDIS_URL` — ko'p worker rejimi uchun (Render Redis xizmatidan)
   - `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` — bildirishnomalar uchun
   - `ALLOWED_ORIGINS` — `https://rayyon-restoran.onrender.com`

## Xodim rollari

| Rol | Kirish paneli | Ruxsatlar |
|-----|---------------|-----------|
| `admin` / `director` | Admin panel | Barcha |
| `cashier` | cashier.html | Stol, to'lov |
| `waiter` | cashier.html | Stol, buyurtma |
| `kitchen` / `cook` | kitchen.html | Oshxona |
| `manager` | Admin panel | Menyu, hisobot |
| `chef` | Admin panel | Menyu, retsept, inventar |
| `accountant` | Admin panel | Moliya, hisobot |

## API asosiy endpointlar

```
GET  /api/health          — Server holati
POST /api/login           — Admin login
GET  /api/menu            — Menyu ro'yxati
GET  /api/tables          — Stollar holati
POST /api/session/open    — Stol ochish
POST /api/session/:id/close — To'lov va yopish
GET  /api/kitchen         — Oshxona buyurtmalari
GET  /api/stats           — Kunlik statistika
```

## Xavfsizlik

- Admin token: 4 soatlik TTL, sessionStorage
- PIN: PBKDF2-SHA256 (200,000 iteratsiya)
- Rate limiting: login (5/min), DELETE (10/min)
- HTTPS redirect production da avtomatik
- CSP, HSTS, X-Frame-Options headerlari

## Loyiha tuzilmasi

```
rayyon-restaurant/
├── backend/
│   ├── app.py           # Flask API
│   ├── database.py      # DB schema
│   └── requirements.txt
├── admin/
│   ├── index.html       # Admin panel
│   └── login.html
├── css/style.css
├── js/main.js
├── cashier.html
├── kitchen.html
├── menu.html
├── index.html
└── render.yaml
```
