"""tables.py — tables CRUD"""
import datetime, logging

from flask import Blueprint, request, jsonify
from database import rows_to_list
from helpers import check_auth, db_exec, get_db, limiter

log = logging.getLogger(__name__)
bp = Blueprint('tables', __name__)


@bp.route("/api/tables", methods=["GET"])
def get_tables():
    conn = get_db()
    cur  = db_exec(conn, """
        SELECT t.*, s.opened_at, s.total_amount, s.token, s.waiter_name
        FROM tables t
        LEFT JOIN sessions s ON t.current_session_id = s.id
        ORDER BY t.number
    """)
    tables = rows_to_list(cur)
    for tbl in tables:
        if tbl.get("opened_at"):
            opened = tbl["opened_at"]
            if isinstance(opened, str):
                try: opened = datetime.datetime.fromisoformat(opened.replace("Z",""))
                except: opened = None
            if opened:
                diff = datetime.datetime.utcnow() - opened.replace(tzinfo=None)
                tbl["minutes_open"] = int(diff.total_seconds() // 60)
    return jsonify(tables)


@bp.route("/api/tables", methods=["POST"])
def add_table():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    number = d.get("number")
    if not number and number != 0:
        return jsonify({"error": "Stol raqami kiritilmadi"}), 400
    try:
        number = int(number)
        if number <= 0:
            return jsonify({"error": "Stol raqami musbat bo'lishi kerak"}), 400
    except (ValueError, TypeError):
        return jsonify({"error": "Stol raqami butun son bo'lishi kerak"}), 400
    conn = get_db()
    db_exec(conn, "INSERT INTO tables (number, name, capacity) VALUES (?,?,?)",
        (number, d.get("name", f"Stol {number}"), d.get("capacity", 4)))
    conn.commit()
    return jsonify({"ok": True})


@bp.route("/api/tables/<int:tid>", methods=["PUT"])
def update_table(tid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_db()
    db_exec(conn, "UPDATE tables SET number=?, name=?, capacity=? WHERE id=?",
        (d.get("number"), d.get("name"), d.get("capacity", 4), tid))
    conn.commit()
    return jsonify({"ok": True})


@bp.route("/api/tables/<int:tid>", methods=["DELETE"])
@limiter.limit("10 per minute")
def delete_table(tid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_db()
    try:
        db_exec(conn, "DELETE FROM tables WHERE id=?", (tid,))
        conn.commit()
    except Exception as _dbe:
        try: conn.rollback()
        except Exception: pass
        log.error("DB xato: %s", _dbe)
        return jsonify({"error": "Server xatosi"}), 500
    return jsonify({"ok": True})
