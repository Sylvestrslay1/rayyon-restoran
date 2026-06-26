"""
Rayyon Restoran Telegram Bot
Muhit o'zgaruvchilari:
  TELEGRAM_BOT_TOKEN  - BotFather dan olingan token
  TELEGRAM_CHAT_ID    - Bildirishnomalar yuboriluvchi chat ID (ruxsatli chatlar)
  RAYYON_API_URL      - Backend URL (masalan https://rayyon-restoran.onrender.com)
  RAYYON_ADMIN_PASS   - Admin paroli
Ishga tushirish: python bot/bot.py
"""

import os, time, urllib.request, urllib.parse, json, logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("rayyon-bot")

TOKEN      = os.environ.get("TELEGRAM_BOT_TOKEN", "")
API_URL    = os.environ.get("RAYYON_API_URL", "http://localhost:5000")
ADMIN_PASS = os.environ.get("RAYYON_ADMIN_PASS", "")
if not ADMIN_PASS:
    raise RuntimeError("RAYYON_ADMIN_PASS muhit o'zgaruvchisi majburiy! Bot ishga tushirilmadi.")

# Ruxsatli chat ID lar (vergul bilan ajratilgan, masalan: "123456,789012")
# Bo'sh bo'lsa — barcha chatlar ruxsat beriladi (XAVFLI, faqat test uchun)
_CHAT_IDS_RAW = os.environ.get("TELEGRAM_CHAT_ID", "")
ALLOWED_CHAT_IDS: set = {
    int(c.strip()) for c in _CHAT_IDS_RAW.split(",") if c.strip().lstrip("-").isdigit()
}

BASE = f"https://api.telegram.org/bot{TOKEN}"
admin_token    = None
_token_created = 0.0
TOKEN_TTL_SEC  = 7 * 3600  # 7 soat (backend TTL 8h, avvalroq yangilaymiz)


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


def _do_login() -> bool:
    """Loginni bajaradi. Muvaffaqiyatli bo'lsa True qaytaradi."""
    global admin_token, _token_created
    res = api_raw("POST", "/api/login", {"password": ADMIN_PASS})
    if res.get("ok"):
        admin_token    = res["token"]
        _token_created = time.time()
        log.info("Admin login OK")
        return True
    log.warning("Admin login FAILED — barcha API calllar 403 oladi")
    if ALLOWED_CHAT_IDS:
        for cid in ALLOWED_CHAT_IDS:
            tg("sendMessage", chat_id=cid,
               text="❌ <b>Bot login xatosi!</b>\nAdmin paroli noto'g'ri yoki server ishlamayapti.",
               parse_mode="HTML")
    return False


def login():
    _do_login()


def _ensure_token():
    """Token muddati tugagan bo'lsa qayta login qiladi."""
    global admin_token
    if not admin_token or (time.time() - _token_created) > TOKEN_TTL_SEC:
        log.info("Admin token yangilanmoqda...")
        _do_login()


def api_raw(method, path, data=None, token=None):
    """Token tekshirmasdan API call (login uchun ishlatiladi)."""
    url     = API_URL + path
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Admin-Token"] = token
    body = json.dumps(data).encode() if data else None
    req  = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        log.error(f"API error {path}: {e}")
        return {}


def api(method, path, data=None):
    """Admin token bilan API call. 401/403 da qayta login qilib urinadi."""
    _ensure_token()
    res = api_raw(method, path, data, token=admin_token)
    # Token muddati tugagan bo'lsa bir marta qayta urinib ko'ramiz
    if res == {} and admin_token:
        log.info("API 403 — qayta login qilinmoqda")
        if _do_login():
            res = api_raw(method, path, data, token=admin_token)
    return res


def is_allowed(chat_id: int) -> bool:
    """Chat ruxsatini tekshiradi. ALLOWED_CHAT_IDS bo'sh bo'lsa hamma ruxsatli (test rejim)."""
    if not ALLOWED_CHAT_IDS:
        return True
    return chat_id in ALLOWED_CHAT_IDS


STATUS_LABELS = {
    "new":       "🆕 Yangi",
    "confirmed": "✅ Tasdiqlangan",
    "done":      "✔️ Bajarilgan",
    "cancelled": "❌ Bekor qilingan",
    "pending":   "⏳ Kutilmoqda",
    "open":      "🟢 Ochiq",
    "closed":    "🔒 Yopilgan",
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
            [
                {"text": "📊 Bugun",       "callback_data": "today"},
                {"text": "📈 Hafta",       "callback_data": "week"},
                {"text": "📉 Oy",          "callback_data": "month"},
            ],
            [
                {"text": "👥 Xodimlar",    "callback_data": "staff"},
            ],
        ]
    )


