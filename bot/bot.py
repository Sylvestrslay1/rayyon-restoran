"""
Rayyon Restoran Telegram Bot
Muhit o'zgaruvchilari:
  TELEGRAM_BOT_TOKEN  - BotFather dan olingan token
  TELEGRAM_CHAT_ID    - Bildirishnomalar yuboriluvchi chat ID
  RAYYON_API_URL      - Backend URL (masalan https://rayyon-restoran.onrender.com)
  RAYYON_ADMIN_PASS   - Admin paroli
Ishga tushirish: python bot/bot.py
"""

import os, time, urllib.request, urllib.parse, json, logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("rayyon-bot")

TOKEN      = os.environ.get("TELEGRAM_BOT_TOKEN", "")
API_URL    = os.environ.get("RAYYON_API_URL", "http://localhost:5000")
ADMIN_PASS = os.environ.get("RAYYON_ADMIN_PASS", "rayyon2024")

BASE = f"https://api.telegram.org/bot{TOKEN}"
admin_token = None


def tg(method, **kwargs):
    url  = f"{BASE}/{method}"
    data = urllib.parse.urlencode({
        k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
        for k, v in kwargs.items()
    }).encode()
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, data=data, method="POST"), timeout=10
        ) as r:
            return json.loads(r.read())
    except Exception as e:
        log.error(f"TG error {method}: {e}")
        return {}


def api(method, path, data=None):
    url     = API_URL + path
    headers = {"Content-Type": "application/json"}
    if admin_token:
        headers["X-Admin-Token"] = admin_token
    body = json.dumps(data).encode() if data else None
    req  = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        log.error(f"API error {path}: {e}")
        return {}


CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def login():
    global admin_token
    res = api("POST", "/api/login", {"password": ADMIN_PASS})
    if res.get("ok"):
        admin_token = res["token"]
        log.info("Admin login OK")
    else:
        log.warning("Admin login FAILED — barcha API calllar 403 oladi")
        if CHAT_ID:
            tg("sendMessage", chat_id=CHAT_ID,
               text="❌ <b>Bot login xatosi!</b>\nAdmin paroli noto'g'ri yoki server ishlamayapti.\n"
                    "RAYYON_ADMIN_PASS env o'zgaruvchisini tekshiring.",
               parse_mode="HTML")


STATUS_LABELS = {
    "new":       "🆕 Yangi",
    "confirmed": "✅ Tasdiqlangan",
    "done":      "✔️ Bajarilgan",
    "cancelled": "❌ Bekor qilingan",
    "pending":   "⏳ Kutilmoqda",
}


def send_kb(chat_id, text, buttons):
    tg("sendMessage",
       chat_id=chat_id,
       text=text,
       parse_mode="HTML",
       reply_markup={"inline_keyboard": buttons})


def send_msg(chat_id, text):
    tg("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML")


def main_menu(chat_id):
    send_kb(chat_id,
        "👋 <b>Rayyon Admin Bot</b>\n\nNimani ko'rmoqchisiz?",
        [
            [
                {"text": "📦 Buyurtmalar", "callback_data": "orders"},
                {"text": "📅 Bronlar",     "callback_data": "reservations"},
            ],
            [
                {"text": "🪑 Stollar",     "callback_data": "tables"},
                {"text": "📦 Inventar",    "callback_data": "inventory"},
            ],
            [
                {"text": "💼 Smena",       "callback_data": "shifts"},
                {"text": "💳 Mijozlar",    "callback_data": "customers"},
            ],
        ]
    )


def handle_message(msg):
    chat_id = msg["chat"]["id"]
    text    = msg.get("text", "").strip()

    if text in ("/start", "/help"):
        main_menu(chat_id)
    elif text == "/orders":
        show_orders(chat_id)
    elif text == "/reservations":
        show_reservations(chat_id)
    elif text == "/stollar":
        show_tables(chat_id)
    elif text == "/smena":
        show_shifts(chat_id)
    elif text == "/inventar":
        show_inventory(chat_id)
    elif text == "/mijozlar":
        show_customers(chat_id)
    elif text == "/bugun":
        show_today(chat_id)
    else:
        send_kb(chat_id,
            "📌 Mavjud buyruqlar:\n"
            "/orders — Buyurtmalar\n"
            "/reservations — Bronlar\n"
            "/stollar — Ochiq stollar\n"
            "/smena — Joriy smena\n"
            "/inventar — Kam mahsulotlar\n"
            "/mijozlar — Top mijozlar\n"
            "/bugun — Bugungi hisobot",
            [[{"text": "🏠 Asosiy menyu", "callback_data": "main"}]]
        )


