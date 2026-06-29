"""settings_routes.py — settings GET/PUT"""
import logging

from flask import Blueprint, request, jsonify
from database import rows_to_list, USE_PG
from helpers import (
    check_auth, get_setting, db_exec, get_db,
    hash_password,
)

log = logging.getLogger(__name__)
bp = Blueprint('settings_routes', __name__)

PUBLIC_SETTINGS = {"restaurant_name", "phone", "address", "working_hours", "telegram_bot"}


@bp.route("/api/settings", methods=["GET"])
def get_settings():
    conn = get_db()
    cur = db_exec(conn, "SELECT key, value FROM settings")
    rows = cur.fetchall()
    if USE_PG:
        all_s = {r[0]: r[1] for r in rows}
    else:
        all_s = {r["key"]: r["value"] for r in rows}
    SENSITIVE = {"admin_password", "admin_password_hash", "admin_password_salt"}
    if not check_auth():
        public = [{"key": k, "value": v} for k, v in all_s.items() if k in PUBLIC_SETTINGS]
        return jsonify(public)
    return jsonify({k: v for k, v in all_s.items() if k not in SENSITIVE})


@bp.route("/api/settings", methods=["PUT"])
def update_settings():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_db()
    for key, val in d.items():
        if key == "admin_password":
            if not val or len(str(val)) < 6:
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
    conn.commit()
    return jsonify({"ok": True})
