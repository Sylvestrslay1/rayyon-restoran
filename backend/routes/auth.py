"""auth.py — login, logout, auth/check, staff/login"""
import os, time, logging, hmac

from flask import Blueprint, request, jsonify
from database import get_conn, USE_PG
from helpers import (
    check_auth, check_staff_pin, audit, get_remote_address,
    _pin_check_locked, _pin_record_fail, _pin_record_success,
    create_admin_token, revoke_admin_token, hash_password, verify_password,
    get_setting, db_exec, PIN_LOCKOUT_MINUTES, TOKEN_TTL_HOURS, limiter,
)

log = logging.getLogger(__name__)
bp = Blueprint('auth', __name__)


@bp.route("/api/login", methods=["POST"])
@limiter.limit("5 per minute; 20 per hour")
def login():
    data = request.json or {}
    password = data.get("password", "")
    if not password:
        return jsonify({"ok": False, "error": "Parol kiritilmadi"}), 400

    stored_hash  = get_setting("admin_password_hash")
    stored_salt  = get_setting("admin_password_salt")
    stored_plain = get_setting("admin_password")
    env_password = os.environ.get("ADMIN_PASSWORD", "")

    authenticated = False

    if env_password and hmac.compare_digest(password, env_password):
        authenticated = True
        new_hash, new_salt = hash_password(password)
        conn2 = get_conn()
        try:
            if USE_PG:
                for k, v in [("admin_password_hash", new_hash), ("admin_password_salt", new_salt)]:
                    db_exec(conn2,
                        "INSERT INTO settings (key,value) VALUES (%s,%s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",
                        (k, v))
                db_exec(conn2, "DELETE FROM settings WHERE key=%s", ("admin_password",))
            else:
                db_exec(conn2, "INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", ("admin_password_hash", new_hash))
                db_exec(conn2, "INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", ("admin_password_salt", new_salt))
                db_exec(conn2, "DELETE FROM settings WHERE key=?", ("admin_password",))
            conn2.commit()
        except Exception as _e:
            log.warning("Parol hash yangilash xato: %s", _e)
        finally:
            conn2.close()

    elif stored_hash and stored_salt:
        authenticated = verify_password(password, stored_hash, stored_salt)

    elif stored_plain and hmac.compare_digest(password, stored_plain):
        authenticated = True
        new_hash, new_salt = hash_password(password)
        conn2 = get_conn()
        try:
            db_exec(conn2, "INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", ("admin_password_hash", new_hash))
            db_exec(conn2, "INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", ("admin_password_salt", new_salt))
            db_exec(conn2, "DELETE FROM settings WHERE key=?", ("admin_password",))
            conn2.commit()
            log.info("Admin parol plaintext dan PBKDF2 ga o'tkazildi")
        except Exception as _upe:
            log.warning("Parol upgrade xato: %s", _upe)
        finally:
            conn2.close()

    if not authenticated:
        time.sleep(0.3)
        audit("login_fail", "admin", user_name="admin",
              details={"ip": get_remote_address(), "reason": "wrong_password"})
        return jsonify({"ok": False, "error": "Parol noto'g'ri"}), 401

    ip = get_remote_address()
    token = create_admin_token(ip)
    audit("login", "admin", user_name="admin")
    return jsonify({"ok": True, "token": token, "ttl_hours": TOKEN_TTL_HOURS})


@bp.route("/api/logout", methods=["POST"])
def logout():
    token = request.headers.get("X-Admin-Token", "")
    revoke_admin_token(token)
    audit("logout", "admin", user_name="admin")
    return jsonify({"ok": True})


@bp.route("/api/auth/check", methods=["GET"])
def auth_check():
    return jsonify({"ok": check_auth()})


@bp.route("/api/staff/login", methods=["POST"])
@limiter.limit("5 per minute; 30 per hour")
def staff_login():
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
        audit("pin_fail", "staff", details={"reason": "wrong_pin", "ip": ip})
        return jsonify({"ok": False, "error": "PIN noto'g'ri"}), 401
    _pin_record_success(ip)

    role = staff.get("role", "waiter")
    redirect_map = {
        "admin": "admin", "director": "director", "accountant": "accountant",
        "manager": "manager", "chef": "chef", "cashier": "cashier",
        "waiter": "waiter", "kitchen": "kitchen",
    }
    redirect_val = redirect_map.get(role, "waiter")

    panel_roles = {"admin", "director", "accountant", "manager", "chef"}
    token = None
    if role in panel_roles:
        token = create_admin_token(get_remote_address())

    resp = {
        "ok": True,
        "id": staff["id"],
        "name": staff["name"],
        "role": role,
        "redirect": redirect_val,
    }
    if token:
        resp["token"] = token
    return jsonify(resp)
