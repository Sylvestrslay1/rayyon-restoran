"""reservations.py — reservations CRUD"""
import logging

from flask import Blueprint, request, jsonify
from database import get_conn, rows_to_list, USE_PG
from helpers import (
    check_auth, _validate_str, _int_param, db_exec, get_db, limiter,
    tg_send, _tg_escape,
)

log = logging.getLogger(__name__)
bp = Blueprint('reservations', __name__)


@bp.route("/api/reservations", methods=["GET"])
def get_reservations():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    limit  = _int_param("limit", 200, max_val=1000)
    offset = _int_param("offset", 0, min_val=0)
    date   = request.args.get("date")
    conn   = get_db()
    if date:
        cur = db_exec(conn,
            "SELECT * FROM reservations WHERE date=? ORDER BY time ASC LIMIT ? OFFSET ?",
            (date, limit, offset))
    else:
        cur = db_exec(conn,
            "SELECT * FROM reservations ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset))
    result = rows_to_list(cur)
    return jsonify({"data": result, "limit": limit, "offset": offset, "count": len(result)})


@bp.route("/api/reservations", methods=["POST"])
@limiter.limit("10 per minute; 50 per hour")
def add_reservation():
    d = request.json or {}
    try:
        _validate_str(d.get("customer_name"),  100, "Ism")
        _validate_str(d.get("customer_phone"),  20, "Telefon")
        _validate_str(d.get("note"),           500, "Izoh")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    conn = get_db()
    try:
        db_exec(conn,
            "INSERT INTO reservations (customer_name, customer_phone, date, time, guests, note) VALUES (?,?,?,?,?,?)",
            (d.get("customer_name"), d.get("customer_phone"), d.get("date"), d.get("time"), d.get("guests", 2), d.get("note"))
        )
        conn.commit()
    except Exception as _dbe:
        try: conn.rollback()
        except Exception: pass
        log.error("add_reservation DB xato: %s", _dbe)
        return jsonify({"error": "Server xatosi"}), 500
    tg_send(
        f"📅 <b>Yangi bron!</b>\n"
        f"👤 Mijoz: {_tg_escape(d.get('customer_name',''))}\n"
        f"📞 Telefon: {_tg_escape(d.get('customer_phone',''))}\n"
        f"📆 Sana: {_tg_escape(d.get('date',''))} {_tg_escape(d.get('time',''))}\n"
        f"👥 Mehmonlar: {d.get('guests',2)} kishi\n"
        + (f"📝 Izoh: {_tg_escape(d.get('note',''))}" if d.get("note") else "")
    )
    return jsonify({"ok": True})


@bp.route("/api/reservations/<int:res_id>", methods=["PUT"])
def update_reservation(res_id):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d      = request.json or {}
    status = d.get("status")
    conn   = get_conn()
    try:
        db_exec(conn, "UPDATE reservations SET status=? WHERE id=?", (status, res_id))
        table_id = d.get("table_id")
        if status == "confirmed" and table_id:
            cur = db_exec(conn, "SELECT status FROM tables WHERE id=?", (table_id,))
            row = cur.fetchone()
            tbl_status = (row[0] if USE_PG else row["status"]) if row else None
            if tbl_status == "free":
                db_exec(conn, "UPDATE tables SET status='reserved' WHERE id=?", (table_id,))
                db_exec(conn, "UPDATE reservations SET table_id=? WHERE id=?", (table_id, res_id))
        elif status == "cancelled":
            cur2 = db_exec(conn, "SELECT table_id FROM reservations WHERE id=?", (res_id,))
            row2 = cur2.fetchone()
            if row2:
                tid = row2[0] if USE_PG else row2["table_id"]
                if tid:
                    db_exec(conn, "UPDATE tables SET status='free' WHERE id=? AND status='reserved'", (tid,))
        conn.commit()
    except Exception as _dbe:
        try: conn.rollback()
        except Exception: pass
        log.error("update_reservation DB xato: %s", _dbe)
        return jsonify({"error": "Server xatosi"}), 500
    finally:
        try: conn.close()
        except Exception: pass
    return jsonify({"ok": True})
