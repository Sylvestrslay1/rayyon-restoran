from flask import Flask, request, jsonify, send_from_directory, Response, redirect
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os, time, urllib.request, urllib.parse, json, secrets, hashlib, hmac
import threading, datetime, csv, io, logging
import smtplib, email.mime.text, email.mime.multipart

log = logging.getLogger(__name__)

# ===== REDIS (ixtiyoriy — multi-worker uchun) =====
_redis = None
try:
    _REDIS_URL = os.environ.get("REDIS_URL", "")
    if _REDIS_URL:
        import redis as _redis_lib
        _redis = _redis_lib.from_url(_REDIS_URL, decode_responses=True, socket_connect_timeout=3)
        _redis.ping()
        log.info("Redis ulandi")
except Exception as _re:
    _redis = None
    log.info("Redis yo'q — in-memory rejim: %s", _re)
from database import get_conn, init_db, rows_to_list, USE_PG
from werkzeug.utils import secure_filename

app = Flask(__name__)
# Secret key muhit o'zgaruvchisidan olinadi (deploy da majburiy)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_urlsafe(32))

_cors_origins = os.environ.get("ALLOWED_ORIGINS", "").strip()
_origins = _cors_origins.split(",") if _cors_origins else ["*"]
CORS(app, supports_credentials=True, origins=_origins,
     allow_headers=["Content-Type", "X-Admin-Token", "X-Kitchen-Token", "X-Session-Token", "X-Staff-Pin"],
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])

# ===== RATE LIMITER =====
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["5000/day", "1000/hour"],
    storage_uri="memory://",
    headers_enabled=True,
)

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
ALLOWED_EXT = {"png", "jpg", "jpeg", "gif", "webp"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

# init_db() fon threadida — gunicorn darhol portga bog'lanadi, health check bloklanmaydi
_db_ready = False
def _init_db_background():
    global _db_ready
    try:
        init_db()
        _db_ready = True
        log.info("DB init muvaffaqiyatli yakunlandi")
    except Exception as _e:
        log.error("DB init xato: %s", _e)

threading.Thread(target=_init_db_background, daemon=True).start()

TG_TOKEN      = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT       = os.environ.get("TELEGRAM_CHAT_ID", "")
KITCHEN_TOKEN = os.environ.get("KITCHEN_TOKEN", "")

# ===== XAVFSIZLIK KONSTANTALARI =====
TOKEN_TTL_HOURS = 8          # Smena uzunligi
PBKDF2_ITERATIONS = 200_000  # NIST tavsiyasi 2024
ALLOWED_PERIODS = {"daily", "weekly", "monthly"}

# ===== TOKEN BOSHQARUVI (in-memory, single-process) =====
# Multi-worker (Gunicorn) uchun Redis ishlatish tavsiya etiladi
_tokens_lock = threading.Lock()
ACTIVE_TOKENS: dict = {}  # token -> {"created": datetime, "ip": str}

# ===== PIN BRUTE-FORCE HIMOYA =====
_pin_fails: dict = {}  # ip -> {"count": int, "last": datetime}
_pin_fails_lock = threading.Lock()
PIN_MAX_TRIES = 5
PIN_LOCKOUT_MINUTES = 15

def _pin_check_locked(ip: str) -> bool:
    """True qaytarsa — IP bloklangan."""
    if _redis:
        return int(_redis.get(f"pin_fail:{ip}") or 0) >= PIN_MAX_TRIES
    with _pin_fails_lock:
        rec = _pin_fails.get(ip)
        if not rec:
            return False
        if rec["count"] < PIN_MAX_TRIES:
            return False
        elapsed = (datetime.datetime.utcnow() - rec["last"]).total_seconds()
        if elapsed > PIN_LOCKOUT_MINUTES * 60:
            del _pin_fails[ip]
            return False
        return True

def _pin_record_fail(ip: str):
    if _redis:
        pipe = _redis.pipeline()
        pipe.incr(f"pin_fail:{ip}")
        pipe.expire(f"pin_fail:{ip}", PIN_LOCKOUT_MINUTES * 60)
        pipe.execute()
        return
    with _pin_fails_lock:
        rec = _pin_fails.setdefault(ip, {"count": 0, "last": datetime.datetime.utcnow()})
        rec["count"] += 1
        rec["last"] = datetime.datetime.utcnow()

def _pin_record_success(ip: str):
    if _redis:
        _redis.delete(f"pin_fail:{ip}")
        return
    with _pin_fails_lock:
        _pin_fails.pop(ip, None)

# ===== ROL VA RUXSATLAR =====
# "all" - to'liq kirish; boshqalar - faqat belgilangan imkoniyatlar
ROLE_PERMISSIONS: dict = {
    "admin":      {"all"},
    "director":   {"all"},
    "accountant": {"hr", "salary", "attendance", "finance", "inventory_view", "customer", "report"},
    "manager":    {"promo", "price", "order_view", "payment_view", "kitchen_view",
                   "discount", "void", "report", "table", "order"},
    "chef":       {"menu", "recipe", "inventory", "promo"},
    "cashier":    {"table", "order", "payment", "discount", "void", "customer", "receipt"},
    "waiter":     {"table", "order", "receipt"},
    "kitchen":    {"kitchen"},
    "cook":       {"kitchen"},
    "cleaner":    set(),
}

VALID_ROLES = set(ROLE_PERMISSIONS.keys())

def has_role(staff, *allowed_roles) -> bool:
    """Xodim kerakli rollardan birida ekanligini tekshiradi.
    admin/director har doim True qaytaradi."""
    if staff is None:
        return False
    role = staff.get("role", "")
    if role in ("admin", "director"):
        return True
    return role in allowed_roles

def staff_has_perm(staff, perm: str) -> bool:
    """Xodimda berilgan ruxsat borligini tekshiradi."""
    if staff is None:
        return False
    role = staff.get("role", "")
    perms = ROLE_PERMISSIONS.get(role, set())
    return "all" in perms or perm in perms

def _prune_expired_tokens():
    if _redis:
        return  # Redis TTL avtomatik o'chiradi
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=TOKEN_TTL_HOURS)
    with _tokens_lock:
        expired = [t for t, info in ACTIVE_TOKENS.items() if info["created"] < cutoff]
        for t in expired:
            del ACTIVE_TOKENS[t]

def create_admin_token(ip: str) -> str:
    _prune_expired_tokens()
    token = secrets.token_urlsafe(32)
    now = datetime.datetime.utcnow()
    if _redis:
        _redis.hset(f"rt:{token}", mapping={"ip": ip, "created": now.isoformat()})
        _redis.expire(f"rt:{token}", TOKEN_TTL_HOURS * 3600)
    else:
        with _tokens_lock:
            ACTIVE_TOKENS[token] = {"created": now, "last_used": now, "ip": ip}
    return token

def revoke_admin_token(token: str):
    if _redis:
        _redis.delete(f"rt:{token}")
    else:
        with _tokens_lock:
            ACTIVE_TOKENS.pop(token, None)

# ===== PAROL HASHING (pbkdf2_hmac + salt) =====
def hash_password(password: str, salt: bytes = None):
    """Yangi pbkdf2 hash yaratish. (hash_hex, salt_hex) qaytaradi."""
    if salt is None:
        salt = os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return h.hex(), salt.hex()

def verify_password(password: str, stored_hash: str, stored_salt: str) -> bool:
    """pbkdf2 hash tekshirish (timing-safe)."""
    try:
        salt = bytes.fromhex(stored_salt)
        h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
        return hmac.compare_digest(h.hex(), stored_hash)
    except Exception:
        return False

def verify_legacy_pin(pin: str, stored_hash: str) -> bool:
    """Eski format (sha256[:8]) — orqaga moslashuv uchun (timing-safe)."""
    try:
        legacy = hashlib.sha256(str(pin).encode()).hexdigest()[:8]
        return hmac.compare_digest(legacy, stored_hash)
    except Exception:
        return False


def tg_send(text):
    """Telegram guruhiga xabar yuborish"""
    if not TG_TOKEN or not TG_CHAT:
        return
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": TG_CHAT,
            "text": text,
            "parse_mode": "HTML"
        }).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        log.warning("tg_send xato: %s", e)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def check_image_mime(file_stream) -> bool:
    """Fayl MIME turini bytes darajasida tekshirish (kengaytmani aldab bo'lmaydi)."""
    try:
        header = file_stream.read(12)
        file_stream.seek(0)
        if header[:8] == b'\x89PNG\r\n\x1a\n':
            return True
        if header[:3] == b'\xff\xd8\xff':
            return True
        if header[:6] in (b'GIF87a', b'GIF89a'):
            return True
        if header[:4] == b'RIFF' and header[8:12] == b'WEBP':
            return True
        return False
    except Exception:
        return False


def check_kitchen_auth() -> bool:
    """Oshxona endpointlari uchun autentifikatsiya.
    Admin token, KITCHEN_TOKEN yoki kitchen/cook/manager/chef PIN bilan kirish mumkin."""
    if check_auth():
        return True
    # Xodim PIN bilan autentifikatsiya (kitchen/cook/manager/chef rollari)
    pin = request.headers.get("X-Staff-Pin", "")
    if pin:
        ip = get_remote_address()
        if _pin_check_locked(ip):
            return False
        staff = check_staff_pin(pin)
        if staff and has_role(staff, "kitchen", "cook", "manager", "chef"):
            _pin_record_success(ip)
            return True
        _pin_record_fail(ip)
        return False
    # KITCHEN_TOKEN tekshiruvi
    if not KITCHEN_TOKEN:
        log.warning("KITCHEN_TOKEN o'rnatilmagan — oshxona endpoint himoyasiz! ENV var qo'shing.")
        return False
    provided = (request.headers.get("X-Kitchen-Token", "")
                or request.args.get("kitchen_token", ""))
    if not provided:
        return False
    return hmac.compare_digest(provided, KITCHEN_TOKEN)


def _validate_str(val, max_len: int, field: str):
    """Matn uzunligini tekshirish. Juda uzun bo'lsa ValueError ko'taradi."""
    if val is not None and len(str(val)) > max_len:
        raise ValueError(f"{field} juda uzun (maksimum {max_len} belgi)")


def q(sql):
    """? -> %s for PostgreSQL"""
    return sql.replace("?", "%s") if USE_PG else sql


def get_setting(key):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(q("SELECT value FROM settings WHERE key=?"), (key,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return row["value"] if not USE_PG else row[0]


@app.before_request
def force_https():
    """Production da HTTP → HTTPS yo'naltirish (Render proxy orqali)."""
    if os.environ.get("FLASK_ENV") == "production":
        proto = request.headers.get("X-Forwarded-Proto", "https")
        if proto == "http":
            url = request.url.replace("http://", "https://", 1)
            return redirect(url, code=301)

@app.after_request
def add_security_headers(response):
    """Barcha javoblarga xavfsizlik headerlari qo'shish."""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    # HSTS — HTTPS ni 1 yilga majburlash (production da)
    if os.environ.get("FLASK_ENV") == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com https://cdnjs.cloudflare.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: blob: https:; "
        "connect-src 'self'; "
        "frame-ancestors 'none';"
    )
    return response


def check_auth() -> bool:
    """Token ni tekshirish (Redis yoki in-memory)."""
    token = request.headers.get("X-Admin-Token", "")
    if not token or len(token) < 32:
        return False
    if _redis:
        data = _redis.hgetall(f"rt:{token}")
        if not data:
            return False
        try:
            created = datetime.datetime.fromisoformat(data["created"])
        except Exception:
            return False
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=TOKEN_TTL_HOURS)
        if created < cutoff:
            _redis.delete(f"rt:{token}")
            return False
        _redis.hset(f"rt:{token}", "last_used", datetime.datetime.utcnow().isoformat())
        return True
    _prune_expired_tokens()
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=TOKEN_TTL_HOURS)
    with _tokens_lock:
        info = ACTIVE_TOKENS.get(token)
        if not info or info["created"] < cutoff:
            return False
        info["last_used"] = datetime.datetime.utcnow()
    return True


def audit(action: str, entity: str = None, entity_id: int = None,
          user_name: str = None, details: dict = None):
    """Muhim amalni audit_log jadvaliga yozish (bloklash yo'q — xato bo'lsa o'tkazib yuboradi)."""
    ip = get_remote_address()
    det = json.dumps(details, ensure_ascii=False) if details else None
    try:
        conn = get_conn()
        db_exec(conn,
            "INSERT INTO audit_log (action, entity, entity_id, user_name, user_ip, details) VALUES (?,?,?,?,?,?)",
            (action, entity, entity_id, user_name, ip, det))
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning("audit() xato: %s", e)


def check_staff_pin(pin, conn=None):
    """PIN to'g'ri xodimga tegishli ekanligini tekshiradi (yangi + eski format)."""
    if not pin:
        return None
    pin_str = str(pin)
    close = conn is None
    if close:
        conn = get_conn()
    # Barcha aktiv xodimlarni olamiz (PIN ni hash qilib solishtiramiz)
    cur = db_exec(conn, "SELECT * FROM staff WHERE active=1", ())
    all_staff = rows_to_list(cur)
    found = None
    for s in all_staff:
        if not s.get("pin"):
            continue
        if s.get("pin_salt"):
            # Yangi pbkdf2 format
            if verify_password(pin_str, s["pin"], s["pin_salt"]):
                found = s
                break
        else:
            # Eski sha256[:8] format (orqaga moslashuv)
            if verify_legacy_pin(pin_str, s["pin"]):
                found = s
                break
    if close:
        conn.close()
    return found


