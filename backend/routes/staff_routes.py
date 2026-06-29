"""staff_routes.py — staff CRUD + checkin + attendance + payroll"""
import datetime, logging

from flask import Blueprint, request, jsonify
from database import get_conn, rows_to_list, USE_PG
from helpers import (
    check_auth, check_staff_pin, audit,
    _validate_str, _int_param,
    db_exec, get_db, limiter,
    hash_password,
)

log = logging.getLogger(__name__)
bp = Blueprint('staff_routes', __name__)


@bp.route("/api/staff", methods=["GET"])
def get_staff():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_db()
    cur  = db_exec(conn, "SELECT id,name,role,phone,salary_type,salary_amount,active FROM staff ORDER BY name")
    result = rows_to_list(cur)
    return jsonify(result)


@bp.route("/api/staff", methods=["POST"])
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
    conn = get_db()
    db_exec(conn, "INSERT INTO staff (name,role,pin,pin_salt,phone,salary_type,salary_amount) VALUES (?,?,?,?,?,?,?)",
        (d.get("name"), d.get("role"), pin_hash, pin_salt,
         d.get("phone"), d.get("salary_type","monthly"), d.get("salary_amount",0)))
    conn.commit()
    audit("staff_add", "staff", user_name="admin", details={"name": d.get("name"), "role": d.get("role")})
    return jsonify({"ok": True})


@bp.route("/api/staff/<int:sid>", methods=["PUT"])
def update_staff(sid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_db()
    if d.get("pin"):
        pin = str(d["pin"])
        if len(pin) < 4:
            return jsonify({"error": "PIN kamida 4 raqam bo'lishi kerak"}), 400
        pin_hash, pin_salt = hash_password(pin)
        db_exec(conn, "UPDATE staff SET name=?,role=?,pin=?,pin_salt=?,phone=?,salary_type=?,salary_amount=?,active=? WHERE id=?",
            (d.get("name"),d.get("role"),pin_hash,pin_salt,
             d.get("phone"),d.get("salary_type"),d.get("salary_amount"),d.get("active",1),sid))
    else:
        db_exec(conn, "UPDATE staff SET name=?,role=?,phone=?,salary_type=?,salary_amount=?,active=? WHERE id=?",
            (d.get("name"),d.get("role"),d.get("phone"),
             d.get("salary_type"),d.get("salary_amount"),d.get("active",1),sid))
    conn.commit()
    audit("staff_update", "staff", sid, "admin", {"name": d.get("name"), "role": d.get("role")})
    return jsonify({"ok": True})


@bp.route("/api/staff/<int:sid>", methods=["DELETE"])
@limiter.limit("10 per minute")
def delete_staff(sid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_db()
    try:
        db_exec(conn, "UPDATE staff SET active=0 WHERE id=?", (sid,))
        conn.commit()
    except Exception as _dbe:
        try: conn.rollback()
        except Exception: pass
        log.error("DB xato: %s", _dbe)
        return jsonify({"error": "Server xatosi"}), 500
    audit("staff_delete", "staff", sid, "admin")
    return jsonify({"ok": True})


@bp.route("/api/staff/checkin", methods=["POST"])
@limiter.limit("10 per minute")
def staff_checkin():
    d = request.json or {}
    pin = str(d.get("pin", ""))
    if not pin:
        return jsonify({"ok": False, "error": "PIN kiritilmadi"}), 400

    conn = get_db()
    staff = check_staff_pin(pin, conn)
    if not staff:
        return jsonify({"ok": False, "error": "PIN noto'g'ri"}), 401
    today = datetime.date.today().isoformat()
    cur2 = db_exec(conn, "SELECT * FROM attendance WHERE staff_id=? AND date=? AND check_out IS NULL", (staff["id"], today))
    existing = rows_to_list(cur2)
    try:
        if existing:
            att = existing[0]
            check_in = att["check_in"]
            if isinstance(check_in, str):
                check_in = datetime.datetime.fromisoformat(check_in)
            hours = (datetime.datetime.utcnow() - check_in.replace(tzinfo=None)).total_seconds() / 3600
            db_exec(conn, "UPDATE attendance SET check_out=CURRENT_TIMESTAMP, hours_worked=? WHERE id=?",
                (round(hours,2), att["id"]))
            conn.commit()
            return jsonify({"ok": True, "action": "checkout", "name": staff["name"], "hours": round(hours,2)})
        else:
            db_exec(conn, "INSERT INTO attendance (staff_id, staff_name, check_in, date) VALUES (?,?,CURRENT_TIMESTAMP,?)",
                (staff["id"], staff["name"], today))
            conn.commit()
            return jsonify({"ok": True, "action": "checkin", "name": staff["name"], "role": staff["role"]})
    except Exception as _dbe:
        try: conn.rollback()
        except Exception: pass
        log.error("staff_checkin DB xato: %s", _dbe)
        return jsonify({"ok": False, "error": "Server xatosi"}), 500


@bp.route("/api/attendance", methods=["GET"])
def get_attendance():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    limit  = _int_param("limit", 100, max_val=500)
    offset = _int_param("offset", 0, min_val=0)
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
    return jsonify({"data": result, "limit": limit, "offset": offset, "count": len(result)})


@bp.route("/api/staff/payroll", methods=["GET"])
def staff_payroll():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    month = request.args.get("month", datetime.datetime.utcnow().strftime("%Y-%m"))
    conn  = get_conn()
    cur   = db_exec(conn, "SELECT * FROM staff WHERE active=1 ORDER BY name")
    staff_list = rows_to_list(cur)
    result = []
    for s in staff_list:
        sid = s["id"]
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
    return jsonify(result)