def show_orders(chat_id):
    items = api("GET", "/api/orders?status=new")
    if not isinstance(items, list) or not items:
        send_kb(chat_id, "📦 Yangi buyurtmalar yo'q.",
                [[{"text": "🏠 Menyu", "callback_data": "main"}]])
        return
    for o in items[:10]:
        txt = (
            f"📦 <b>Buyurtma #{o['id']}</b>\n"
            f"🍽 {o.get('item_name','')} x{o.get('quantity',1)}\n"
            f"💰 {int(o.get('total_price',0)):,} so'm\n"
            f"👤 {o.get('customer_name','')} · {o.get('customer_phone','')}\n"
            + (f"📝 {o['note']}\n" if o.get("note") else "")
            + f"📊 {STATUS_LABELS.get(o.get('status'), o.get('status',''))}"
        )
        btns = [[
            {"text": "✅ Tasdiqlash", "callback_data": f"ord_confirmed_{o['id']}"},
            {"text": "✔️ Bajarildi",  "callback_data": f"ord_done_{o['id']}"},
            {"text": "❌ Bekor",      "callback_data": f"ord_cancelled_{o['id']}"},
        ]]
        send_kb(chat_id, txt, btns)


def show_reservations(chat_id):
    items = api("GET", "/api/reservations")
    if not isinstance(items, list):
        send_kb(chat_id, "📅 Bronlar yo'q.",
                [[{"text": "🏠 Menyu", "callback_data": "main"}]])
        return
    new_only = [r for r in items if r.get("status") in ("new", "confirmed")][:10]
    if not new_only:
        send_kb(chat_id, "📅 Yangi bronlar yo'q.",
                [[{"text": "🏠 Menyu", "callback_data": "main"}]])
        return
    for r in new_only:
        txt = (
            f"📅 <b>Bron #{r['id']}</b>\n"
            f"👤 {r.get('customer_name','')} · {r.get('customer_phone','')}\n"
            f"📆 {r.get('date','')} {r.get('time','')}\n"
            f"👥 {r.get('guests',2)} mehmon\n"
            + (f"📝 {r['note']}\n" if r.get("note") else "")
            + f"📊 {STATUS_LABELS.get(r.get('status'), r.get('status',''))}"
        )
        btns = [[
            {"text": "✅ Tasdiqlash", "callback_data": f"res_confirmed_{r['id']}"},
            {"text": "❌ Bekor",      "callback_data": f"res_cancelled_{r['id']}"},
        ]]
        send_kb(chat_id, txt, btns)


def show_tables(chat_id):
    tables = api("GET", "/api/tables")
    if not isinstance(tables, list):
        send_msg(chat_id, "❌ Stollar ma'lumoti olinmadi.")
        return
    occupied = [t for t in tables if t.get("status") != "free"]
    free_ct  = len(tables) - len(occupied)
    if not occupied:
        send_kb(chat_id, f"🪑 Hamma {len(tables)} ta stol bo'sh.",
                [[{"text": "🏠 Menyu", "callback_data": "main"}]])
        return
    lines = [f"🪑 <b>Stollar ({len(occupied)}/{len(tables)} band)</b>\n"]
    for t in occupied:
        mins = t.get("minutes_open", 0) or 0
        time_str = f"{mins//60}s {mins%60}d" if mins >= 60 else f"{mins}d"
        overtime = "⚠ " if mins > 120 else ""
        status_icon = "🧾" if t.get("status") == "bill_requested" else "🔴"
        amt = f"{int(t.get('total_amount',0)):,} so'm" if t.get("total_amount") else "—"
        waiter = t.get("waiter_name", "")
        lines.append(
            f"{status_icon} <b>Stol #{t['number']}</b> — {overtime}{time_str} — {amt}"
            + (f" | 👤{waiter}" if waiter else "")
        )
    lines.append(f"\n✅ Bo'sh stollar: {free_ct} ta")
    send_kb(chat_id, "\n".join(lines),
            [[{"text": "🔄 Yangilash", "callback_data": "tables"},
              {"text": "🏠 Menyu",     "callback_data": "main"}]])


def show_shifts(chat_id):
    # Barcha ochiq smenalar
    tables = api("GET", "/api/tables")
    # Smena ma'lumotini shifts endpointidan olish mumkin emas (public emas)
    # Faqat umumiy holatni ko'rsatamiz
    if not isinstance(tables, list):
        send_msg(chat_id, "❌ Ma'lumot olinmadi.")
        return
    occupied = [t for t in tables if t.get("status") != "free"]
    total_rev = sum(int(t.get("total_amount") or 0) for t in occupied)
    send_kb(chat_id,
        f"💼 <b>Joriy holat</b>\n\n"
        f"🪑 Band stollar: <b>{len(occupied)}</b> ta\n"
        f"💰 Kutilayotgan tushum: <b>{total_rev:,} so'm</b>\n"
        f"📊 Admin panelda to'liq smena ma'lumotini ko'ring.",
        [[{"text": "🪑 Stollar", "callback_data": "tables"},
          {"text": "🏠 Menyu",   "callback_data": "main"}]])