def db_exec(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(q(sql), params)
    return cur


# ===== AUTH =====
@app.route("/api/login", methods=["POST"])
@limiter.limit("5 per minute; 20 per hour")
def login():
    """
    Admin login. Parol pbkdf2 bilan tekshiriladi.
    Eski plaintext parollar ham ishla­ydi (birinchi kirish­da avtomatik
    yangi hash ga o'tkaziladi).
    """
    data = request.json or {}
    password = data.get("password", "")
    if not password:
        return jsonify({"ok": False, "error": "Parol kiritilmadi"}), 400

    stored_hash = get_setting("admin_password_hash")
    stored_salt = get_setting("admin_password_salt")
    stored_plain = get_setting("admin_password")
    # Env var dan yoki hardcoded default (faqat DB da hech narsa yo'q bo'lsa)
    fallback_plain = os.environ.get("ADMIN_PASSWORD", "rayyon2024")

    authenticated = False
    if stored_hash and stored_salt:
        authenticated = verify_password(password, stored_hash, stored_salt)
    else:
        # Plaintext tekshirish: DB dagi yoki env var default
        candidate = stored_plain or fallback_plain
        if hmac.compare_digest(password, candidate):
            authenticated = True
            # Zudlik bilan pbkdf2 hash ga o'tkazish
            new_hash, new_salt = hash_password(password)
            conn2 = get_conn()
            if USE_PG:
                for k, v in [("admin_password_hash", new_hash), ("admin_password_salt", new_salt)]:
                    db_exec(conn2,
                        "INSERT INTO settings (key,value) VALUES (%s,%s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",
                        (k, v))
                # Plaintext ni bazadan o'chirish
                db_exec(conn2, "DELETE FROM settings WHERE key=%s", ("admin_password",))
            else:
                db_exec(conn2, "INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", ("admin_password_hash", new_hash))
                db_exec(conn2, "INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", ("admin_password_salt", new_salt))
                db_exec(conn2, "DELETE FROM settings WHERE key=?", ("admin_password",))
            conn2.commit(); conn2.close()

    if not authenticated:
        time.sleep(0.3)  # Vaqt hujumiga qarshi kechiktirish
        return jsonify({"ok": False, "error": "Parol noto'g'ri"}), 401

    ip = get_remote_address()
    token = create_admin_token(ip)
    audit("login", "admin", user_name="admin")
    return jsonify({"ok": True, "token": token, "ttl_hours": TOKEN_TTL_HOURS})


@app.route("/api/logout", methods=["POST"])
def logout():
    token = request.headers.get("X-Admin-Token", "")
    revoke_admin_token(token)
    audit("logout", "admin", user_name="admin")
    return jsonify({"ok": True})


@app.route("/api/auth/check", methods=["GET"])
def auth_check():
    """Token hali ham amal qilishini tekshirish."""
    return jsonify({"ok": check_auth()})


@app.route("/api/staff/login", methods=["POST"])
@limiter.limit("5 per minute; 30 per hour")
def staff_login():
    """PIN bilan xodim tizimga kirishi — rol bo'yicha yo'naltiradi.
    Qaytaradi: {ok, name, role, id, redirect}
    redirect: cashier | waiter | kitchen | chef | manager | accountant | director
    """
    ip = get_remote_address()
    if _pin_check_locked(ip):
        return jsonify({"ok": False, "error": f"Juda ko'p urinish. {PIN_LOCKOUT_MINUTES} daqiqadan keyin qayta urinib ko'ring."}), 429

    d = request.json or {}
    pin = str(d.get("pin", "")).strip()
    if not pin:
        return jsonify({"ok": False, "error": "PIN kiritilmadi"}), 400

    staff = check_staff_pin(pin)
    if not staff:
        _pin_record_fail(ip)
        time.sleep(0.3)
        return jsonify({"ok": False, "error": "PIN noto'g'ri"}), 401
    _pin_record_success(ip)

    role = staff.get("role", "waiter")
    redirect_map = {
        "admin":      "admin",
        "director":   "director",
        "accountant": "accountant",
        "manager":    "manager",
        "chef":       "chef",
        "cashier":    "cashier",
        "waiter":     "waiter",
        "kitchen":    "kitchen",
    }
    redirect = redirect_map.get(role, "waiter")

    # Panel rollar uchun admin token ham beramiz (admin panelga kirish uchun)
    panel_roles = {"admin", "director", "accountant", "manager", "chef"}
    token = None
    if role in panel_roles:
        ip = get_remote_address()
        token = create_admin_token(ip)

    resp = {
        "ok": True,
        "id": staff["id"],
        "name": staff["name"],
        "role": role,
        "redirect": redirect,
    }
    if token:
        resp["token"] = token
    return jsonify(resp)


# ===== MENU =====
@app.route("/api/menu", methods=["GET"])
def get_menu():
    conn = get_conn()
    category = request.args.get("category")
    if category and category != "all":
        cur = db_exec(conn, "SELECT * FROM menu WHERE category=? ORDER BY id", (category,))
    else:
        cur = db_exec(conn, "SELECT * FROM menu ORDER BY category, id")
    result = rows_to_list(cur)
    conn.close()
    return jsonify(result)


@app.route("/api/menu", methods=["POST"])
def add_menu():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    try:
        _validate_str(d.get("name"), 100, "Taom nomi")
        _validate_str(d.get("description"), 500, "Tavsif")
        _validate_str(d.get("emoji"), 10, "Emoji")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    conn = get_conn()
    db_exec(conn,
        "INSERT INTO menu (name, category, description, price, emoji, available) VALUES (?,?,?,?,?,?)",
        (d.get("name"), d.get("category"), d.get("description"), d.get("price"), d.get("emoji", "🍽"), d.get("available", 1))
    )
    conn.commit(); conn.close()
    audit("menu_add", "menu", user_name="admin", details={"name": d.get("name"), "price": d.get("price")})
    return jsonify({"ok": True})


@app.route("/api/menu/<int:item_id>", methods=["PUT"])
def update_menu(item_id):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    try:
        _validate_str(d.get("name"), 100, "Taom nomi")
        _validate_str(d.get("description"), 500, "Tavsif")
        _validate_str(d.get("emoji"), 10, "Emoji")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    conn = get_conn()
    db_exec(conn,
        "UPDATE menu SET name=?, category=?, description=?, price=?, emoji=?, available=? WHERE id=?",
        (d.get("name"), d.get("category"), d.get("description"), d.get("price"), d.get("emoji", "🍽"), d.get("available", 1), item_id)
    )
    conn.commit(); conn.close()
    audit("menu_update", "menu", item_id, "admin", {"name": d.get("name"), "price": d.get("price")})
    return jsonify({"ok": True})


@app.route("/api/menu/<int:item_id>", methods=["DELETE"])
def delete_menu(item_id):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    db_exec(conn, "DELETE FROM menu WHERE id=?", (item_id,))
    conn.commit(); conn.close()
    audit("menu_delete", "menu", item_id, "admin")
    return jsonify({"ok": True})


# ===== ORDERS =====
@app.route("/api/orders", methods=["GET"])
def get_orders():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    limit  = min(int(request.args.get("limit",  200)), 1000)
    offset = max(int(request.args.get("offset", 0)),   0)
    status = request.args.get("status")
    conn   = get_conn()
    if status:
        cur = db_exec(conn,
            "SELECT * FROM orders WHERE status=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (status, limit, offset))
    else:
        cur = db_exec(conn,
            "SELECT * FROM orders ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset))
    result = rows_to_list(cur)
    conn.close()
    return jsonify({"data": result, "limit": limit, "offset": offset, "count": len(result)})


@app.route("/api/orders", methods=["POST"])
@limiter.limit("20 per minute; 200 per hour")
def add_order():
    d = request.json or {}
    try:
        _validate_str(d.get("item_name"),     200, "Taom nomi")
        _validate_str(d.get("customer_name"), 100, "Ism")
        _validate_str(d.get("customer_phone"), 20, "Telefon")
        _validate_str(d.get("note"),          500, "Izoh")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    conn = get_conn()
    db_exec(conn,
        "INSERT INTO orders (item_name, item_id, quantity, total_price, customer_name, customer_phone, note) VALUES (?,?,?,?,?,?,?)",
        (d.get("item_name"), d.get("item_id"), d.get("quantity", 1),
         d.get("total_price"), d.get("customer_name"), d.get("customer_phone"), d.get("note"))
    )
    conn.commit(); conn.close()
    tg_send(
        f"🛒 <b>Yangi buyurtma!</b>\n"
        f"📌 Taom: {d.get('item_name')} x{d.get('quantity',1)}\n"
        f"💰 Narx: {d.get('total_price',0):,} so'm\n"
        f"👤 Mijoz: {d.get('customer_name')}\n"
        f"📞 Telefon: {d.get('customer_phone')}\n"
        + (f"📝 Izoh: {d.get('note')}" if d.get("note") else "")
    )
    return jsonify({"ok": True})


@app.route("/api/orders/<int:order_id>", methods=["PUT"])
def update_order(order_id):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    db_exec(conn, "UPDATE orders SET status=? WHERE id=?", (d.get("status"), order_id))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


# ===== RESERVATIONS =====
@app.route("/api/reservations", methods=["GET"])
def get_reservations():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    limit  = min(int(request.args.get("limit",  200)), 1000)
    offset = max(int(request.args.get("offset", 0)),   0)
    date   = request.args.get("date")
    conn   = get_conn()
    if date:
        cur = db_exec(conn,
            "SELECT * FROM reservations WHERE date=? ORDER BY time ASC LIMIT ? OFFSET ?",
            (date, limit, offset))
    else:
        cur = db_exec(conn,
            "SELECT * FROM reservations ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset))
    result = rows_to_list(cur)
    conn.close()
    return jsonify({"data": result, "limit": limit, "offset": offset, "count": len(result)})


@app.route("/api/reservations", methods=["POST"])
@limiter.limit("10 per minute; 50 per hour")
def add_reservation():
    d = request.json or {}
    try:
        _validate_str(d.get("customer_name"),  100, "Ism")
        _validate_str(d.get("customer_phone"),  20, "Telefon")
        _validate_str(d.get("note"),           500, "Izoh")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    conn = get_conn()
    db_exec(conn,
        "INSERT INTO reservations (customer_name, customer_phone, date, time, guests, note) VALUES (?,?,?,?,?,?)",
        (d.get("customer_name"), d.get("customer_phone"), d.get("date"), d.get("time"), d.get("guests", 2), d.get("note"))
    )
    conn.commit(); conn.close()
    tg_send(
        f"📅 <b>Yangi bron!</b>\n"
        f"👤 Mijoz: {d.get('customer_name')}\n"
        f"📞 Telefon: {d.get('customer_phone')}\n"
        f"📆 Sana: {d.get('date')} {d.get('time')}\n"
        f"👥 Mehmonlar: {d.get('guests',2)} kishi\n"
        + (f"📝 Izoh: {d.get('note')}" if d.get("note") else "")
    )
    return jsonify({"ok": True})


@app.route("/api/reservations/<int:res_id>", methods=["PUT"])
def update_reservation(res_id):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d      = request.json or {}
    status = d.get("status")
    conn   = get_conn()
    db_exec(conn, "UPDATE reservations SET status=? WHERE id=?", (status, res_id))
    # Tasdiqlanganda va stol_id berilgan bo'lsa — stolni band qilish
    table_id = d.get("table_id")
    if status == "confirmed" and table_id:
        cur = db_exec(conn, "SELECT status FROM tables WHERE id=?", (table_id,))
        row = cur.fetchone()
        tbl_status = (row[0] if USE_PG else row["status"]) if row else None
        if tbl_status == "free":
            db_exec(conn, "UPDATE tables SET status='reserved' WHERE id=?", (table_id,))
            db_exec(conn, "UPDATE reservations SET table_id=? WHERE id=?", (table_id, res_id))
    # Bekor qilinganda stol bo'shatish
    elif status == "cancelled":
        cur2 = db_exec(conn, "SELECT table_id FROM reservations WHERE id=?", (res_id,))
        row2 = cur2.fetchone()
        if row2:
            tid = row2[0] if USE_PG else row2["table_id"]
            if tid:
                db_exec(conn, "UPDATE tables SET status='free' WHERE id=? AND status='reserved'", (tid,))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


# ===== NEWS =====
@app.route("/api/news", methods=["GET"])
def get_news():
    conn = get_conn()
    if request.args.get("active") == "1":
        cur = db_exec(conn, "SELECT * FROM news WHERE active=1 ORDER BY created_at DESC")
    else:
        cur = db_exec(conn, "SELECT * FROM news ORDER BY created_at DESC")
    result = rows_to_list(cur)
    conn.close()
    return jsonify(result)


@app.route("/api/news", methods=["POST"])
def add_news():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    try:
        _validate_str(d.get("title"), 200, "Sarlavha")
        _validate_str(d.get("content"), 2000, "Matn")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    try:
        conn = get_conn()
        db_exec(conn,
            "INSERT INTO news (title, content, image, active) VALUES (?,?,?,?)",
            (d.get("title"), d.get("content"), d.get("image"), d.get("active", 1))
        )
        conn.commit(); conn.close()
    except Exception as e:
        log.error("add_news DB xato: %s", e)
        return jsonify({"error": f"DB xato: {e}"}), 500
    return jsonify({"ok": True})


@app.route("/api/news/<int:news_id>", methods=["PUT"])
def update_news(news_id):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    db_exec(conn,
        "UPDATE news SET title=?, content=?, active=? WHERE id=?",
        (d.get("title"), d.get("content"), d.get("active", 1), news_id)
    )
    conn.commit(); conn.close()
    return jsonify({"ok": True})


@app.route("/api/news/<int:news_id>", methods=["DELETE"])
def delete_news(news_id):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    db_exec(conn, "DELETE FROM news WHERE id=?", (news_id,))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


# ===== IMAGE UPLOAD =====
@app.route("/api/upload", methods=["POST"])
def upload_image():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    if "file" not in request.files: return jsonify({"error": "Fayl topilmadi"}), 400
    file = request.files["file"]
    if file.filename == "" or not allowed_file(file.filename):
        return jsonify({"error": "Noto'g'ri fayl turi (png, jpg, gif, webp)"}), 400
    if not check_image_mime(file.stream):
        return jsonify({"error": "Fayl mazmuni rasm emas (MIME tekshiruvi muvaffaqiyatsiz)"}), 400
    filename = str(int(time.time())) + "_" + secure_filename(file.filename)
    file.save(os.path.join(UPLOAD_FOLDER, filename))
    return jsonify({"ok": True, "url": f"/uploads/{filename}"})


@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


# ===== SETTINGS =====
PUBLIC_SETTINGS = {"restaurant_name", "phone", "address", "working_hours", "telegram_bot"}

@app.route("/api/settings", methods=["GET"])
def get_settings():
    conn = get_conn()
    cur = db_exec(conn, "SELECT key, value FROM settings")
    rows = cur.fetchall()
    conn.close()
    if USE_PG:
        all_s = {r[0]: r[1] for r in rows}
    else:
        all_s = {r["key"]: r["value"] for r in rows}
    # Admin bo'lmasa faqat public sozlamalarni qaytarish
    if not check_auth():
        public = [{"key": k, "value": v} for k, v in all_s.items() if k in PUBLIC_SETTINGS]
        return jsonify(public)
    return jsonify(all_s)


@app.route("/api/settings", methods=["PUT"])
def update_settings():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    for key, val in d.items():
        # Parol o'zgartirish: darhol pbkdf2 bilan hash qilib saqlash
        if key == "admin_password":
            if not val or len(str(val)) < 6:
                conn.close()
                return jsonify({"error": "Parol kamida 6 belgi bo'lishi kerak"}), 400
            new_hash, new_salt = hash_password(str(val))
            if USE_PG:
                db_exec(conn, "INSERT INTO settings (key,value) VALUES (%s,%s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value", ("admin_password_hash", new_hash))
                db_exec(conn, "INSERT INTO settings (key,value) VALUES (%s,%s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value", ("admin_password_salt", new_salt))
                db_exec(conn, "DELETE FROM settings WHERE key='admin_password'")
            else:
                db_exec(conn, "INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", ("admin_password_hash", new_hash))
                db_exec(conn, "INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", ("admin_password_salt", new_salt))
                db_exec(conn, "DELETE FROM settings WHERE key=?", ("admin_password",))
            continue
        if USE_PG:
            db_exec(conn, "INSERT INTO settings (key,value) VALUES (%s,%s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value", (key, str(val)))
        else:
            db_exec(conn, "INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, str(val)))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


# ===== STATS =====
@app.route("/api/stats", methods=["GET"])
def get_stats():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()

    def val(sql):
        cur = db_exec(conn, sql)
        row = cur.fetchone()
        return row[0] if row else 0

    if USE_PG:
        rev_sql        = "SELECT COALESCE(SUM(amount),0) FROM payments WHERE created_at::date = CURRENT_DATE"
        res_today_sql  = "SELECT COUNT(*) FROM reservations WHERE date=CURRENT_DATE::text"
        active_ses_sql = "SELECT COUNT(*) FROM sessions WHERE status='active'"
        closed_sql     = "SELECT COUNT(*) FROM sessions WHERE status='closed' AND closed_at::date = CURRENT_DATE"
    else:
        rev_sql        = "SELECT COALESCE(SUM(amount),0) FROM payments WHERE date(created_at,'localtime')=date('now','localtime')"
        res_today_sql  = "SELECT COUNT(*) FROM reservations WHERE date=date('now','localtime')"
        active_ses_sql = "SELECT COUNT(*) FROM sessions WHERE status='active'"
        closed_sql     = "SELECT COUNT(*) FROM sessions WHERE status='closed' AND date(closed_at,'localtime')=date('now','localtime')"

    result = {
        "revenue":            val(rev_sql),
        "active_sessions":    val(active_ses_sql),
        "closed_today":       val(closed_sql),
        "reservations_today": val(res_today_sql),
        "reservations_new":   val("SELECT COUNT(*) FROM reservations WHERE status='new'"),
        "menu_count":         val("SELECT COUNT(*) FROM menu WHERE available=1"),
        # Eski maydonlar — website buyurtmalari uchun (orqaga moslik)
        "orders_total": val("SELECT COUNT(*) FROM orders"),
        "orders_new":   val("SELECT COUNT(*) FROM orders WHERE status='new'"),
    }
    conn.close()
    return jsonify(result)


# ===== STOLLAR =====
@app.route("/api/tables", methods=["GET"])
def get_tables():
    conn = get_conn()
    cur  = db_exec(conn, """
        SELECT t.*, s.opened_at, s.total_amount, s.token, s.waiter_name
        FROM tables t
        LEFT JOIN sessions s ON t.current_session_id = s.id
        ORDER BY t.number
    """)
    tables = rows_to_list(cur)
    conn.close()
    # Har bir stol uchun ochiq vaqtni hisoblash
    for tbl in tables:
        if tbl.get("opened_at"):
            import datetime
            opened = tbl["opened_at"]
            if isinstance(opened, str):
                try: opened = datetime.datetime.fromisoformat(opened.replace("Z",""))
                except: opened = None
            if opened:
                diff = datetime.datetime.utcnow() - opened.replace(tzinfo=None)
                tbl["minutes_open"] = int(diff.total_seconds() // 60)
    return jsonify(tables)

@app.route("/api/tables", methods=["POST"])
def add_table():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    db_exec(conn, "INSERT INTO tables (number, name, capacity) VALUES (?,?,?)",
        (d.get("number"), d.get("name", f"Stol {d.get('number')}"), d.get("capacity", 4)))
    conn.commit(); conn.close()
    return jsonify({"ok": True})

@app.route("/api/tables/<int:tid>", methods=["PUT"])
def update_table(tid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    db_exec(conn, "UPDATE tables SET number=?, name=?, capacity=? WHERE id=?",
        (d.get("number"), d.get("name"), d.get("capacity", 4), tid))
    conn.commit(); conn.close()
    return jsonify({"ok": True})

@app.route("/api/tables/<int:tid>", methods=["DELETE"])
def delete_table(tid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    db_exec(conn, "DELETE FROM tables WHERE id=?", (tid,))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


# ===== SESSIYALAR =====
@app.route("/api/session/open", methods=["POST"])
def open_session():
    """Stol ochish — kassir yoki ofitsiant tomonidan"""
    d = request.json or {}
    staff = check_staff_pin(d.get("waiter_pin")) if d.get("waiter_pin") else None
    if not check_auth() and not staff:
        return jsonify({"error": "Ruxsat yo'q"}), 403
    if staff and not has_role(staff, "waiter", "cashier", "manager"):
        return jsonify({"error": "Faqat ofitsiant yoki kassir stol ocha oladi"}), 403
    if staff and not d.get("waiter_name"):
        d["waiter_name"] = staff["name"]
    table_id = d.get("table_id")
    conn = get_conn()
    # Stol mavjudligini tekshirish
    cur = db_exec(conn, "SELECT * FROM tables WHERE id=?", (table_id,))
    tbl = rows_to_list(cur)
    if not tbl: conn.close(); return jsonify({"error": "Stol topilmadi"}), 404
    tbl = tbl[0]
    if tbl["status"] != "free" and tbl.get("current_session_id"):
        conn.close()
        return jsonify({"error": "Stol band", "session_id": tbl["current_session_id"]}), 409
    # Noyob token yaratish
    token = secrets.token_urlsafe(12)
    db_exec(conn, """INSERT INTO sessions (table_id, table_number, token, waiter_id, waiter_name, service_charge)
        VALUES (?,?,?,?,?,?)""",
        (table_id, tbl["number"], token, d.get("waiter_id"), d.get("waiter_name",""), d.get("service_charge", 0)))
    # session id olish
    cur2 = db_exec(conn, "SELECT id FROM sessions WHERE token=?", (token,))
    row  = cur2.fetchone()
    sid  = row[0] if USE_PG else row["id"]
    db_exec(conn, "UPDATE tables SET status='occupied', current_session_id=? WHERE id=?", (sid, table_id))
    conn.commit(); conn.close()
    return jsonify({"ok": True, "token": token, "session_id": sid, "table_number": tbl["number"]})

@app.route("/api/session/validate", methods=["GET"])
def validate_session():
    """QR token tekshirish (24 soatlik TTL bilan)."""
    token = request.args.get("token")
    if not token: return jsonify({"valid": False}), 400
    conn = get_conn()
    cur  = db_exec(conn, "SELECT * FROM sessions WHERE token=? AND status='active'", (token,))
    rows = rows_to_list(cur)
    conn.close()
    if not rows: return jsonify({"valid": False, "error": "Token eskirgan yoki noto'g'ri"}), 404
    s = rows[0]
    # QR token muddatini tekshirish (24 soat)
    opened = s.get("opened_at")
    if opened:
        if isinstance(opened, str):
            try:
                opened = datetime.datetime.fromisoformat(opened.replace("Z", ""))
            except Exception:
                opened = None
        if opened:
            age_hours = (datetime.datetime.utcnow() - opened.replace(tzinfo=None)).total_seconds() / 3600
            if age_hours > 24:
                return jsonify({"valid": False, "error": "QR token eskirgan (24 soatdan ortiq)"}), 404
    return jsonify({"valid": True, "table_number": s["table_number"], "session_id": s["id"]})

@app.route("/api/session/<int:sid>", methods=["GET"])
def get_session(sid):
    """Sessiya ma'lumotlari va barcha buyurtmalar"""
    token = request.headers.get("X-Session-Token","")
    conn  = get_conn()
    cur   = db_exec(conn, "SELECT * FROM sessions WHERE id=?", (sid,))
    rows  = rows_to_list(cur)
    if not rows: conn.close(); return jsonify({"error": "Topilmadi"}), 404
    s = rows[0]
    # Token yoki admin tekshirish
    if s["token"] != token and not check_auth():
        conn.close(); return jsonify({"error": "Ruxsat yo'q"}), 403
    cur2 = db_exec(conn, "SELECT * FROM order_items WHERE session_id=? ORDER BY created_at", (sid,))
    items = rows_to_list(cur2)
    cur3  = db_exec(conn, "SELECT * FROM payments WHERE session_id=?", (sid,))
    payments = rows_to_list(cur3)
    conn.close()
    total = sum(i["total_price"] for i in items if i["status"] != "cancelled")
    sc    = total * s.get("service_charge", 0) / 100
    disc  = total * s.get("discount", 0) / 100
    return jsonify({**s, "items": items, "payments": payments,
                    "subtotal": total, "service_charge_amount": int(sc),
                    "discount_amount": int(disc), "grand_total": int(total + sc - disc)})

@app.route("/api/session/<int:sid>/order", methods=["POST"])
def add_order_item(sid):
    """Sessiyaga buyurtma qo'shish"""
    token = request.headers.get("X-Session-Token","")
    conn  = get_conn()
    cur   = db_exec(conn, "SELECT * FROM sessions WHERE id=? AND status='active'", (sid,))
    rows  = rows_to_list(cur)
    if not rows: conn.close(); return jsonify({"error": "Sessiya topilmadi yoki yopilgan"}), 404
    s = rows[0]
    body = request.json or {}
    staff = check_staff_pin(body.get("waiter_pin"), conn) if body.get("waiter_pin") else None
    if s["token"] != token and not check_auth() and not staff:
        conn.close(); return jsonify({"error": "Ruxsat yo'q"}), 403
    if staff and not has_role(staff, "waiter", "cashier", "manager"):
        conn.close(); return jsonify({"error": "Faqat ofitsiant yoki kassir buyurtma bera oladi"}), 403
    items = body.get("items", [])
    if not items: conn.close(); return jsonify({"error": "Buyurtma bo'sh"}), 400
    # Input validatsiyasi
    for item in items:
        try:
            _validate_str(item.get("name"), 100, "Taom nomi")
            _validate_str(item.get("comment"), 500, "Izoh")
        except ValueError as e:
            conn.close()
            return jsonify({"error": str(e)}), 400
    waiter_name_fallback = staff["name"] if staff else ""
    for item in items:
        total = item.get("price",0) * item.get("quantity",1)
        db_exec(conn, """INSERT INTO order_items
            (session_id, table_number, menu_item_id, item_name, item_emoji, item_price, quantity,
             total_price, comment, course, category, waiter_id, waiter_name)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sid, s["table_number"], item.get("menu_item_id"), item.get("name"),
             item.get("emoji","🍽"), item.get("price",0), item.get("quantity",1),
             total, item.get("comment",""), item.get("course",1),
             item.get("category",""), item.get("waiter_id"), item.get("waiter_name") or waiter_name_fallback))
    conn.commit()
    # Umumiy summani yangilash
    cur2 = db_exec(conn, "SELECT SUM(total_price) FROM order_items WHERE session_id=? AND status!='cancelled'", (sid,))
    row  = cur2.fetchone()
    total_sum = (row[0] or 0)
    db_exec(conn, "UPDATE sessions SET total_amount=? WHERE id=?", (total_sum, sid))
    conn.commit(); conn.close()
    # Telegram xabarnomasi
    names = ", ".join(f"{i.get('name')} x{i.get('quantity',1)}" for i in items)
    tg_send(f"🍽 <b>Stol #{s['table_number']} — Yangi buyurtma!</b>\n{names}")
    _sse_broadcast("new_order", {"session_id": sid, "table": s["table_number"], "items": names})
    return jsonify({"ok": True})

@app.route("/api/session/<int:sid>/item/<int:iid>/status", methods=["PUT"])
def update_item_status(sid, iid):
    """Buyurtma item statusini o'zgartirish (oshxona/ofitsiant)"""
    d    = request.json or {}
    status = d.get("status")
    valid  = ["pending","cooking","ready","served","cancelled"]
    if status not in valid: return jsonify({"error": "Noto'g'ri status"}), 400

    # Autentifikatsiya: admin token YOKI PIN YOKI kitchen token
    staff = check_staff_pin(d.get("pin")) if d.get("pin") else None
    is_authed = check_auth() or check_kitchen_auth() or (staff is not None)
    if not is_authed:
        return jsonify({"error": "Ruxsat yo'q — PIN yoki token kerak"}), 403

    # Cancel uchun faqat admin
    if status == "cancelled" and not check_auth():
        return jsonify({"error": "Bekor qilish uchun admin ruxsati kerak"}), 403
    conn = get_conn()
    # Oldingi item ma'lumotlarini olib qo'yish (deduct uchun)
    pre_cur = db_exec(conn, "SELECT * FROM order_items WHERE id=? AND session_id=?", (iid, sid))
    pre_rows = rows_to_list(pre_cur)
    db_exec(conn, "UPDATE order_items SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=? AND session_id=?",
        (status, iid, sid))
    # Agar tayyorlash boshlansa → ombordan chiqarish
    if status == "cooking" and pre_rows:
        item = pre_rows[0]
        if item["status"] == "pending":  # faqat bir marta chiqarish
            try:
                deduct_inventory(item["menu_item_id"], item["quantity"], conn,
                    f"Stol #{item['table_number']} — {item['item_name']}")
            except Exception:
                pass  # ombor moduli bo'lmasa ham ishlaydi
    # Agar tayyor bo'lsa → Telegram ga xabar
    if status == "ready" and pre_rows:
        item = pre_rows[0]
        tg_send(f"✅ <b>Stol #{item['table_number']} — Tayyor!</b>\n🍽 {item['item_name']}\nOfitsiant olib keling!")
        _sse_broadcast("item_ready", {"session_id": sid, "item_id": iid,
                                      "item_name": item["item_name"], "table": item.get("table_number")})
    elif status == "cooking" and pre_rows:
        _sse_broadcast("item_cooking", {"session_id": sid, "item_id": iid,
                                        "item_name": pre_rows[0]["item_name"]})
    conn.commit(); conn.close()
    return jsonify({"ok": True})

@app.route("/api/session/<int:sid>/bill", methods=["POST"])
def request_bill(sid):
    """Mijoz hisob so'radi"""
    token = request.headers.get("X-Session-Token","")
    conn  = get_conn()
    cur   = db_exec(conn, "SELECT * FROM sessions WHERE id=? AND status='active'", (sid,))
    rows  = rows_to_list(cur)
    if not rows: conn.close(); return jsonify({"error": "Sessiya topilmadi"}), 404
    s = rows[0]
    if s["token"] != token and not check_auth():
        conn.close(); return jsonify({"error": "Ruxsat yo'q"}), 403
    db_exec(conn, "UPDATE tables SET status='bill_requested' WHERE number=?", (s["table_number"],))
    conn.commit(); conn.close()
    tg_send(f"🧾 <b>Stol #{s['table_number']} — Hisob so'radi!</b>\nJami: {s.get('total_amount',0):,} so'm")
    return jsonify({"ok": True})

def _calc_session_total(sid, conn) -> int:
    """Sessiya umumiy summasini server tomonida hisoblash (frontend ga ishonmaydi)."""
    # Bekor qilinmagan itemlar summasi
    cur = db_exec(conn,
        "SELECT COALESCE(SUM(total_price),0) FROM order_items WHERE session_id=? AND status!='cancelled'",
        (sid,))
    row = cur.fetchone()
    subtotal = int(row[0] if row and row[0] else 0)
    # Xizmat haqi va chegirmani sessiyadan olish
    cur2 = db_exec(conn, "SELECT service_charge, discount FROM sessions WHERE id=?", (sid,))
    srow = cur2.fetchone()
    sc_pct = disc_pct = 0
    if srow:
        sc_raw   = srow[0] if USE_PG else srow["service_charge"]
        disc_raw = srow[1] if USE_PG else srow["discount"]
        sc_pct   = float(sc_raw   if sc_raw   is not None else 0)
        disc_pct = float(disc_raw if disc_raw is not None else 0)
    sc_amount   = int(subtotal * sc_pct   / 100)
    disc_amount = int(subtotal * disc_pct / 100)
    return subtotal + sc_amount - disc_amount


@app.route("/api/session/<int:sid>/close", methods=["POST"])
def close_session(sid):
    """Sessiyani yopish va to'lovni qayd etish (server-da summa tekshiriladi)."""
    d    = request.json or {}
    staff = check_staff_pin(d.get("pin")) if d.get("pin") else None
    if not check_auth() and not staff:
        return jsonify({"error": "Ruxsat yo'q"}), 403
    if staff and not has_role(staff, "cashier", "manager"):
        return jsonify({"error": "Faqat kassir to'lov qabul qila oladi"}), 403
    conn = get_conn()
    cur  = db_exec(conn, "SELECT * FROM sessions WHERE id=?", (sid,))
    rows = rows_to_list(cur)
    if not rows: conn.close(); return jsonify({"error": "Topilmadi"}), 404
    s = rows[0]

    # V5: Server tomonida haqiqiy summani hisoblash
    server_total = _calc_session_total(sid, conn)
    payments     = d.get("payments", [])
    client_total = sum(int(p.get("amount", 0)) for p in payments)

    # Tolerans ±500 so'm (yaxlitlash uchun)
    if server_total > 0 and abs(server_total - client_total) > 500:
        conn.close()
        return jsonify({
            "error": "To'lov miqdori mos emas",
            "server_total": server_total,
            "client_total": client_total,
        }), 400

    cashier_name = d.get("cashier_name") or (staff["name"] if staff else "")
    cashier_id   = d.get("cashier_id")   or (staff["id"]   if staff else None)
    shift_id     = d.get("shift_id")

    try:
        for p in payments:
            db_exec(conn,
                "INSERT INTO payments (session_id, table_number, amount, method, notes, cashier_name, cashier_id, shift_id, verified) VALUES (?,?,?,?,?,?,?,?,1)",
                (sid, s["table_number"], p.get("amount", 0),
                 p.get("method", "cash"), p.get("notes", ""),
                 cashier_name, cashier_id, shift_id))

        db_exec(conn,
            "UPDATE sessions SET status='closed', closed_at=CURRENT_TIMESTAMP, total_amount=?, cashier_name=?, cashier_id=?, shift_id=? WHERE id=?",
            (server_total, cashier_name, cashier_id, shift_id, sid))
        db_exec(conn, "UPDATE tables SET status='free', current_session_id=NULL WHERE id=?", (s["table_id"],))

        # Loyalty: mijoz bo'lsa — total_spent va visits yangilash
        customer_phone = d.get("customer_phone", "") or s.get("customer_phone", "")
        customer_name_d = d.get("customer_name", "") or s.get("customer_name", "")
        if customer_phone:
            earned_points = int(server_total // 1000)
            cur_c = db_exec(conn, "SELECT * FROM customers WHERE phone=?", (customer_phone,))
            crows = rows_to_list(cur_c)
            if crows:
                db_exec(conn,
                    "UPDATE customers SET total_spent=total_spent+?, visits=visits+1, loyalty_points=loyalty_points+? WHERE phone=?",
                    (server_total, earned_points, customer_phone))
                new_points = (crows[0].get("loyalty_points") or 0) + earned_points
                auto_disc = 15 if new_points >= 500 else (10 if new_points >= 200 else (5 if new_points >= 100 else 0))
                if auto_disc > 0:
                    db_exec(conn, "UPDATE customers SET discount_pct=? WHERE phone=?", (auto_disc, customer_phone))
            else:
                db_exec(conn,
                    "INSERT INTO customers (name, phone, total_spent, visits, loyalty_points) VALUES (?,?,?,1,?)",
                    (customer_name_d, customer_phone, server_total, earned_points))

        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        log.error("close_session xato (sid=%s): %s", sid, e)
        return jsonify({"error": f"To'lov saqlanmadi: {e}"}), 500

    conn.close()
    audit("payment", "session", sid, cashier_name,
          {"total": server_total, "table": s.get("table_number"), "methods": [p.get("method") for p in payments]})
    return jsonify({"ok": True, "total": server_total})

@app.route("/api/session/<int:sid>/discount", methods=["PUT"])
def set_discount(sid):
    """Chegirma yoki xizmat haqi o'rnatish"""
    d = request.json or {}
    staff = check_staff_pin(d.get("pin")) if d.get("pin") else None
    if not check_auth() and not staff:
        return jsonify({"error": "Ruxsat yo'q"}), 403
    if staff and not has_role(staff, "cashier", "manager"):
        return jsonify({"error": "Faqat kassir yoki menejer chegirma qo'ya oladi"}), 403
    discount = float(d.get("discount", 0))
    service_charge = float(d.get("service_charge", 0))
    if not (0 <= discount <= 100) or not (0 <= service_charge <= 100):
        return jsonify({"error": "Chegirma va xizmat haqi 0–100% oralig'ida bo'lishi kerak"}), 400
    conn = get_conn()
    db_exec(conn, "UPDATE sessions SET discount=?, service_charge=? WHERE id=?",
        (discount, service_charge, sid))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


# ===== KASSIR SMENALARI =====

@app.route("/api/shift/open", methods=["POST"])
@limiter.limit("10 per minute")
def shift_open():
    """Kassir smena ochish — PIN bilan."""
    d = request.json or {}
    staff = check_staff_pin(d.get("pin"))
    if not staff:
        time.sleep(0.3)
        return jsonify({"ok": False, "error": "PIN noto'g'ri"}), 401
    if staff["role"] not in ("cashier", "manager", "admin"):
        return jsonify({"ok": False, "error": "Faqat kassir yoki menejer smena ocha oladi"}), 403
    conn = get_conn()
    cur = db_exec(conn, "SELECT * FROM shifts WHERE cashier_id=? AND status='open'", (staff["id"],))
    existing = rows_to_list(cur)
    if existing:
        conn.close()
        return jsonify({"ok": True, "shift_id": existing[0]["id"],
                        "already_open": True, "cashier": staff["name"]})
    opening_cash = int(d.get("opening_cash") or 0)
    db_exec(conn, "INSERT INTO shifts (cashier_id, cashier_name, status, opening_cash) VALUES (?,?,?,?)",
            (staff["id"], staff["name"], "open", opening_cash))
    cur2 = db_exec(conn, "SELECT id FROM shifts WHERE cashier_id=? AND status='open' ORDER BY id DESC", (staff["id"],))
    row = cur2.fetchone()
    shift_id = row[0] if USE_PG else row["id"]
    conn.commit(); conn.close()
    tg_send(f"💼 <b>Smena ochildi</b>\n👤 Kassir: {staff['name']}\n🆔 Smena #{shift_id}")
    return jsonify({"ok": True, "shift_id": shift_id, "cashier": staff["name"]})


@app.route("/api/shift/current", methods=["POST"])
@limiter.limit("30 per minute")
def shift_current():
    """Joriy ochiq smena — PIN bilan tekshirish."""
    d = request.json or {}
    staff = check_staff_pin(d.get("pin"))
    if not staff:
        time.sleep(0.3)
        return jsonify({"ok": False, "error": "PIN noto'g'ri"}), 401
    conn = get_conn()
    cur = db_exec(conn, "SELECT * FROM shifts WHERE cashier_id=? AND status='open' ORDER BY id DESC", (staff["id"],))
    shifts = rows_to_list(cur)
    conn.close()
    if not shifts:
        return jsonify({"ok": True, "shift": None, "cashier": staff["name"], "role": staff["role"],
                        "cashier_id": staff["id"]})
    return jsonify({"ok": True, "shift": shifts[0], "cashier": staff["name"], "role": staff["role"],
                    "cashier_id": staff["id"]})


@app.route("/api/shift/<int:shift_id>/close", methods=["POST"])
def shift_close(shift_id):
    """Smena yopish."""
    d = request.json or {}
    staff = check_staff_pin(d.get("pin")) if d.get("pin") else None
    if not check_auth() and not staff:
        return jsonify({"ok": False, "error": "PIN yoki admin token kerak"}), 401
    if staff and not has_role(staff, "cashier", "manager"):
        return jsonify({"ok": False, "error": "Faqat kassir smena yopa oladi"}), 403
    cashier_id = staff["id"] if staff else None
    conn = get_conn()
    if cashier_id:
        cur = db_exec(conn, "SELECT * FROM shifts WHERE id=? AND cashier_id=? AND status='open'",
                      (shift_id, cashier_id))
    else:
        cur = db_exec(conn, "SELECT * FROM shifts WHERE id=? AND status='open'", (shift_id,))
    shift_rows = rows_to_list(cur)
    if not shift_rows:
        conn.close()
        return jsonify({"ok": False, "error": "Smena topilmadi yoki allaqachon yopilgan"}), 404

    # Aktiv sessiyalar tekshiruvi
    force = d.get("force", False)
    active_cur = db_exec(conn, "SELECT COUNT(*) FROM sessions WHERE shift_id=? AND status='active'", (shift_id,))
    active_row = active_cur.fetchone()
    active_cnt = int(active_row[0] if USE_PG else (active_row[0] or 0))
    if active_cnt > 0 and not force:
        conn.close()
        return jsonify({
            "ok": False,
            "error": f"{active_cnt} ta ochiq stol bor. Barchasini yoping yoki force=true yuboring.",
            "active_sessions": active_cnt
        }), 409

    # Smena davrida qilingan to'lovlar summasi + usullar bo'yicha
    cur2 = db_exec(conn,
        "SELECT COALESCE(SUM(amount),0) AS total, COUNT(DISTINCT session_id) AS sess FROM payments WHERE shift_id=?",
        (shift_id,))
    row2 = cur2.fetchone()
    total = int(row2[0] if USE_PG else (row2["total"] or 0))
    sess_cnt = int(row2[1] if USE_PG else (row2["sess"] or 0))

    # To'lov usullari breakdown
    meth_cur = db_exec(conn,
        "SELECT method, COALESCE(SUM(amount),0) AS s FROM payments WHERE shift_id=? GROUP BY method",
        (shift_id,))
    methods = rows_to_list(meth_cur)
    methods_summary = {(r["method"] if USE_PG else r["method"]): int(r["s"] if USE_PG else r["s"]) for r in methods}

    # Chiqimlar summasi (smena ochildi vaqtidan buyon)
    shift_opened = shift_rows[0].get("opened_at") or shift_rows[0].get("created_at") or ""
    exp_cur = db_exec(conn,
        "SELECT COALESCE(SUM(amount),0) FROM expenses WHERE created_at >= ?", (shift_opened,))
    exp_row = exp_cur.fetchone()
    expenses = int(exp_row[0] if USE_PG else (exp_row[0] or 0)) if exp_row else 0
    net = total - expenses

    notes = d.get("notes", "")
    db_exec(conn,
        "UPDATE shifts SET status='closed', closed_at=CURRENT_TIMESTAMP, total_collected=?, sessions_count=?, notes=?, total_revenue=? WHERE id=?",
        (total, sess_cnt, notes, total, shift_id))
    conn.commit(); conn.close()

    cashier_name = staff["name"] if staff else shift_rows[0].get("cashier_name", "")
    meth_lines = "\n".join(f"  {k}: {v:,} so'm" for k, v in methods_summary.items())
    tg_send(f"🔒 <b>Smena yopildi</b>\n👤 Kassir: {cashier_name}\n"
            f"💰 Jami: {total:,} so'm\n📋 Chiqim: {expenses:,} so'm\n"
            f"✅ Sof: {net:,} so'm\n🧾 Sessiya: {sess_cnt} ta\n{meth_lines}")
    return jsonify({
        "ok": True,
        "total_collected": total,
        "sessions_count": sess_cnt,
        "expenses": expenses,
        "net": net,
        "by_method": methods_summary,
    })


@app.route("/api/shift/<int:shift_id>/report", methods=["POST"])
def shift_report(shift_id):
    """Smena hisoboti — to'lov usullari va sessiyalar bo'yicha."""
    d = request.json or {}
    staff = check_staff_pin(d.get("pin")) if d.get("pin") else None
    if not check_auth() and not staff:
        return jsonify({"error": "Ruxsat yo'q"}), 403
    if staff and not has_role(staff, "cashier", "manager", "accountant"):
        return jsonify({"error": "Faqat kassir, menejer yoki buxgalter hisobotni ko'ra oladi"}), 403
    conn = get_conn()
    cur = db_exec(conn, "SELECT * FROM shifts WHERE id=?", (shift_id,))
    shifts = rows_to_list(cur)
    if not shifts:
        conn.close()
        return jsonify({"error": "Smena topilmadi"}), 404
    shift = shifts[0]
    # To'lov usullari bo'yicha taqsimlash
    cur2 = db_exec(conn, "SELECT method, COALESCE(SUM(amount),0) AS total, COUNT(*) AS cnt FROM payments WHERE shift_id=? GROUP BY method", (shift_id,))
    by_method = rows_to_list(cur2)
    # Smena sessiyalari
    cur3 = db_exec(conn, """SELECT s.id, s.table_number, s.total_amount, s.opened_at, s.closed_at
        FROM sessions s
        JOIN payments p ON p.session_id = s.id
        WHERE p.shift_id=?
        GROUP BY s.id, s.table_number, s.total_amount, s.opened_at, s.closed_at
        ORDER BY s.closed_at""", (shift_id,))
    sessions_list = rows_to_list(cur3)
    conn.close()
    return jsonify({**shift, "by_method": by_method, "sessions": sessions_list})


# ===== KASSIR: VOID ITEM =====

@app.route("/api/session/<int:sid>/item/<int:iid>/void", methods=["POST"])
@limiter.limit("20 per minute")
def void_item(sid, iid):
    """Buyurtma itemini void qilish — kassir PIN yoki admin."""
    d = request.json or {}
    staff = check_staff_pin(d.get("pin")) if d.get("pin") else None
    if not check_auth() and not staff:
        return jsonify({"error": "Kassir PIN yoki admin token kerak"}), 403
    if staff and not has_role(staff, "cashier", "manager"):
        return jsonify({"error": "Faqat kassir yoki menejer void qila oladi"}), 403
    reason = d.get("reason", "Kassir tomonidan bekor qilindi")
    try:
        _validate_str(reason, 200, "Sabab")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    voider = staff["name"] if staff else "Admin"
    conn = get_conn()
    cur = db_exec(conn, "SELECT * FROM order_items WHERE id=? AND session_id=?", (iid, sid))
    rows = rows_to_list(cur)
    if not rows:
        conn.close()
        return jsonify({"error": "Item topilmadi"}), 404
    item = rows[0]
    if item["status"] == "cancelled":
        conn.close()
        return jsonify({"error": "Item allaqachon bekor qilingan"}), 400
    db_exec(conn, """UPDATE order_items SET status='cancelled', void_by=?, void_reason=?,
        voided_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=? AND session_id=?""",
        (voider, reason, iid, sid))
    # Cooking bosqichida bo'lgan bo'lsa — inventarni qaytarish
    if item.get("status") in ("cooking", "ready", "served"):
        try:
            restore_inventory(item.get("menu_item_id"), item.get("quantity", 1), conn,
                              f"Void: {item.get('item_name')} — {reason}")
        except Exception as e:
            log.warning("restore_inventory xato: %s", e)
    # Sessiya summasini qayta hisoblash
    cur2 = db_exec(conn, "SELECT COALESCE(SUM(total_price),0) FROM order_items WHERE session_id=? AND status!='cancelled'", (sid,))
    row2 = cur2.fetchone()
    new_total = int(row2[0] if USE_PG else (row2[0] or 0))
    db_exec(conn, "UPDATE sessions SET total_amount=? WHERE id=?", (new_total, sid))
    conn.commit(); conn.close()
    audit("void", "order_item", iid, voider,
          {"item": item.get("item_name"), "reason": reason, "session_id": sid})
    tg_send(f"🚫 <b>VOID</b> — Stol #{item.get('table_number')}\n"
            f"❌ {item.get('item_name')} x{item.get('quantity')}\n"
            f"📝 Sabab: {reason}\n👤 {voider}")
    return jsonify({"ok": True, "new_total": new_total})


# ===== CHEK (RECEIPT) =====

@app.route("/api/receipt/<int:sid>", methods=["GET"])
def get_receipt(sid):
    """Sessiya cheki — kassir PIN yoki session token yoki admin."""
    token = request.headers.get("X-Session-Token", "")
    # PIN header orqali qabul qilinadi (URL loglarida ko'rinmasin)
    pin   = request.headers.get("X-Staff-Pin", "") or request.args.get("pin", "")
    conn  = get_conn()
    cur   = db_exec(conn, "SELECT * FROM sessions WHERE id=?", (sid,))
    sessions = rows_to_list(cur)
    if not sessions:
        conn.close()
        return jsonify({"error": "Sessiya topilmadi"}), 404
    s = sessions[0]
    staff = check_staff_pin(pin, conn) if pin else None
    if s["token"] != token and not check_auth() and not staff:
        conn.close()
        return jsonify({"error": "Ruxsat yo'q"}), 403
    cur2 = db_exec(conn, "SELECT * FROM order_items WHERE session_id=? AND status!='cancelled' ORDER BY created_at", (sid,))
    items = rows_to_list(cur2)
    cur3 = db_exec(conn, "SELECT * FROM payments WHERE session_id=? ORDER BY created_at", (sid,))
    payments_list = rows_to_list(cur3)
    cur4 = db_exec(conn, "SELECT key, value FROM settings WHERE key IN ('restaurant_name','phone','address','working_hours')")
    raw4 = cur4.fetchall()
    rest_info = {}
    for r in raw4:
        rest_info[r[0] if USE_PG else r["key"]] = r[1] if USE_PG else r["value"]
    conn.close()
    subtotal   = sum(i["total_price"] for i in items)
    sc_amount  = int(subtotal * float(s.get("service_charge") or 0) / 100)
    disc_amount = int(subtotal * float(s.get("discount") or 0) / 100)
    grand_total = subtotal + sc_amount - disc_amount
    return jsonify({
        "session": s, "items": items, "payments": payments_list,
        "subtotal": subtotal, "sc_amount": sc_amount,
        "disc_amount": disc_amount, "grand_total": grand_total,
        "restaurant": rest_info,
    })


# ===== OSHXONA (KDS) =====
@app.route("/api/kitchen", methods=["GET"])
def kitchen_orders():
    """Oshxona ekrani uchun — faqat pending va cooking itemlar"""
    if not check_kitchen_auth():
        return jsonify({"error": "Ruxsat yo'q. Kitchen token kerak."}), 403
    conn = get_conn()
    category = request.args.get("category")
    if category:
        cur = db_exec(conn, """SELECT oi.*, s.table_number
            FROM order_items oi JOIN sessions s ON oi.session_id=s.id
            WHERE oi.status IN ('pending','cooking') AND oi.category=?
            ORDER BY oi.course, oi.created_at""", (category,))
    else:
        cur = db_exec(conn, """SELECT oi.*, s.table_number as tnum
            FROM order_items oi JOIN sessions s ON oi.session_id=s.id
            WHERE oi.status IN ('pending','cooking')
            ORDER BY oi.course, oi.created_at""")
    items = rows_to_list(cur)
    conn.close()
    # Stol bo'yicha guruhlash
    grouped = {}
    for item in items:
        tbl = str(item.get("table_number") or item.get("tnum") or "?")
        if tbl not in grouped:
            grouped[tbl] = {"table": tbl, "session_id": item["session_id"], "items": []}
        grouped[tbl]["items"].append(item)
    return jsonify(list(grouped.values()))

@app.route("/api/kitchen/ready", methods=["GET"])
def kitchen_ready():
    """Tayyor bo'lgan buyurtmalar — ofitsiant olishi kerak"""
    if not check_kitchen_auth():
        return jsonify({"error": "Ruxsat yo'q. Kitchen token kerak."}), 403
    conn = get_conn()
    cur  = db_exec(conn, """SELECT oi.* FROM order_items oi
        WHERE oi.status='ready' ORDER BY oi.updated_at""")
    items = rows_to_list(cur)
    conn.close()
    return jsonify(items)


# ===== XODIMLAR =====
@app.route("/api/staff", methods=["GET"])
def get_staff():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    cur  = db_exec(conn, "SELECT id,name,role,phone,salary_type,salary_amount,active FROM staff ORDER BY name")
    result = rows_to_list(cur)
    conn.close()
    return jsonify(result)

@app.route("/api/staff", methods=["POST"])
def add_staff():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    try:
        _validate_str(d.get("name"), 100, "Ism")
        _validate_str(d.get("phone"), 20, "Telefon")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    pin = str(d.get("pin", "0000"))
    if len(pin) < 4:
        return jsonify({"error": "PIN kamida 4 raqam bo'lishi kerak"}), 400
    pin_hash, pin_salt = hash_password(pin)
    conn = get_conn()
    db_exec(conn, "INSERT INTO staff (name,role,pin,pin_salt,phone,salary_type,salary_amount) VALUES (?,?,?,?,?,?,?)",
        (d.get("name"), d.get("role"), pin_hash, pin_salt,
         d.get("phone"), d.get("salary_type","monthly"), d.get("salary_amount",0)))
    conn.commit(); conn.close()
    audit("staff_add", "staff", user_name="admin", details={"name": d.get("name"), "role": d.get("role")})
    return jsonify({"ok": True})

@app.route("/api/staff/<int:sid>", methods=["PUT"])
def update_staff(sid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    if d.get("pin"):
        pin = str(d["pin"])
        if len(pin) < 4:
            conn.close()
            return jsonify({"error": "PIN kamida 4 raqam bo'lishi kerak"}), 400
        pin_hash, pin_salt = hash_password(pin)
        db_exec(conn, "UPDATE staff SET name=?,role=?,pin=?,pin_salt=?,phone=?,salary_type=?,salary_amount=?,active=? WHERE id=?",
            (d.get("name"),d.get("role"),pin_hash,pin_salt,
             d.get("phone"),d.get("salary_type"),d.get("salary_amount"),d.get("active",1),sid))
    else:
        db_exec(conn, "UPDATE staff SET name=?,role=?,phone=?,salary_type=?,salary_amount=?,active=? WHERE id=?",
            (d.get("name"),d.get("role"),d.get("phone"),
             d.get("salary_type"),d.get("salary_amount"),d.get("active",1),sid))
    conn.commit(); conn.close()
    audit("staff_update", "staff", sid, "admin", {"name": d.get("name"), "role": d.get("role")})
    return jsonify({"ok": True})

@app.route("/api/staff/<int:sid>", methods=["DELETE"])
def delete_staff(sid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    db_exec(conn, "UPDATE staff SET active=0 WHERE id=?", (sid,))
    conn.commit(); conn.close()
    audit("staff_delete", "staff", sid, "admin")
    return jsonify({"ok": True})

@app.route("/api/staff/checkin", methods=["POST"])
@limiter.limit("10 per minute")
def staff_checkin():
    """PIN bilan kirish/chiqish (yangi pbkdf2 + eski sha256 moslashuv)."""
    d = request.json or {}
    pin = str(d.get("pin", ""))
    if not pin:
        return jsonify({"ok": False, "error": "PIN kiritilmadi"}), 400

    conn = get_conn()
    # check_staff_pin barcha aktiv xodimlarni tekshiradi (timing-safe)
    staff = check_staff_pin(pin, conn)
    if not staff:
        conn.close()
        return jsonify({"ok": False, "error": "PIN noto'g'ri"}), 401
    import datetime
    today = datetime.date.today().isoformat()
    # Bugun allaqachon kirganmi?
    cur2 = db_exec(conn, "SELECT * FROM attendance WHERE staff_id=? AND date=? AND check_out IS NULL", (staff["id"], today))
    existing = rows_to_list(cur2)
    if existing:
        # Check-out
        att = existing[0]
        check_in = att["check_in"]
        if isinstance(check_in, str):
            check_in = datetime.datetime.fromisoformat(check_in)
        hours = (datetime.datetime.utcnow() - check_in.replace(tzinfo=None)).total_seconds() / 3600
        db_exec(conn, "UPDATE attendance SET check_out=CURRENT_TIMESTAMP, hours_worked=? WHERE id=?",
            (round(hours,2), att["id"]))
        conn.commit(); conn.close()
        return jsonify({"ok": True, "action": "checkout", "name": staff["name"], "hours": round(hours,2)})
    else:
        # Check-in
        db_exec(conn, "INSERT INTO attendance (staff_id, staff_name, check_in, date) VALUES (?,?,CURRENT_TIMESTAMP,?)",
            (staff["id"], staff["name"], today))
        conn.commit(); conn.close()
        return jsonify({"ok": True, "action": "checkin", "name": staff["name"], "role": staff["role"]})

@app.route("/api/attendance", methods=["GET"])
def get_attendance():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    limit  = min(int(request.args.get("limit",  100)), 500)
    offset = max(int(request.args.get("offset", 0)),   0)
    date   = request.args.get("date")
    conn   = get_conn()
    if date:
        cur = db_exec(conn,
            "SELECT * FROM attendance WHERE date=? ORDER BY check_in DESC LIMIT ? OFFSET ?",
            (date, limit, offset))
    else:
        cur = db_exec(conn,
            "SELECT * FROM attendance ORDER BY check_in DESC LIMIT ? OFFSET ?",
            (limit, offset))
    result = rows_to_list(cur)
    conn.close()
    return jsonify({"data": result, "limit": limit, "offset": offset, "count": len(result)})


# ===== GALEREYA =====
@app.route("/api/gallery", methods=["GET"])
def get_gallery():
    conn = get_conn()
    active = request.args.get("active")
    if active == "1":
        cur = db_exec(conn, "SELECT * FROM gallery WHERE active=1 ORDER BY sort_order, id")
    else:
        cur = db_exec(conn, "SELECT * FROM gallery ORDER BY sort_order, id")
    result = rows_to_list(cur)
    conn.close()
    return jsonify(result)

@app.route("/api/gallery", methods=["POST"])
def add_gallery():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    try:
        _validate_str(d.get("title"), 200, "Sarlavha")
        _validate_str(d.get("emoji"),  10, "Emoji")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    conn = get_conn()
    db_exec(conn, "INSERT INTO gallery (title, emoji, image, sort_order, active) VALUES (?,?,?,?,?)",
        (d.get("title"), d.get("emoji","🖼"), d.get("image"), d.get("sort_order",0), d.get("active",1)))
    conn.commit(); conn.close()
    return jsonify({"ok": True})

@app.route("/api/gallery/<int:gid>", methods=["PUT"])
def update_gallery(gid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    db_exec(conn, "UPDATE gallery SET title=?, emoji=?, image=?, sort_order=?, active=? WHERE id=?",
        (d.get("title"), d.get("emoji","🖼"), d.get("image"), d.get("sort_order",0), d.get("active",1), gid))
    conn.commit(); conn.close()
    return jsonify({"ok": True})

@app.route("/api/gallery/<int:gid>", methods=["DELETE"])
def delete_gallery(gid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    db_exec(conn, "DELETE FROM gallery WHERE id=?", (gid,))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


# ===== AKSIYALAR =====
@app.route("/api/promotions", methods=["GET"])
def get_promotions():
    conn = get_conn()
    active = request.args.get("active")
    if active == "1":
        cur = db_exec(conn, "SELECT * FROM promotions WHERE active=1 ORDER BY sort_order, id")
    else:
        cur = db_exec(conn, "SELECT * FROM promotions ORDER BY sort_order, id")
    result = rows_to_list(cur)
    conn.close()
    return jsonify(result)

@app.route("/api/promotions", methods=["POST"])
def add_promotion():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    try:
        _validate_str(d.get("title"),       200,  "Sarlavha")
        _validate_str(d.get("description"), 1000, "Tavsif")
        _validate_str(d.get("badge"),        20,  "Badge")
        _validate_str(d.get("time_info"),   100,  "Vaqt ma'lumoti")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    conn = get_conn()
    db_exec(conn, "INSERT INTO promotions (title, description, badge, emoji, time_info, sort_order, active) VALUES (?,?,?,?,?,?,?)",
        (d.get("title"), d.get("description"), d.get("badge"), d.get("emoji","🎁"), d.get("time_info"), d.get("sort_order",0), d.get("active",1)))
    conn.commit(); conn.close()
    return jsonify({"ok": True})

@app.route("/api/promotions/<int:pid>", methods=["PUT"])
def update_promotion(pid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    db_exec(conn, "UPDATE promotions SET title=?, description=?, badge=?, emoji=?, time_info=?, sort_order=?, active=? WHERE id=?",
        (d.get("title"), d.get("description"), d.get("badge"), d.get("emoji","🎁"), d.get("time_info"), d.get("sort_order",0), d.get("active",1), pid))
    conn.commit(); conn.close()
    return jsonify({"ok": True})

@app.route("/api/promotions/<int:pid>", methods=["DELETE"])
def delete_promotion(pid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    db_exec(conn, "DELETE FROM promotions WHERE id=?", (pid,))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


# ===== MAOSH HISOBLASH =====
@app.route("/api/staff/payroll", methods=["GET"])
def staff_payroll():
    """Xodimlar maosh hisoboti: davomat soatlari × stavka yoki oylik."""
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    month = request.args.get("month", datetime.datetime.utcnow().strftime("%Y-%m"))
    conn  = get_conn()
    cur   = db_exec(conn, "SELECT * FROM staff WHERE active=1 ORDER BY name")
    staff_list = rows_to_list(cur)
    result = []
    for s in staff_list:
        sid = s["id"]
        # Davomat soatlari
        if USE_PG:
            att_cur = db_exec(conn,
                "SELECT COALESCE(SUM(hours_worked),0) FROM attendance WHERE staff_id=%s AND to_char(date::date,'YYYY-MM')=%s",
                (sid, month))
        else:
            att_cur = db_exec(conn,
                "SELECT COALESCE(SUM(hours_worked),0) FROM attendance WHERE staff_id=? AND strftime('%Y-%m',date)=?",
                (sid, month))
        hours = float(att_cur.fetchone()[0] or 0)
        salary_type   = s.get("salary_type", "monthly")
        salary_amount = float(s.get("salary_amount") or 0)
        if salary_type == "hourly":
            earned = round(hours * salary_amount)
        elif salary_type == "percent":
            # Bu oyda sessiyalardan tushum × foiz
            if USE_PG:
                rev_cur = db_exec(conn,
                    "SELECT COALESCE(SUM(total_amount),0) FROM sessions WHERE waiter_id=%s AND status='closed' AND to_char(closed_at,'YYYY-MM')=%s",
                    (sid, month))
            else:
                rev_cur = db_exec(conn,
                    "SELECT COALESCE(SUM(total_amount),0) FROM sessions WHERE waiter_id=? AND status='closed' AND strftime('%Y-%m',closed_at)=?",
                    (sid, month))
            revenue = float(rev_cur.fetchone()[0] or 0)
            earned  = round(revenue * salary_amount / 100)
        else:
            earned = round(salary_amount)
        result.append({
            "id": sid, "name": s["name"], "role": s["role"],
            "salary_type": salary_type, "salary_amount": salary_amount,
            "hours_worked": hours, "earned": earned, "month": month,
        })
    conn.close()
    return jsonify(result)


# ===== BUXGALTERIYA: HISOBOTLAR =====
@app.route("/api/accounting/report", methods=["GET"])
def accounting_report():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    # V4: SQL injection — whitelist tekshiruvi
    period = request.args.get("period", "daily")
    if period not in ALLOWED_PERIODS:
        period = "daily"
    conn   = get_conn()

    if USE_PG:
        if period == "daily":
            date_filter = "date_trunc('day', created_at) = CURRENT_DATE"
            exp_filter  = "date = CURRENT_DATE::text"
        elif period == "weekly":
            date_filter = "created_at >= date_trunc('week', CURRENT_DATE)"
            exp_filter  = "date >= date_trunc('week', CURRENT_DATE)::text"
        else:
            date_filter = "date_trunc('month', created_at) = date_trunc('month', CURRENT_DATE)"
            exp_filter  = "to_char(created_at,'YYYY-MM') = to_char(CURRENT_DATE,'YYYY-MM')"
    else:
        if period == "daily":
            date_filter = "date(created_at,'localtime') = date('now','localtime')"
            exp_filter  = "date = date('now','localtime')"
        elif period == "weekly":
            date_filter = "date(created_at,'localtime') >= date('now','localtime','-6 days')"
            exp_filter  = "date >= date('now','localtime','-6 days')"
        else:
            date_filter = "strftime('%Y-%m', created_at) = strftime('%Y-%m', 'now', 'localtime')"
            exp_filter  = "strftime('%Y-%m', date) = strftime('%Y-%m', 'now', 'localtime')"

    def val(sql):
        cur = conn.cursor()
        cur.execute(sql)
        row = cur.fetchone()
        return row[0] if row else 0

    revenue   = val(f"SELECT COALESCE(SUM(amount),0) FROM payments WHERE {date_filter}")
    orders_ct = val(f"SELECT COUNT(DISTINCT session_id) FROM payments WHERE {date_filter}")
    expenses  = val(f"SELECT COALESCE(SUM(amount),0) FROM expenses WHERE {exp_filter}")

    # Kunlik daromad grafigi (oxirgi 7 kun)
    if USE_PG:
        chart_sql = """
            SELECT date_trunc('day', created_at)::date::text AS day,
                   COALESCE(SUM(amount),0) AS rev
            FROM payments
              WHERE created_at >= CURRENT_DATE - INTERVAL '6 days'
            GROUP BY 1 ORDER BY 1
        """
    else:
        chart_sql = """
            SELECT date(created_at,'localtime') AS day,
                   COALESCE(SUM(amount),0) AS rev
            FROM payments
              WHERE date(created_at,'localtime') >= date('now','localtime','-6 days')
            GROUP BY 1 ORDER BY 1
        """
    cur2 = conn.cursor()
    cur2.execute(chart_sql)
    if USE_PG:
        chart = [{"day": r[0], "rev": r[1]} for r in cur2.fetchall()]
    else:
        chart = [{"day": r[0], "rev": r[1]} for r in cur2.fetchall()]

    # Kategoriya bo'yicha chiqimlar
    cur3 = conn.cursor()
    cur3.execute(f"SELECT category, COALESCE(SUM(amount),0) AS total FROM expenses WHERE {exp_filter} GROUP BY category ORDER BY total DESC")
    if USE_PG:
        exp_by_cat = [{"cat": r[0], "total": r[1]} for r in cur3.fetchall()]
    else:
        exp_by_cat = [{"cat": r[0], "total": r[1]} for r in cur3.fetchall()]

    conn.close()
    return jsonify({
        "revenue": revenue,
        "expenses": expenses,
        "profit": revenue - expenses,
        "orders": orders_ct,
        "chart": chart,
        "expenses_by_cat": exp_by_cat,
    })


@app.route("/api/expenses", methods=["GET"])
def get_expenses():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    limit     = min(int(request.args.get("limit",  200)), 1000)
    offset    = max(int(request.args.get("offset", 0)),   0)
    date_from = request.args.get("from")
    date_to   = request.args.get("to")
    conn = get_conn()
    if date_from and date_to:
        cur = db_exec(conn,
            "SELECT * FROM expenses WHERE date>=? AND date<=? ORDER BY date DESC, id DESC LIMIT ? OFFSET ?",
            (date_from, date_to, limit, offset))
    else:
        cur = db_exec(conn,
            "SELECT * FROM expenses ORDER BY date DESC, id DESC LIMIT ? OFFSET ?",
            (limit, offset))
    result = rows_to_list(cur)
    conn.close()
    return jsonify({"data": result, "limit": limit, "offset": offset, "count": len(result)})


@app.route("/api/expenses", methods=["POST"])
def add_expense():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    try:
        _validate_str(d.get("category"),    50,  "Kategoriya")
        _validate_str(d.get("description"), 500, "Tavsif")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    conn = get_conn()
    db_exec(conn,
        "INSERT INTO expenses (category, description, amount, date) VALUES (?,?,?,?)",
        (d.get("category"), d.get("description"), d.get("amount", 0), d.get("date"))
    )
    conn.commit(); conn.close()
    audit("expense_add", "expense", user_name="admin",
          details={"category": d.get("category"), "amount": d.get("amount"), "date": d.get("date")})
    return jsonify({"ok": True})


@app.route("/api/expenses/<int:eid>", methods=["DELETE"])
def delete_expense(eid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    db_exec(conn, "DELETE FROM expenses WHERE id=?", (eid,))
    conn.commit(); conn.close()
    audit("expense_delete", "expense", eid, "admin")
    return jsonify({"ok": True})


# ===== OMBOR =====
@app.route("/api/inventory", methods=["GET"])
def get_inventory():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    limit  = min(int(request.args.get("limit",  500)), 2000)
    offset = max(int(request.args.get("offset", 0)),   0)
    search = request.args.get("q", "").strip()
    conn   = get_conn()
    if search:
        cur = db_exec(conn,
            "SELECT * FROM inventory WHERE name LIKE ? ORDER BY name LIMIT ? OFFSET ?",
            (f"%{search}%", limit, offset))
    else:
        cur = db_exec(conn,
            "SELECT * FROM inventory ORDER BY name LIMIT ? OFFSET ?",
            (limit, offset))
    result = rows_to_list(cur)
    conn.close()
    return jsonify({"data": result, "limit": limit, "offset": offset, "count": len(result)})


@app.route("/api/inventory", methods=["POST"])
def add_inventory():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    db_exec(conn,
        "INSERT INTO inventory (name, unit, quantity, min_quantity, price_per_unit) VALUES (?,?,?,?,?)",
        (d.get("name"), d.get("unit","kg"), d.get("quantity",0), d.get("min_quantity",0), d.get("price_per_unit",0))
    )
    conn.commit(); conn.close()
    return jsonify({"ok": True})


@app.route("/api/inventory/<int:iid>", methods=["PUT"])
def update_inventory(iid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d    = request.json or {}
    conn = get_conn()
    # Miqdor o'zgartirish va log yozish
    cur  = db_exec(conn, "SELECT name, quantity FROM inventory WHERE id=?", (iid,))
    row  = cur.fetchone()
    if row:
        old_name = row["name"] if not USE_PG else row[0]
        old_qty  = row["quantity"] if not USE_PG else row[1]
        new_qty  = d.get("quantity", old_qty)
        diff     = new_qty - old_qty
        move_type = "kirim" if diff > 0 else "chiqim"
        if diff != 0:
            db_exec(conn,
                "INSERT INTO inventory_log (item_id, item_name, type, quantity, note) VALUES (?,?,?,?,?)",
                (iid, old_name, move_type, abs(diff), d.get("note", ""))
            )
    db_exec(conn,
        "UPDATE inventory SET name=?, unit=?, quantity=?, min_quantity=?, price_per_unit=? WHERE id=?",
        (d.get("name"), d.get("unit","kg"), d.get("quantity",0), d.get("min_quantity",0), d.get("price_per_unit",0), iid)
    )
    conn.commit(); conn.close()
    return jsonify({"ok": True})


@app.route("/api/inventory/<int:iid>", methods=["DELETE"])
def delete_inventory(iid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    db_exec(conn, "DELETE FROM inventory WHERE id=?", (iid,))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


@app.route("/api/inventory/log", methods=["GET"])
def get_inventory_log():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    limit  = min(int(request.args.get("limit",  100)), 500)
    offset = max(int(request.args.get("offset", 0)),   0)
    conn   = get_conn()
    cur    = db_exec(conn,
        "SELECT * FROM inventory_log ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (limit, offset))
    result = rows_to_list(cur)
    conn.close()
    return jsonify({"data": result, "limit": limit, "offset": offset, "count": len(result)})


# ===== RETSEPTLAR =====
@app.route("/api/recipes", methods=["GET"])
def get_recipes():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    menu_item_id = request.args.get("menu_item_id")
    conn = get_conn()
    if menu_item_id:
        cur = db_exec(conn, """
            SELECT r.*, i.name AS inv_name, i.unit AS inv_unit, i.quantity AS inv_qty
            FROM recipes r
            JOIN inventory i ON r.inventory_id = i.id
            WHERE r.menu_item_id=?
        """, (menu_item_id,))
    else:
        cur = db_exec(conn, """
            SELECT r.*, i.name AS inv_name, i.unit AS inv_unit, i.quantity AS inv_qty,
                   m.name AS menu_name
            FROM recipes r
            JOIN inventory i ON r.inventory_id = i.id
            JOIN menu m ON r.menu_item_id = m.id
            ORDER BY m.name
        """)
    result = rows_to_list(cur)
    conn.close()
    return jsonify(result)


@app.route("/api/recipes", methods=["POST"])
def add_recipe():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    # Eski o'chirib yangi kiritish (upsert)
    db_exec(conn, "DELETE FROM recipes WHERE menu_item_id=? AND inventory_id=?",
            (d.get("menu_item_id"), d.get("inventory_id")))
    db_exec(conn,
        "INSERT INTO recipes (menu_item_id, inventory_id, quantity, unit) VALUES (?,?,?,?)",
        (d.get("menu_item_id"), d.get("inventory_id"), d.get("quantity", 0), d.get("unit", "g"))
    )
    conn.commit(); conn.close()
    return jsonify({"ok": True})


@app.route("/api/recipes/<int:rid>", methods=["DELETE"])
def delete_recipe(rid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    db_exec(conn, "DELETE FROM recipes WHERE id=?", (rid,))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


def _inv_update(conn, needed, inv_id, unit_cond=""):
    """MAX(0, qty-?) — SQLite: CASE WHEN, PG: GREATEST()"""
    where = f"id=? {unit_cond}".strip()
    if USE_PG:
        sql = f"UPDATE inventory SET quantity = GREATEST(0, quantity - ?) WHERE {where}"
        db_exec(conn, sql, (needed, inv_id))
    else:
        sql = f"UPDATE inventory SET quantity = CASE WHEN quantity - ? < 0 THEN 0 ELSE quantity - ? END WHERE {where}"
        db_exec(conn, sql, (needed, needed, inv_id))


def deduct_inventory(menu_item_id, quantity, conn, note=""):
    """Retsept bo'yicha ombordan avtomatik hisobdan chiqarish"""
    cur = db_exec(conn, "SELECT * FROM recipes WHERE menu_item_id=?", (menu_item_id,))
    recipes = rows_to_list(cur)
    for r in recipes:
        needed = r["quantity"] * quantity
        inv_id = r["inventory_id"]
        if r["unit"] == "g":
            _inv_update(conn, needed / 1000.0, inv_id, "AND unit='kg'")
            _inv_update(conn, needed,           inv_id, "AND unit='g'")
        elif r["unit"] == "ml":
            _inv_update(conn, needed / 1000.0, inv_id, "AND unit='l'")
            _inv_update(conn, needed,           inv_id, "AND unit='ml'")
        else:
            _inv_update(conn, needed, inv_id)
        inv_cur = db_exec(conn, "SELECT name FROM inventory WHERE id=?", (r["inventory_id"],))
        inv_row = inv_cur.fetchone()
        inv_name = inv_row[0] if USE_PG else (inv_row["name"] if inv_row else "?")
        db_exec(conn,
            "INSERT INTO inventory_log (item_id, item_name, type, quantity, note) VALUES (?,?,?,?,?)",
            (r["inventory_id"], inv_name, "expense", needed, note or "Auto chiqim"))


def restore_inventory(menu_item_id, quantity, conn, note=""):
    """Void/cancel bo'lganda inventarni qaytarish (deduct_inventory teskarisi)"""
    cur = db_exec(conn, "SELECT * FROM recipes WHERE menu_item_id=?", (menu_item_id,))
    recipes = rows_to_list(cur)
    for r in recipes:
        needed = r["quantity"] * quantity
        inv_id = r["inventory_id"]
        if r["unit"] == "g":
            db_exec(conn, "UPDATE inventory SET quantity=quantity+? WHERE id=? AND unit='kg'", (needed/1000.0, inv_id))
            db_exec(conn, "UPDATE inventory SET quantity=quantity+? WHERE id=? AND unit='g'",  (needed, inv_id))
        elif r["unit"] == "ml":
            db_exec(conn, "UPDATE inventory SET quantity=quantity+? WHERE id=? AND unit='l'",  (needed/1000.0, inv_id))
            db_exec(conn, "UPDATE inventory SET quantity=quantity+? WHERE id=? AND unit='ml'", (needed, inv_id))
        else:
            db_exec(conn, "UPDATE inventory SET quantity=quantity+? WHERE id=?", (needed, inv_id))
        inv_cur = db_exec(conn, "SELECT name FROM inventory WHERE id=?", (inv_id,))
        inv_row = inv_cur.fetchone()
        inv_name = inv_row[0] if USE_PG else (inv_row["name"] if inv_row else "?")
        db_exec(conn,
            "INSERT INTO inventory_log (item_id, item_name, type, quantity, note) VALUES (?,?,?,?,?)",
            (inv_id, inv_name, "kirim", needed, note or "Void/bekor — qaytarildi"))


# ===== SMENALAR RO'YXATI =====
@app.route("/api/shifts", methods=["GET"])
def get_shifts():
    """Barcha smenalar ro'yxati — admin uchun."""
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    limit_n = min(int(request.args.get("limit", 100)), 500)
    status  = request.args.get("status", "")
    if status:
        cur = db_exec(conn,
            "SELECT * FROM shifts WHERE status=? ORDER BY opened_at DESC LIMIT ?",
            (status, limit_n))
    else:
        cur = db_exec(conn,
            "SELECT * FROM shifts ORDER BY opened_at DESC LIMIT ?",
            (limit_n,))
    result = rows_to_list(cur)
    conn.close()
    return jsonify(result)


# ===== ANALYTICS ALIAS =====
@app.route("/api/analytics", methods=["GET"])
def analytics_alias():
    """/api/analytics/summary ga qisqartma — orqaga moslik uchun."""
    return analytics_summary()


# ===== STOP-LIST =====
@app.route("/api/menu/<int:item_id>/stoplist", methods=["PUT"])
def toggle_stoplist(item_id):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    db_exec(conn, "UPDATE menu SET available=? WHERE id=?",
            (0 if d.get("stop") else 1, item_id))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


# ===== KENGAYTIRILGAN HISOBOTLAR =====
@app.route("/api/analytics/summary", methods=["GET"])
def analytics_summary():
    """Sessiyalar asosida to'liq hisobot"""
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    # V4: SQL injection — whitelist tekshiruvi
    period = request.args.get("period", "daily")
    if period not in ALLOWED_PERIODS:
        period = "daily"
    conn   = get_conn()

    if USE_PG:
        if period == "daily":
            df = "date_trunc('day', closed_at) = CURRENT_DATE"
            df2 = "date_trunc('day', created_at) = CURRENT_DATE"
            df3 = "date = CURRENT_DATE::text"
        elif period == "weekly":
            df = "closed_at >= date_trunc('week', CURRENT_DATE)"
            df2 = "created_at >= date_trunc('week', CURRENT_DATE)"
            df3 = "date >= date_trunc('week', CURRENT_DATE)::text"
        else:
            df = "date_trunc('month', closed_at) = date_trunc('month', CURRENT_DATE)"
            df2 = "date_trunc('month', created_at) = date_trunc('month', CURRENT_DATE)"
            df3 = "to_char(date::date,'YYYY-MM') = to_char(CURRENT_DATE,'YYYY-MM')"
        chart_sql = f"""
            SELECT date_trunc('day', closed_at)::date::text AS day, COALESCE(SUM(total_amount),0) AS rev
            FROM sessions WHERE status='closed' AND {df}
            GROUP BY 1 ORDER BY 1
        """
        top_sql = f"""
            SELECT item_name, item_emoji, SUM(quantity) AS cnt, SUM(total_price) AS rev
            FROM order_items WHERE status!='cancelled' AND {df2}
            GROUP BY item_name, item_emoji ORDER BY cnt DESC LIMIT 10
        """
        staff_sql = f"""
            SELECT waiter_name, COUNT(DISTINCT session_id) AS sessions, SUM(total_price) AS rev
            FROM order_items WHERE waiter_name IS NOT NULL AND waiter_name!='' AND {df2}
            GROUP BY waiter_name ORDER BY rev DESC
        """
    else:
        if period == "daily":
            df = "date(closed_at,'localtime') = date('now','localtime')"
            df2 = "date(created_at,'localtime') = date('now','localtime')"
            df3 = "date = date('now','localtime')"
        elif period == "weekly":
            df = "date(closed_at,'localtime') >= date('now','localtime','-6 days')"
            df2 = "date(created_at,'localtime') >= date('now','localtime','-6 days')"
            df3 = "date >= date('now','localtime','-6 days')"
        else:
            df = "strftime('%Y-%m',closed_at) = strftime('%Y-%m','now','localtime')"
            df2 = "strftime('%Y-%m',created_at) = strftime('%Y-%m','now','localtime')"
            df3 = "strftime('%Y-%m',date) = strftime('%Y-%m','now','localtime')"
        chart_sql = f"""
            SELECT date(closed_at,'localtime') AS day, COALESCE(SUM(total_amount),0) AS rev
            FROM sessions WHERE status='closed' AND {df}
            GROUP BY 1 ORDER BY 1
        """
        top_sql = f"""
            SELECT item_name, item_emoji, SUM(quantity) AS cnt, SUM(total_price) AS rev
            FROM order_items WHERE status!='cancelled' AND {df2}
            GROUP BY item_name, item_emoji ORDER BY cnt DESC LIMIT 10
        """
        staff_sql = f"""
            SELECT waiter_name, COUNT(DISTINCT session_id) AS sessions, SUM(total_price) AS rev
            FROM order_items WHERE waiter_name IS NOT NULL AND waiter_name!='' AND {df2}
            GROUP BY waiter_name ORDER BY rev DESC
        """

    def val(sql):
        c = conn.cursor(); c.execute(sql); r = c.fetchone(); return r[0] if r and r[0] else 0

    revenue     = val(f"SELECT COALESCE(SUM(total_amount),0) FROM sessions WHERE status='closed' AND {df}")
    sessions_ct = val(f"SELECT COUNT(*) FROM sessions WHERE status='closed' AND {df}")
    items_ct    = val(f"SELECT COALESCE(SUM(quantity),0) FROM order_items WHERE status!='cancelled' AND {df2}")
    expenses    = val(f"SELECT COALESCE(SUM(amount),0) FROM expenses WHERE {df3}")
    avg_bill    = (revenue / sessions_ct) if sessions_ct else 0

    # Payment usullari
    pay_cur = conn.cursor()
    pay_cur.execute(f"SELECT method, COALESCE(SUM(amount),0) FROM payments WHERE {df2.replace('created_at','created_at')} GROUP BY method")
    pay_by_method = [{"method": r[0], "total": r[1]} for r in pay_cur.fetchall()]

    # Grafik
    c2 = conn.cursor(); c2.execute(chart_sql)
    chart = [{"day": r[0], "rev": r[1]} for r in c2.fetchall()]

    # Top taomlar
    c3 = conn.cursor(); c3.execute(top_sql)
    top_items = [{"name": r[0], "emoji": r[1], "count": r[2], "revenue": r[3]} for r in c3.fetchall()]

    # Ofitsiantlar samaradorligi
    c4 = conn.cursor(); c4.execute(staff_sql)
    staff_perf = [{"name": r[0], "sessions": r[1], "revenue": r[2]} for r in c4.fetchall()]

    # Ombor kam qolganlar
    c5 = conn.cursor(); c5.execute("SELECT name, quantity, min_quantity, unit FROM inventory WHERE quantity <= min_quantity ORDER BY quantity")
    low_stock = [{"name": r[0], "quantity": r[1], "min_quantity": r[2], "unit": r[3]} for r in c5.fetchall()]

    conn.close()
    return jsonify({
        "revenue": revenue, "expenses": expenses, "profit": revenue - expenses,
        "sessions": sessions_ct, "items_sold": items_ct, "avg_bill": round(avg_bill),
        "chart": chart, "top_items": top_items, "staff_perf": staff_perf,
        "low_stock": low_stock, "pay_by_method": pay_by_method
    })


@app.route("/api/payments", methods=["GET"])
def get_payments():
    # Kassir PIN yoki admin token bilan ruxsat
    pin = request.headers.get("X-Staff-Pin", "") or request.args.get("pin", "")
    staff = check_staff_pin(pin) if pin else None
    if not check_auth() and not staff:
        return jsonify({"error": "Ruxsat yo'q"}), 403
    if staff and not has_role(staff, "cashier", "manager", "accountant"):
        return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    date = request.args.get("date")
    shift_id = request.args.get("shift_id")
    try:
        limit_n = min(int(request.args.get("limit", 100)), 500)
    except (ValueError, TypeError):
        limit_n = 100

    sql = "SELECT p.*, s.table_number as tbl FROM payments p LEFT JOIN sessions s ON p.session_id=s.id WHERE 1=1"
    params = []
    if date:
        sql += " AND p.created_at::date::text=?" if USE_PG else " AND date(p.created_at)=?"
        params.append(date)
    if shift_id:
        sql += " AND p.shift_id=?"
        params.append(int(shift_id))
    sql += " ORDER BY p.created_at DESC LIMIT ?"
    params.append(limit_n)
    cur = db_exec(conn, sql, tuple(params))
    result = rows_to_list(cur)
    conn.close()
    return jsonify(result)


# ===== LOYALTY KARTALAR =====
@app.route("/api/customers", methods=["GET"])
def get_customers():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    search = request.args.get("q", "")
    if search:
        cur = db_exec(conn, "SELECT * FROM customers WHERE phone LIKE ? OR name LIKE ? ORDER BY total_spent DESC",
                      (f"%{search}%", f"%{search}%"))
    else:
        cur = db_exec(conn, "SELECT * FROM customers ORDER BY total_spent DESC")
    result = rows_to_list(cur)
    conn.close()
    return jsonify(result)

@app.route("/api/customers/lookup", methods=["GET"])
def lookup_customer():
    phone = request.args.get("phone", "").strip()
    if not phone: return jsonify({"found": False}), 200
    conn = get_conn()
    cur = db_exec(conn, "SELECT * FROM customers WHERE phone=?", (phone,))
    rows = rows_to_list(cur)
    conn.close()
    if rows:
        return jsonify({"found": True, "customer": rows[0]})
    return jsonify({"found": False})

@app.route("/api/customers", methods=["POST"])
def add_customer():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    phone = (d.get("phone") or "").strip()
    if not phone: return jsonify({"error": "Telefon kiritilmadi"}), 400
    conn = get_conn()
    try:
        db_exec(conn, "INSERT INTO customers (name, phone, discount_pct, notes) VALUES (?,?,?,?)",
                (d.get("name",""), phone, d.get("discount_pct", 0), d.get("notes","")))
        conn.commit()
    except Exception as e:
        conn.close()
        return jsonify({"error": "Bu telefon allaqachon mavjud"}), 409
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/customers/<int:cid>", methods=["PUT"])
def update_customer(cid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    db_exec(conn, "UPDATE customers SET name=?, phone=?, discount_pct=?, notes=? WHERE id=?",
            (d.get("name",""), d.get("phone",""), d.get("discount_pct",0), d.get("notes",""), cid))
    conn.commit(); conn.close()
    return jsonify({"ok": True})

@app.route("/api/customers/<int:cid>", methods=["DELETE"])
def delete_customer(cid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    db_exec(conn, "DELETE FROM customers WHERE id=?", (cid,))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


# ===== EMAIL YUBORISH =====
def send_email(to: str, subject: str, html_body: str) -> bool:
    """SMTP orqali email yuborish. DB sozlamalari yoki env: SMTP_HOST/PORT/USER/PASS"""
    host   = get_setting("smtp_host")   or os.environ.get("SMTP_HOST", "")
    port   = int(get_setting("smtp_port") or os.environ.get("SMTP_PORT", "587"))
    user   = get_setting("smtp_user")   or os.environ.get("SMTP_USER", "")
    passwd = get_setting("smtp_pass")   or os.environ.get("SMTP_PASS", "")
    from_addr = user
    if not host or not user or not passwd:
        log.warning("Email konfiguratsiya yo'q (SMTP_HOST/USER/PASS)")
        return False
    try:
        msg = email.mime.multipart.MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to
        msg.attach(email.mime.text.MIMEText(html_body, "html", "utf-8"))
        with smtplib.SMTP(host, port, timeout=10) as s:
            s.ehlo()
            s.starttls()
            s.login(user, passwd)
            s.sendmail(from_addr, [to], msg.as_string())
        return True
    except Exception as e:
        log.warning("Email xatosi: %s", e)
        return False


@app.route("/api/shift/<int:shift_id>/email-report", methods=["POST"])
def email_shift_report(shift_id):
    """Smena hisobotini emailga yuborish."""
    if not check_auth():
        d = request.json or {}
        staff = check_staff_pin(d.get("pin")) if d.get("pin") else None
        if not staff or not has_role(staff, "cashier", "manager"):
            return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    to_email = d.get("email", "").strip()
    if not to_email or "@" not in to_email:
        return jsonify({"error": "Email manzil kiritilmadi"}), 400

    conn = get_conn()
    cur = db_exec(conn, "SELECT * FROM shifts WHERE id=?", (shift_id,))
    rows = rows_to_list(cur)
    if not rows:
        conn.close()
        return jsonify({"error": "Smena topilmadi"}), 404
    s = rows[0]

    cur2 = db_exec(conn, "SELECT method, COALESCE(SUM(amount),0) AS total FROM payments WHERE shift_id=? GROUP BY method", (shift_id,))
    methods = rows_to_list(cur2)
    cur3 = db_exec(conn, "SELECT COALESCE(SUM(amount),0) FROM payments WHERE shift_id=?", (shift_id,))
    total_pay = int((cur3.fetchone() or [0])[0] or 0)
    cur4 = db_exec(conn, "SELECT COUNT(DISTINCT session_id) FROM payments WHERE shift_id=?", (shift_id,))
    sess_cnt = int((cur4.fetchone() or [0])[0] or 0)
    conn.close()

    opened = str(s.get("opened_at") or "")[:16]
    closed = str(s.get("closed_at") or "")[:16]
    cashier = str(s.get("cashier_name") or "")
    meth_rows = "".join(
        f"<tr><td style='padding:6px 12px'>{r.get('method','')}</td>"
        f"<td style='padding:6px 12px;text-align:right'><b>{int(r.get('total') or 0):,} so'm</b></td></tr>"
        for r in methods
    )

    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:520px;margin:0 auto;background:#f8f8f8;padding:24px;border-radius:12px">
      <div style="background:#0f0f1a;border-radius:8px;padding:20px;text-align:center;margin-bottom:20px">
        <h1 style="color:#d4af37;font-size:22px;margin:0;letter-spacing:2px">RAYYON RESTORAN</h1>
        <p style="color:rgba(255,255,255,0.5);margin:4px 0 0;font-size:13px">Smena #{shift_id} hisoboti</p>
      </div>
      <table style="width:100%;background:#fff;border-radius:8px;border-collapse:collapse;margin-bottom:16px">
        <tr><td style="padding:10px 16px;color:#555">Kassir</td><td style="padding:10px 16px;text-align:right;font-weight:600">{cashier}</td></tr>
        <tr style="background:#f9f9f9"><td style="padding:10px 16px;color:#555">Ochildi</td><td style="padding:10px 16px;text-align:right">{opened}</td></tr>
        <tr><td style="padding:10px 16px;color:#555">Yopildi</td><td style="padding:10px 16px;text-align:right">{closed}</td></tr>
        <tr style="background:#f9f9f9"><td style="padding:10px 16px;color:#555">Sessiyalar</td><td style="padding:10px 16px;text-align:right">{sess_cnt} ta</td></tr>
        <tr style="background:#e8f5e9"><td style="padding:10px 16px;font-weight:700">Jami daromad</td><td style="padding:10px 16px;text-align:right;font-weight:700;color:#2e7d32;font-size:18px">{total_pay:,} so'm</td></tr>
      </table>
      <h3 style="font-size:14px;color:#333;margin:0 0 8px">To'lov usullari:</h3>
      <table style="width:100%;background:#fff;border-radius:8px;border-collapse:collapse;margin-bottom:20px">
        {meth_rows or "<tr><td style='padding:10px 16px;color:#999'>To'lovlar yo'q</td></tr>"}
      </table>
      <p style="text-align:center;font-size:11px;color:#aaa">Rayyon Restoran Boshqaruv Tizimi &mdash; {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
    </div>
    """
    ok = send_email(to_email, f"Smena #{shift_id} hisoboti — Rayyon Restoran", html)
    if ok:
        return jsonify({"ok": True, "sent_to": to_email})
    return jsonify({"error": "Email yuborishda xato. SMTP sozlamalarini tekshiring."}), 500


# ===== LOYALTY KARTA (public) =====
@app.route("/api/loyalty-card/<int:cid>", methods=["GET"])
def loyalty_card(cid):
    """Ochiq endpoint — mijoz o'z karta ma'lumotlarini ko'radi (token kerak emas)."""
    conn = get_conn()
    cur = db_exec(conn, "SELECT id,name,phone,total_spent,visits,loyalty_points,discount_pct FROM customers WHERE id=?", (cid,))
    rows = rows_to_list(cur)
    conn.close()
    if not rows:
        return jsonify({"error": "Mijoz topilmadi"}), 404
    c = rows[0]
    pts = c.get("loyalty_points") or 0
    tier = ("Platinum" if pts >= 500 else "Gold" if pts >= 200 else "Silver" if pts >= 100 else "Bronze" if pts >= 1 else "Yangi")
    # Keyingi darajaga kerakli ball chegarasi
    if pts < 1:    next_tier_pts = 1    # Yangi → Bronze
    elif pts < 100: next_tier_pts = 100  # Bronze → Silver
    elif pts < 200: next_tier_pts = 200  # Silver → Gold
    elif pts < 500: next_tier_pts = 500  # Gold → Platinum
    else:           next_tier_pts = pts  # Platinum — maksimal
    return jsonify({
        "id": c["id"], "name": c["name"] or "Mijoz",
        "phone": str(c["phone"])[:4] + "****" + str(c["phone"])[-2:],
        "total_spent": c["total_spent"], "visits": c["visits"],
        "loyalty_points": pts, "discount_pct": c["discount_pct"],
        "tier": tier, "next_tier_pts": max(0, next_tier_pts - pts),
    })


# ===== STATIC FILES =====
@app.route("/")
def serve_site():
    base = os.path.join(os.path.dirname(__file__), "..")
    return send_from_directory(base, "index.html")

# Admin panel va boshqa HTML sahifalar uchun aniq yo'llar
@app.route("/admin")
@app.route("/admin/")
def serve_admin():
    base = os.path.join(os.path.dirname(__file__), "..", "admin")
    return send_from_directory(base, "index.html")

@app.route("/admin/<path:path>")
def serve_admin_files(path):
    base = os.path.join(os.path.dirname(__file__), "..", "admin")
    return send_from_directory(base, path)

# Nisbiy yo'l xatolarini tuzatish: /login.html → /admin/login.html
@app.route("/login.html")
def redirect_login_html():
    return redirect("/admin/login.html", code=301)


@app.route("/<path:path>")
def serve_static(path):
    base = os.path.join(os.path.dirname(__file__), "..")
    full = os.path.join(base, path)
    # Papka bo'lsa (masalan /admin, /waiter) — index.html xizmat qilish
    if os.path.isdir(full):
        return send_from_directory(full, "index.html")
    return send_from_directory(base, path)


# ===== CSV EKSPORT =====
def _csv_response(rows, filename):
    """rows — list of dicts. CSV Response qaytaradi."""
    if not rows:
        return Response("", mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename={filename}"})
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=rows[0].keys())
    w.writeheader(); w.writerows(rows)
    bom = "﻿"  # Excel UTF-8 BOM
    return Response(bom + out.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


@app.route("/api/export/payments", methods=["GET"])
def export_payments():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    month = request.args.get("month", datetime.datetime.utcnow().strftime("%Y-%m"))
    conn  = get_conn()
    if USE_PG:
        cur = db_exec(conn, "SELECT * FROM payments WHERE to_char(created_at,'YYYY-MM')=%s ORDER BY created_at DESC", (month,))
    else:
        cur = db_exec(conn, "SELECT * FROM payments WHERE strftime('%Y-%m',created_at)=? ORDER BY created_at DESC", (month,))
    rows = rows_to_list(cur); conn.close()
    return _csv_response(rows, f"payments_{month}.csv")


@app.route("/api/export/sessions", methods=["GET"])
def export_sessions():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    month = request.args.get("month", datetime.datetime.utcnow().strftime("%Y-%m"))
    conn  = get_conn()
    if USE_PG:
        cur = db_exec(conn, "SELECT id,table_number,waiter_name,status,total_amount,discount,service_charge,opened_at,closed_at FROM sessions WHERE to_char(opened_at,'YYYY-MM')=%s ORDER BY opened_at DESC", (month,))
    else:
        cur = db_exec(conn, "SELECT id,table_number,waiter_name,status,total_amount,discount,service_charge,opened_at,closed_at FROM sessions WHERE strftime('%Y-%m',opened_at)=? ORDER BY opened_at DESC", (month,))
    rows = rows_to_list(cur); conn.close()
    return _csv_response(rows, f"sessions_{month}.csv")


@app.route("/api/export/staff", methods=["GET"])
def export_staff():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    cur  = db_exec(conn, "SELECT id,name,role,phone,salary_type,salary_amount,active,created_at FROM staff ORDER BY name")
    rows = rows_to_list(cur); conn.close()
    return _csv_response(rows, "staff.csv")


@app.route("/api/export/inventory", methods=["GET"])
def export_inventory():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    cur  = db_exec(conn, "SELECT * FROM inventory ORDER BY name")
    rows = rows_to_list(cur); conn.close()
    return _csv_response(rows, "inventory.csv")


# ===== SSE — REAL-TIME YANGILANISHLAR =====
_sse_clients: list = []
_sse_lock = threading.Lock()

def _sse_broadcast(event: str, data: dict):
    """Barcha ulangan mijozlarga SSE xabari yuborish."""
    msg = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
    with _sse_lock:
        for q in list(_sse_clients):
            try:
                q.put_nowait(msg)
            except Exception:
                pass

@app.route("/api/events")
def sse_stream():
    """SSE oqimi — oshxona va ofitsiant paneli uchun real-time."""
    from queue import Queue, Empty
    client_q = Queue(maxsize=50)
    with _sse_lock:
        _sse_clients.append(client_q)

    def generate():
        try:
            yield "data: {\"type\": \"connected\"}\n\n"
            while True:
                try:
                    msg = client_q.get(timeout=25)
                    yield msg
                except Empty:
                    yield ": ping\n\n"
        finally:
            with _sse_lock:
                try:
                    _sse_clients.remove(client_q)
                except ValueError:
                    pass

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ===== PUSH NOTIFICATIONS =====
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC_KEY  = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_CLAIMS      = {"sub": f"mailto:{os.environ.get('VAPID_EMAIL', 'admin@rayyon.uz')}"}

@app.route("/api/push/vapid-key", methods=["GET"])
def push_vapid_key():
    """Frontend uchun VAPID public key."""
    if not VAPID_PUBLIC_KEY:
        return jsonify({"ok": False, "error": "VAPID_PUBLIC_KEY o'rnatilmagan"}), 503
    return jsonify({"ok": True, "key": VAPID_PUBLIC_KEY})

@app.route("/api/push/subscribe", methods=["POST"])
def push_subscribe():
    """Push subscription saqlash."""
    data = request.json or {}
    subscription = data.get("subscription")
    if not subscription:
        return jsonify({"ok": False, "error": "subscription yo'q"}), 400
    endpoint = subscription.get("endpoint", "")
    if not endpoint:
        return jsonify({"ok": False, "error": "endpoint yo'q"}), 400
    keys    = subscription.get("keys", {})
    p256dh  = keys.get("p256dh", "")
    auth_key = keys.get("auth", "")
    conn = get_conn()
    try:
        db_exec(conn, """
            INSERT OR IGNORE INTO push_subscriptions (endpoint, p256dh, auth)
            VALUES (?, ?, ?)
        """, (endpoint, p256dh, auth_key))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})

@app.route("/api/push/unsubscribe", methods=["POST"])
def push_unsubscribe():
    """Push subscription o'chirish."""
    data = request.json or {}
    endpoint = data.get("endpoint", "")
    if not endpoint:
        return jsonify({"ok": False}), 400
    conn = get_conn()
    try:
        db_exec(conn, "DELETE FROM push_subscriptions WHERE endpoint=?", (endpoint,))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})

@app.route("/api/push/send", methods=["POST"])
def push_send():
    """Barcha obunachilarga push notification yuborish (faqat admin)."""
    if not check_auth():
        return jsonify({"ok": False, "error": "Ruxsat yo'q"}), 403
    if not VAPID_PRIVATE_KEY or not VAPID_PUBLIC_KEY:
        return jsonify({"ok": False, "error": "VAPID kalitlari o'rnatilmagan"}), 503
    data = request.json or {}
    payload = json.dumps({
        "title": data.get("title", "Rayyon Restoran"),
        "body":  data.get("body", ""),
        "url":   data.get("url", "/"),
        "tag":   data.get("tag", "rayyon"),
    })
    conn = get_conn()
    try:
        cur = db_exec(conn, "SELECT * FROM push_subscriptions", ())
        subs = rows_to_list(cur)
    finally:
        conn.close()
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        return jsonify({"ok": False, "error": "pywebpush o'rnatilmagan"}), 503
    sent = 0
    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub["endpoint"],
                    "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
                },
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS,
            )
            sent += 1
        except Exception as e:
            log.warning("Push yuborilmadi %s: %s", sub["endpoint"][:40], e)
    return jsonify({"ok": True, "sent": sent, "total": len(subs)})


# ===== AUDIT LOG =====
@app.route("/api/audit", methods=["GET"])
def get_audit_log():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    limit  = min(int(request.args.get("limit",  100)), 500)
    offset = max(int(request.args.get("offset", 0)),   0)
    action = request.args.get("action")
    entity = request.args.get("entity")
    conn   = get_conn()
    if action and entity:
        cur = db_exec(conn,
            "SELECT * FROM audit_log WHERE action=? AND entity=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (action, entity, limit, offset))
    elif action:
        cur = db_exec(conn,
            "SELECT * FROM audit_log WHERE action=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (action, limit, offset))
    else:
        cur = db_exec(conn,
            "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset))
    result = rows_to_list(cur)
    conn.close()
    return jsonify({"data": result, "limit": limit, "offset": offset, "count": len(result)})


@app.route("/api/export/audit", methods=["GET"])
def export_audit_csv():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    cur  = db_exec(conn, "SELECT * FROM audit_log ORDER BY created_at DESC")
    rows = rows_to_list(cur); conn.close()
    return _csv_response(rows, "audit_log.csv")


# ===== HEALTH CHECK =====
@app.route("/api/health", methods=["GET"])
def health_check():
    # Render health check uchun doim 200 qaytaradi — server ishlayapti degan signal
    # DB holati alohida ko'rsatiladi lekin 503 qaytarmaydi (deploy failed bo'lmasin)
    return jsonify({
        "status": "ok",
        "db_ready": _db_ready,
        "version": "1.0.0",
    }), 200


# ===== QOSHIMCHA CSV EKSPORT =====
@app.route("/api/export/orders", methods=["GET"])
def export_orders_csv():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    date_from = request.args.get("from")
    date_to   = request.args.get("to")
    conn = get_conn()
    if date_from and date_to:
        cur = db_exec(conn,
            "SELECT * FROM orders WHERE created_at>=? AND created_at<=? ORDER BY created_at DESC",
            (date_from, date_to + " 23:59:59"))
    else:
        cur = db_exec(conn, "SELECT * FROM orders ORDER BY created_at DESC")
    rows = rows_to_list(cur); conn.close()
    return _csv_response(rows, "orders.csv")


@app.route("/api/export/expenses", methods=["GET"])
def export_expenses_csv():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    date_from = request.args.get("from")
    date_to   = request.args.get("to")
    conn = get_conn()
    if date_from and date_to:
        cur = db_exec(conn,
            "SELECT * FROM expenses WHERE date>=? AND date<=? ORDER BY date DESC",
            (date_from, date_to))
    else:
        cur = db_exec(conn, "SELECT * FROM expenses ORDER BY date DESC")
    rows = rows_to_list(cur); conn.close()
    return _csv_response(rows, "expenses.csv")


@app.route("/api/export/attendance", methods=["GET"])
def export_attendance_csv():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    date_from = request.args.get("from")
    date_to   = request.args.get("to")
    conn = get_conn()
    if date_from and date_to:
        cur = db_exec(conn,
            "SELECT * FROM attendance WHERE date>=? AND date<=? ORDER BY date DESC",
            (date_from, date_to))
    else:
        cur = db_exec(conn, "SELECT * FROM attendance ORDER BY check_in DESC")
    rows = rows_to_list(cur); conn.close()
    return _csv_response(rows, "attendance.csv")


# ===== 404 / 500 XATO HANDLERLARI =====
@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Endpoint topilmadi", "path": request.path}), 404
    return jsonify({"error": "Sahifa topilmadi"}), 404

@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({"error": "Bu method ruxsat etilmagan", "allowed": e.valid_methods}), 405

@app.errorhandler(500)
def internal_error(e):
    log.error("500 xato: %s — %s", request.path, e)
    return jsonify({"error": "Server ichki xatosi"}), 500

@app.errorhandler(429)
def too_many_requests(e):
    return jsonify({"error": "Juda ko'p so'rov. Biroz kuting."}), 429


if __name__ == "__main__":
    # Xavfsizlik tekshiruvi: ADMIN_PASSWORD env var o'rnatilganligini nazorat qilish
    if not os.environ.get("ADMIN_PASSWORD"):
        log.warning("=" * 60)
        log.warning("XAVFSIZLIK OGOHLANTIRISHI: ADMIN_PASSWORD env var")
        log.warning("o'rnatilmagan! Default 'rayyon2024' paroli ishlatilmoqda.")
        log.warning("Production uchun: export ADMIN_PASSWORD='kuchli_parol'")
        log.warning("=" * 60)
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV") != "production"
    print(f"Rayyon backend ishga tushdi: http://localhost:{port}")
    app.run(host="0.0.0.0", debug=debug, port=port)
