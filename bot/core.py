"""
Umumiy: API, Telegram, holat boshqaruvi, keshlar, yordamchi funksiyalar.
Barcha modullar shu fayldan import qiladi.
"""
import os, time, urllib.request, urllib.parse, json, logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("rayyon-bot")

TOKEN      = os.environ.get("TELEGRAM_BOT_TOKEN", "")
API_URL    = os.environ.get("RAYYON_API_URL", "http://localhost:5000")
ADMIN_PASS = os.environ.get("RAYYON_ADMIN_PASS", "")
if not ADMIN_PASS:
    raise RuntimeError("RAYYON_ADMIN_PASS muhit o'zgaruvchisi majburiy! Bot ishga tushirilmadi.")

_CHAT_IDS_RAW = os.environ.get("TELEGRAM_CHAT_ID", "")
ALLOWED_CHAT_IDS: set = {
    int(c.strip()) for c in _CHAT_IDS_RAW.split(",") if c.strip().lstrip("-").isdigit()
}

_NOTIF_INTERVAL    = int(os.environ.get("NOTIF_INTERVAL", "60"))
_DAILY_REPORT_HOUR = int(os.environ.get("DAILY_REPORT_HOUR", "22"))

BASE           = f"https://api.telegram.org/bot{TOKEN}"
admin_token    = None
_token_created = 0.0
TOKEN_TTL_SEC  = 7 * 3600

STATUS_LABELS = {
    "new":       "🆕 Yangi",
    "confirmed": "✅ Tasdiqlangan",
    "done":      "✔️ Bajarilgan",
    "cancelled": "❌ Bekor qilingan",
    "pending":   "⏳ Kutilmoqda",
    "open":      "🟢 Ochiq",
    "closed":    "🔒 Yopilgan",
}

ROLE_ICONS = {
    'admin': '👑', 'director': '🏆', 'manager': '📋',
    'cashier': '💳', 'waiter': '🍽', 'kitchen': '👨‍🍳',
    'cook': '🧑‍🍳', 'chef': '👨‍🍳',
}
CATS = [
    ('milliy', '🏺 Milliy taomlar'),
    ('grill',  '🔥 Grill'),
    ('salad',  '🥗 Salatlar'),
    ('drink',  '🥤 Ichimliklar'),
]
WAITER_ROLES  = ('waiter',)
KITCHEN_ROLES = ('kitchen', 'cook', 'chef')
CASHIER_ROLES = ('cashier', 'manager', 'admin', 'director')


# ── Telegram API ──────────────────────────────────────────────

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


def send_kb(chat_id, text, buttons):
    tg("sendMessage",
       chat_id=chat_id, text=text, parse_mode="HTML",
       reply_markup={"inline_keyboard": buttons})


def send_msg(chat_id, text):
    tg("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML")


# ── Backend API ───────────────────────────────────────────────

_login_notified = False  # Xato xabari faqat bir marta yuborilsin


def _do_login(silent=False) -> bool:
    global admin_token, _token_created, _login_notified
    res = api_raw("POST", "/api/login", {"password": ADMIN_PASS})
    if res.get("ok"):
        admin_token    = res["token"]
        _token_created = time.time()
        _login_notified = False
        log.info("Admin login OK")
        return True
    log.warning("Admin login FAILED")
    if not silent and not _login_notified and ALLOWED_CHAT_IDS:
        _login_notified = True
        for cid in ALLOWED_CHAT_IDS:
            tg("sendMessage", chat_id=cid,
               text="❌ <b>Bot login xatosi!</b>\nAdmin paroli noto'g'ri yoki server ishlamayapti.",
               parse_mode="HTML")
    return False


def login():
    # Birinchi login — xato bo'lsa xabar yubormaymiz (Render uyg'onayotgan bo'lishi mumkin)
    _do_login(silent=True)


def _ensure_token():
    global admin_token
    if not admin_token or (time.time() - _token_created) > TOKEN_TTL_SEC:
        log.info("Admin token yangilanmoqda...")
        _do_login(silent=False)