def handle_message(msg):
    chat_id = msg["chat"]["id"]
    # Xavfsizlik: ruxsatsiz chatlardan kelgan xabarlarni e'tiborsiz qoldiramiz
    if not is_allowed(chat_id):
        log.warning(f"Ruxsatsiz chat: {chat_id}")
        return
    text = msg.get("text", "").strip()

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
    elif text == "/hafta":
        show_period(chat_id, "weekly", "Haftalik")
    elif text == "/oy":
        show_period(chat_id, "monthly", "Oylik")
    elif text == "/xodimlar":
        show_staff(chat_id)
    else:
        send_kb(chat_id,
            "📌 Mavjud buyruqlar:\n"
            "/orders — Buyurtmalar\n"
            "/reservations — Bronlar\n"
            "/stollar — Ochiq stollar\n"
            "/smena — Joriy smena\n"
            "/inventar — Kam mahsulotlar\n"
            "/mijozlar — Top mijozlar\n"
            "/bugun — Bugungi hisobot\n"
            "/hafta — Haftalik hisobot\n"
            "/oy — Oylik hisobot\n"
            "/xodimlar — Xodimlar ro'yxati",
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
    """Joriy ochiq smenalarni ko'rsatadi."""
    shifts = api("GET", "/api/shifts?status=open&limit=5")
    tables = api("GET", "/api/tables")
    occupied_ct  = sum(1 for t in (tables if isinstance(tables, list) else []) if t.get("status") != "free")
    total_amount = sum(int(t.get("total_amount") or 0) for t in (tables if isinstance(tables, list) else []))

    if not isinstance(shifts, list) or not shifts:
        send_kb(chat_id,
            f"💼 <b>Joriy holat</b>\n\n"
            f"🪑 Band stollar: <b>{occupied_ct}</b> ta\n"
            f"💰 Kutilayotgan: <b>{total_amount:,} so'm</b>\n"
            f"ℹ️ Ochiq smena topilmadi.",
            [[{"text": "🪑 Stollar", "callback_data": "tables"},
              {"text": "🏠 Menyu",   "callback_data": "main"}]])
        return

    lines = [f"💼 <b>Ochiq smenalar</b>\n"]
    for s in shifts:
        cashier  = s.get("cashier_name", "?")
        opened   = str(s.get("opened_at", ""))[:16]
        sessions = s.get("sessions_count", 0)
        revenue  = int(s.get("total_revenue") or s.get("total_collected") or 0)
        lines.append(
            f"👤 <b>{cashier}</b> — {opened}\n"
            f"   🧾 {sessions} xizmat · 💰 {revenue:,} so'm"
        )
    lines.append(f"\n🪑 Band stollar: <b>{occupied_ct}</b> ta")
    lines.append(f"💰 Kutilayotgan: <b>{total_amount:,} so'm</b>")
    send_kb(chat_id, "\n".join(lines),
            [[{"text": "🔄 Yangilash", "callback_data": "shifts"},
              {"text": "🏠 Menyu",     "callback_data": "main"}]])


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
        name  = c.get("name") or c.get("phone", "?")
        spent = int(c.get("total_spent", 0))
        visits = c.get("visits", 0)
        disc  = c.get("discount_pct", 0)
        lines.append(
            f"{i}. {name} — {spent:,} so'm · {visits} tashrif"
            + (f" · {disc}% chegirma" if disc else "")
        )
    send_kb(chat_id, "\n".join(lines),
            [[{"text": "🏠 Menyu", "callback_data": "main"}]])


def show_today(chat_id):
    show_period(chat_id, "daily", "Bugungi")


def show_period(chat_id, period: str, label: str):
    """Davr bo'yicha hisobot: daily / weekly / monthly."""
    stats = api("GET", f"/api/analytics/summary?period={period}")
    if not stats or not isinstance(stats, dict):
        send_msg(chat_id, "❌ Statistika olinmadi.")
        return
    revenue  = int(stats.get("revenue", 0))
    expenses = int(stats.get("expenses", 0))
    profit   = revenue - expenses
    sessions = stats.get("sessions", 0)
    items_ct = stats.get("items_sold", 0)
    avg      = int(stats.get("avg_bill", 0))
    cb_key   = {"daily": "today", "weekly": "week", "monthly": "month"}.get(period, "today")
    send_kb(chat_id,
        f"📊 <b>{label} hisobot</b>\n\n"
        f"💰 Daromad: <b>{revenue:,} so'm</b>\n"
        f"📤 Xarajat: <b>{expenses:,} so'm</b>\n"
        f"📈 Foyda:   <b>{profit:,} so'm</b>\n"
        f"🪑 Xizmatlar: <b>{sessions}</b> ta\n"
        f"🍽 Taomlar: <b>{items_ct}</b> ta sotilgan\n"
        f"🧾 O'rtacha: <b>{avg:,} so'm</b>",
        [[{"text": "🔄 Yangilash", "callback_data": cb_key},
          {"text": "🏠 Menyu",     "callback_data": "main"}]])


def show_staff(chat_id):
    """Aktiv xodimlar ro'yxati."""
    staff_list = api("GET", "/api/staff")
    if not isinstance(staff_list, list):
        send_msg(chat_id, "❌ Xodimlar ma'lumoti olinmadi.")
        return
    active = [s for s in staff_list if s.get("active", 1)]
    if not active:
        send_kb(chat_id, "👥 Aktiv xodimlar yo'q.",
                [[{"text": "🏠 Menyu", "callback_data": "main"}]])
        return
    role_icons = {
        "admin": "👑", "director": "🏆", "manager": "📋",
        "cashier": "💳", "waiter": "🍽", "kitchen": "👨‍🍳",
        "cook": "🧑‍🍳", "chef": "👨‍🍳", "accountant": "📊",
        "cleaner": "🧹",
    }
    lines = [f"👥 <b>Xodimlar ({len(active)} ta)</b>\n"]
    for s in active[:20]:
        role = s.get("role", "?")
        icon = role_icons.get(role, "👤")
        name = s.get("name", "?")
        lines.append(f"{icon} <b>{name}</b> — {role}")
    send_kb(chat_id, "\n".join(lines),
            [[{"text": "🔄 Yangilash", "callback_data": "staff"},
              {"text": "🏠 Menyu",     "callback_data": "main"}]])


def handle_callback(cb):
    chat_id = cb["message"]["chat"]["id"]
    # Xavfsizlik: ruxsatsiz chatlardan kelgan callbacklarni e'tiborsiz qoldiramiz
    if not is_allowed(chat_id):
        log.warning(f"Ruxsatsiz callback chat: {chat_id}")
        return
    msg_id = cb["message"]["message_id"]
    data   = cb.get("data", "")
    cb_id  = cb["id"]

    tg("answerCallbackQuery", callback_query_id=cb_id)

    dispatch = {
        "main":         main_menu,
        "orders":       show_orders,
        "reservations": show_reservations,
        "tables":       show_tables,
        "shifts":       show_shifts,
        "inventory":    show_inventory,
        "customers":    show_customers,
        "today":        show_today,
        "staff":        show_staff,
    }
    if data in dispatch:
        dispatch[data](chat_id)
        return
    if data == "week":
        show_period(chat_id, "weekly", "Haftalik")
        return
    if data == "month":
        show_period(chat_id, "monthly", "Oylik")
        return

    if data.startswith("ord_"):
        _, status, oid = data.split("_", 2)
        res   = api("PUT", f"/api/orders/{oid}", {"status": status})
        label = STATUS_LABELS.get(status, status)
        if res.get("ok"):
            tg("editMessageText",
               chat_id=chat_id, message_id=msg_id,
               text=f"✅ Buyurtma #{oid} → {label}", parse_mode="HTML")
        return

    if data.startswith("res_"):
        _, status, rid = data.split("_", 2)
        res   = api("PUT", f"/api/reservations/{rid}", {"status": status})
        label = STATUS_LABELS.get(status, status)
        if res.get("ok"):
            tg("editMessageText",
               chat_id=chat_id, message_id=msg_id,
               text=f"✅ Bron #{rid} → {label}", parse_mode="HTML")
        return

    log.debug(f"Noma'lum callback: {data}")


def poll():
    offset = 0
    log.info(f"Bot polling boshlandi | API: {API_URL}")
    if ALLOWED_CHAT_IDS:
        log.info(f"Ruxsatli chatlar: {ALLOWED_CHAT_IDS}")
    else:
        log.warning("TELEGRAM_CHAT_ID o'rnatilmagan — barcha chatlar ruxsatli (test rejim)!")
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
