"""
helpers.py — Shared helper funksiyalar va global o'zgaruvchilar.
app.py va barcha blueprint fayllar bu moduldan import qiladi.
"""
import os, time, json, secrets, hashlib, hmac, threading, datetime, logging
import urllib.request, urllib.parse

from flask import request, g as _g
from database import get_conn, rows_to_list, USE_PG

log = logging.getLogger(__name__)

# ===== ENV VARS =====
TG_TOKEN      = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT       = os.environ.get("TELEGRAM_CHAT_ID", "")
KITCHEN_TOKEN = os.environ.get("KITCHEN_TOKEN", "")

# ===== XAVFSIZLIK KONSTANTALARI =====
TOKEN_TTL_HOURS   = 4
PBKDF2_ITERATIONS = 200_000
ALLOWED_PERIODS   = {"daily", "weekly", "monthly"}
ALLOWED_EXT       = {"png", "jpg", "jpeg", "gif", "webp"}

# ===== PIN BRUTE-FORCE HIMOYA =====
_pin_fails: dict = {}
_pin_fails_lock  = threading.Lock()
PIN_MAX_TRIES        = 5
PIN_LOCKOUT_MINUTES  = 15

# ===== TOKEN (in-memory) =====
_tokens_lock  = threading.Lock()
ACTIVE_TOKENS: dict = {}

# ===== SSE CLIENTS =====
_sse_clients: list = []
_sse_lock = threading.Lock()

# ===== DB READY STATE =====
_db_ready = False
_db_error = None

# ===== LIMITER (app.py da init_app(app) chaqiriladi) =====
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address as _gra_util

limiter = Limiter(
    key_func=_gra_util,
    default_limits=["5000/day", "1000/hour"],
    storage_uri="memory://",
    headers_enabled=True,
)

# ===== REDIS (ixtiyoriy) =====
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

# ===== ROL VA RUXSATLAR =====
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


# ===== DB HELPER =====
def get_db():
    """Request kontekstida bitta connection qayta ishlatiladi."""
    if "db" not in _g:
        _g.db = get_conn()
    return _g.db


def q(sql):
    """? -> %s for PostgreSQL"""
    return sql.replace("?", "%s") if USE_PG else sql