def api_raw(method, path, data=None, token=None):
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
    _ensure_token()
    res = api_raw(method, path, data, token=admin_token)
    if res == {} and admin_token:
        log.info("API 403 — qayta login qilinmoqda")
        if _do_login():
            res = api_raw(method, path, data, token=admin_token)
    return res


def is_allowed(chat_id: int) -> bool:
    if not ALLOWED_CHAT_IDS:
        return True
    return chat_id in ALLOWED_CHAT_IDS


def _ascii_bar(value, max_val, width=12):
    if max_val <= 0:
        return '░' * width
    filled = round(value / max_val * width)
    return '█' * filled + '░' * (width - filled)


# ── Suhbat holati (state machine) ────────────────────────────

_user_state  = {}  # chat_id -> {'step': str, 'data': dict}
_user_roles  = {}  # chat_id -> 'staff' | 'customer'  (admin is_allowed() orqali aniqlanadi)
_user_langs  = {}  # chat_id -> 'uz' | 'ru' | 'en'
_user_names  = {}  # chat_id -> str  (mijoz ismi)
_user_phones = {}  # chat_id -> str  (mijoz telefoni)
_user_tables = {}  # chat_id -> int  (QR orqali kelgan stol raqami)


def get_state(chat_id):
    return _user_state.get(chat_id, {})


def set_state(chat_id, step, data=None):
    _user_state[chat_id] = {'step': step, 'data': data or {}}


def clear_state(chat_id):
    _user_state.pop(chat_id, None)


def get_user_role(chat_id):
    """Foydalanuvchi rolini qaytaradi: 'admin', 'staff', 'customer' yoki None."""
    if is_allowed(chat_id):
        return 'admin'
    return _user_roles.get(chat_id)


def set_user_role(chat_id, role):
    if role is None:
        _user_roles.pop(chat_id, None)
    else:
        _user_roles[chat_id] = role


# ── Mijoz profili (til, ism, telefon, stol) ───────────────────

def get_lang(chat_id):
    return _user_langs.get(chat_id)

def set_lang(chat_id, lang):
    _user_langs[chat_id] = lang

def get_cust_name(chat_id):
    return _user_names.get(chat_id)

def set_cust_name(chat_id, name):
    _user_names[chat_id] = name

def get_cust_phone(chat_id):
    return _user_phones.get(chat_id)

def set_cust_phone(chat_id, phone):
    _user_phones[chat_id] = phone

def get_table(chat_id):
    return _user_tables.get(chat_id)

def set_table(chat_id, num):
    if num:
        _user_tables[chat_id] = num
    else:
        _user_tables.pop(chat_id, None)


# ── Mijoz savati ──────────────────────────────────────────────

_user_carts = {}  # chat_id -> [{'id','name','emoji','price','qty'}]


def get_cart(chat_id):
    return _user_carts.get(chat_id, [])


def cart_add(chat_id, item):
    cart = _user_carts.setdefault(chat_id, [])
    for c in cart:
        if c['id'] == item['id']:
            c['qty'] += 1
            return
    cart.append({**item, 'qty': 1})


def cart_clear(chat_id):
    _user_carts.pop(chat_id, None)


def cart_total(chat_id):
    return sum(c['price'] * c['qty'] for c in get_cart(chat_id))


# ── Xodim sessiyalari ─────────────────────────────────────────

_staff_sessions = {}  # chat_id -> {name, role, id, pin}
_waiter_carts   = {}  # chat_id -> {table_id, session_id, items:[]}


def get_staff(chat_id):
    return _staff_sessions.get(chat_id)


def staff_logout(chat_id):
    _staff_sessions.pop(chat_id, None)
    _waiter_carts.pop(chat_id, None)
    clear_state(chat_id)
    set_user_role(chat_id, None)


# ── Menyu keshi ───────────────────────────────────────────────

_menu_cache    = []
_menu_cache_ts = 0.0
_MENU_TTL      = 120


def get_menu():
    global _menu_cache, _menu_cache_ts
    if _menu_cache and (time.time() - _menu_cache_ts) < _MENU_TTL:
        return _menu_cache
    items = api("GET", "/api/menu")
    if isinstance(items, list):
        _menu_cache    = items
        _menu_cache_ts = time.time()
    return _menu_cache