def show_inventory(chat_id):
    items = api("GET", "/api/inventory")
    if not isinstance(items, list):
        send_msg(chat_id, "❌ Inventar ma'lumoti olinmadi.")
        return
    low = [i for i in items if (i.get("quantity") or 0) <= (i.get("min_quantity") or 0)]
    if not low:
        send_kb(chat_id, f"📦 Inventar yaxshi — {len(items)} ta mahsulot, hammasi yetarli.",
                [[{"text": "🏠 Menyu", "callback_data": "main"}]])
        return
    lines = [f"⚠️ <b>Kam mahsulotlar ({len(low)} ta)</b>\n"]
    for i in low[:15]:
        lines.append(f"🔴 {i['name']}: <b>{i.get('quantity',0)} {i.get('unit','')}</b> (min: {i.get('min_quantity',0)})")
    send_kb(chat_id, "\n".join(lines),
            [[{"text": "🔄 Yangilash", "callback_data": "inventory"},
              {"text": "🏠 Menyu",     "callback_data": "main"}]])


def show_customers(chat_id):
    customers = api("GET", "/api/customers")
    if not isinstance(customers, list):
        send_msg(chat_id, "❌ Mijozlar ma'lumoti olinmadi.")
        return
    if not customers:
        send_kb(chat_id, "💳 Loyalty mijozlar ro'yxati bo'sh.",
                [[{"text": "🏠 Menyu", "callback_data": "main"}]])
        return
    top = sorted(customers, key=lambda x: x.get("total_spent", 0), reverse=True)[:10]
    lines = [f"💳 <b>Top {len(top)} mijoz</b>\n"]
    for i, c in enumerate(top, 1):
        name = c.get("name") or c.get("phone", "?")
        spent = int(c.get("total_spent", 0))
        visits = c.get("visits", 0)
        disc = c.get("discount_pct", 0)
        lines.append(
            f"{i}. {name} — {spent:,} so'm · {visits} tashrif"
            + (f" · {disc}% chegirma" if disc else "")
        )
    send_kb(chat_id, "\n".join(lines),
            [[{"text": "🏠 Menyu", "callback_data": "main"}]])


def show_today(chat_id):
    stats = api("GET", "/api/analytics/summary?period=daily")
    if not stats or not isinstance(stats, dict):
        send_msg(chat_id, "❌ Statistika olinmadi.")
        return
    revenue  = int(stats.get("revenue", 0))
    expenses = int(stats.get("expenses", 0))
    profit   = revenue - expenses
    sessions = stats.get("sessions", 0)
    items_ct = stats.get("items_sold", 0)
    avg      = int(stats.get("avg_bill", 0))
    send_kb(chat_id,
        f"📊 <b>Bugungi hisobot</b>\n\n"
        f"💰 Daromad: <b>{revenue:,} so'm</b>\n"
        f"📤 Xarajat: <b>{expenses:,} so'm</b>\n"
        f"📈 Foyda:   <b>{profit:,} so'm</b>\n"
        f"🪑 Stollar: <b>{sessions}</b> ta xizmat\n"
        f"🍽 Taomlar: <b>{items_ct}</b> ta sotilgan\n"
        f"🧾 O'rtacha: <b>{avg:,} so'm</b>",
        [[{"text": "🔄 Yangilash", "callback_data": "today"},
          {"text": "🏠 Menyu",     "callback_data": "main"}]])


def handle_callback(cb):
    chat_id = cb["message"]["chat"]["id"]
    msg_id  = cb["message"]["message_id"]
    data    = cb.get("data", "")
    cb_id   = cb["id"]

    tg("answerCallbackQuery", callback_query_id=cb_id)

    if data == "main":
        main_menu(chat_id); return
    if data == "orders":
        show_orders(chat_id); return
    if data == "reservations":
        show_reservations(chat_id); return
    if data == "tables":
        show_tables(chat_id); return
    if data == "shifts":
        show_shifts(chat_id); return
    if data == "inventory":
        show_inventory(chat_id); return
    if data == "customers":
        show_customers(chat_id); return
    if data == "today":
        show_today(chat_id); return

    if data.startswith("ord_"):
        _, status, oid = data.split("_", 2)
        res   = api("PUT", f"/api/orders/{oid}", {"status": status})
        label = STATUS_LABELS.get(status, status)
        if res.get("ok"):
            tg("editMessageText",
               chat_id=chat_id, message_id=msg_id,
               text=f"✅ Buyurtma #{oid} → {label}", parse_mode="HTML")

    elif data.startswith("res_"):
        _, status, rid = data.split("_", 2)
        res   = api("PUT", f"/api/reservations/{rid}", {"status": status})
        label = STATUS_LABELS.get(status, status)
        if res.get("ok"):
            tg("editMessageText",
               chat_id=chat_id, message_id=msg_id,
               text=f"✅ Bron #{rid} → {label}", parse_mode="HTML")


def poll():
    offset = 0
    log.info(f"Bot polling boshlandi | API: {API_URL}")
    while True:
        res = tg("getUpdates", offset=offset, timeout=30)
        for upd in res.get("result", []):
            offset = upd["update_id"] + 1
            try:
                if "message" in upd:
                    handle_message(upd["message"])
                elif "callback_query" in upd:
                    handle_callback(upd["callback_query"])
            except Exception as e:
                log.error(f"Handler error: {e}")
        time.sleep(0.3)


if __name__ == "__main__":
    if not TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN o'rnatilmagan!")
        print("   export TELEGRAM_BOT_TOKEN=<token>")
        exit(1)
    login()
    poll()