def db_exec(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(q(sql), params)
    return cur


# ===== PIN FUNCTIONS =====
def _pin_check_locked(ip: str) -> bool:
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


# ===== ROL TEKSHIRISH =====
def has_role(staff, *allowed_roles) -> bool:
    if staff is None:
        return False
    role = staff.get("role", "")
    if role in ("admin", "director"):
        return True
    return role in allowed_roles


def staff_has_perm(staff, perm: str) -> bool:
    if staff is None:
        return False
    role = staff.get("role", "")
    perms = ROLE_PERMISSIONS.get(role, set())
    return "all" in perms or perm in perms


# ===== PAROL HASHING =====
def hash_password(password: str, salt: bytes = None):
    if salt is None:
        salt = os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return h.hex(), salt.hex()


def verify_password(password: str, stored_hash: str, stored_salt: str) -> bool:
    try:
        salt = bytes.fromhex(stored_salt)
        h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
        return hmac.compare_digest(h.hex(), stored_hash)
    except Exception:
        return False


def verify_legacy_pin(pin: str, stored_hash: str) -> bool:
    try:
        legacy = hashlib.sha256(str(pin).encode()).hexdigest()[:8]
        return hmac.compare_digest(legacy, stored_hash)
    except Exception:
        return False


# ===== TOKEN BOSHQARUVI =====
def _prune_expired_tokens():
    if _redis:
        return
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


# ===== AUTH TEKSHIRISH =====
def get_remote_address():
    """Flask-Limiter bilan moslik uchun."""
    return _gra_util()


def check_auth() -> bool:
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


def check_staff_pin(pin, conn=None):
    if not pin:
        return None
    pin_str = str(pin)
    close = conn is None
    if close:
        conn = get_conn()
    cur = db_exec(conn, "SELECT * FROM staff WHERE active=1", ())
    all_staff = rows_to_list(cur)
    found = None
    for s in all_staff:
        if not s.get("pin"):
            continue
        if s.get("pin_salt"):
            if verify_password(pin_str, s["pin"], s["pin_salt"]):
                found = s
                break
        else:
            if verify_legacy_pin(pin_str, s["pin"]):
                found = s
                break
    if close:
        conn.close()
    return found


def check_kitchen_auth() -> bool:
    if check_auth():
        return True
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
    if not KITCHEN_TOKEN:
        log.warning("KITCHEN_TOKEN o'rnatilmagan — oshxona endpoint himoyasiz! ENV var qo'shing.")
        return False
    provided = (request.headers.get("X-Kitchen-Token", "")
                or request.args.get("kitchen_token", ""))
    if not provided:
        return False
    return hmac.compare_digest(provided, KITCHEN_TOKEN)


# ===== AUDIT =====
def audit(action: str, entity: str = None, entity_id: int = None,
          user_name: str = None, details: dict = None):
    ip = get_remote_address()
    det = json.dumps(details, ensure_ascii=False) if details else None
    try:
        conn = get_db()
        db_exec(conn,
            "INSERT INTO audit_log (action, entity, entity_id, user_name, user_ip, details) VALUES (?,?,?,?,?,?)",
            (action, entity, entity_id, user_name, ip, det))
        conn.commit()
    except Exception as e:
        log.warning("audit() xato: %s", e)


# ===== TELEGRAM =====
def _tg_escape(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def tg_send(text):
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
        log.warning("tg_send xato: %s", type(e).__name__)


# ===== VALIDATSIYA =====
def _validate_str(val, max_len: int, field: str):
    if val is not None and len(str(val)) > max_len:
        raise ValueError(f"{field} juda uzun (maksimum {max_len} belgi)")


def _int_param(name: str, default: int, min_val: int = 0, max_val: int = 10000) -> int:
    try:
        v = int(request.args.get(name, default))
        return max(min_val, min(v, max_val))
    except (ValueError, TypeError):
        return default


# ===== IMAGE =====
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def check_image_mime(file_stream) -> bool:
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


# ===== SETTINGS HELPER =====
def get_setting(key):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(q("SELECT value FROM settings WHERE key=?"), (key,))
        row = cur.fetchone()
    except Exception:
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute(q("SELECT value FROM settings WHERE key=?"), (key,))
            row = cur.fetchone()
        finally:
            conn.close()
    if not row:
        return None
    return row["value"] if not USE_PG else row[0]


# ===== SSE =====
def _sse_broadcast(event: str, data: dict):
    msg = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
    with _sse_lock:
        for client_q in list(_sse_clients):
            try:
                client_q.put_nowait(msg)
            except Exception:
                pass


# ===== CSV RESPONSE =====
def _csv_response(rows, filename):
    import csv, io
    from flask import Response
    if not rows:
        return Response("", mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename={filename}"})
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=rows[0].keys())
    w.writeheader()
    w.writerows(rows)
    bom = "﻿"
    return Response(bom + out.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


# ===== SESSION TOTAL =====
def _calc_session_total(sid, conn) -> int:
    cur = db_exec(conn,
        "SELECT COALESCE(SUM(total_price),0) FROM order_items WHERE session_id=? AND status!='cancelled'",
        (sid,))
    row = cur.fetchone()
    subtotal = int(row[0] if row and row[0] else 0)
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


# ===== INVENTORY =====
def _inv_update(conn, needed, inv_id, unit_cond=""):
    where = f"id=? {unit_cond}".strip()
    if USE_PG:
        sql = f"UPDATE inventory SET quantity = GREATEST(0, quantity - ?) WHERE {where}"
        db_exec(conn, sql, (needed, inv_id))
    else:
        sql = f"UPDATE inventory SET quantity = CASE WHEN quantity - ? < 0 THEN 0 ELSE quantity - ? END WHERE {where}"
        db_exec(conn, sql, (needed, needed, inv_id))


def deduct_inventory(menu_item_id, quantity, conn, note=""):
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


# ===== EMAIL =====
def send_email(to: str, subject: str, html_body: str) -> bool:
    import smtplib, email.mime.text, email.mime.multipart
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
