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


def login():
    global admin_token
    res = api("POST", "/api/login", {"password": ADMIN_PASS})
    if res.get("ok"):
        admin_token = res["token"]
        log.info("Admin login OK")
    else:
        log.warning("Admin login FAILED — buyurtma statusini o'zgartirish ishlamas")


STATUS_LABELS = {
    "new":       "🆕 Yangi",
    "confirmed": "✅ Tasdiqlangan",
    "done":      "✔️ Bajarilgan",
    "cancelled": "❌ Bekor qilingan",
}


def send_kb(chat_id, text, buttons):
    tg("sendMessage",
       chat_id=chat_id,
       text=text,
       parse_mode="HTML",
       reply_markup={"inline_keyboard": buttons})


def handle_message(msg):
    chat_id = msg["chat"]["id"]
    text    = msg.get("text", "").strip()

    if text in ("/start", "/help"):
        send_kb(chat_id,
            "👋 <b>Rayyon Admin Bot</b>\n\nBuyurtmalar va bronlarni boshqarish:",
            [[
                {"text": "📦 Buyurtmalar", "callback_data": "orders"},
                {"text": "📅 Bronlar",     "callback_data": "reservations"},
            ]]
        )
    elif text == "/orders":
        show_orders(chat_id)
    elif text == "/reservations":
        show_reservations(chat_id)
    else:
        tg("sendMessage", chat_id=chat_id,
           text="📌 Komandalar:\n/orders — Buyurtmalar\n/reservations — Bronlar")


def show_orders(chat_id):
    items = api("GET", "/api/orders?status=new")
    if not isinstance(items, list) or not items:
        tg("sendMessage", chat_id=chat_id, text="📦 Yangi buyurtmalar yo'q.")
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
        tg("sendMessage", chat_id=chat_id, text="📅 Bronlar yo'q.")
        return
    new_only = [r for r in items if r.get("status") == "new"][:10]
    if not new_only:
        tg("sendMessage", chat_id=chat_id, text="📅 Yangi bronlar yo'q.")
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


def handle_callback(cb):
    chat_id = cb["message"]["chat"]["id"]
    msg_id  = cb["message"]["message_id"]
    data    = cb.get("data", "")
    cb_id   = cb["id"]

    if data == "orders":
        show_orders(chat_id)
        tg("answerCallbackQuery", callback_query_id=cb_id)
        return
    if data == "reservations":
        show_reservations(chat_id)
        tg("answerCallbackQuery", callback_query_id=cb_id)
        return

    if data.startswith("ord_"):
        _, status, oid = data.split("_", 2)
        res   = api("PUT", f"/api/orders/{oid}", {"status": status})
        label = STATUS_LABELS.get(status, status)
        if res.get("ok"):
            tg("editMessageText",
               chat_id=chat_id, message_id=msg_id,
               text=f"✅ Buyurtma #{oid} → {label}", parse_mode="HTML")
        tg("answerCallbackQuery", callback_query_id=cb_id, text=label)

    elif data.startswith("res_"):
        _, status, rid = data.split("_", 2)
        res   = api("PUT", f"/api/reservations/{rid}", {"status": status})
        label = STATUS_LABELS.get(status, status)
        if res.get("ok"):
            tg("editMessageText",
               chat_id=chat_id, message_id=msg_id,
               text=f"✅ Bron #{rid} → {label}", parse_mode="HTML")
        tg("answerCallbackQuery", callback_query_id=cb_id, text=label)


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
