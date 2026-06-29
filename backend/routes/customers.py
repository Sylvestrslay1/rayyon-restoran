"""customers.py — customers + loyalty-card"""
import re, logging

from flask import Blueprint, request, jsonify
from database import rows_to_list
from helpers import (
    check_auth, db_exec, get_db, limiter,
)

log = logging.getLogger(__name__)
bp = Blueprint('customers', __name__)


@bp.route("/api/customers", methods=["GET"])
def get_customers():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_db()
    search = request.args.get("q", "")
    if search:
        cur = db_exec(conn, "SELECT * FROM customers WHERE phone LIKE ? OR name LIKE ? ORDER BY total_spent DESC",
                      (f"%{search}%", f"%{search}%"))
    else:
        cur = db_exec(conn, "SELECT * FROM customers ORDER BY total_spent DESC")
    result = rows_to_list(cur)
    return jsonify(result)


@bp.route("/api/customers/lookup", methods=["GET"])
@limiter.limit("30 per minute")
def lookup_customer():
    phone = request.args.get("phone", "").strip()
    if not phone: return jsonify({"found": False}), 200
    conn = get_db()
    cur = db_exec(conn, "SELECT * FROM customers WHERE phone=?", (phone,))
    rows = rows_to_list(cur)
    if rows:
        return jsonify({"found": True, "customer": rows[0]})
    return jsonify({"found": False})


@bp.route("/api/customers", methods=["POST"])
def add_customer():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    phone = (d.get("phone") or "").strip()
    if not phone:
        return jsonify({"error": "Telefon kiritilmadi"}), 400
    if not re.match(r"^\+?[\d\s\-\(\)]{7,20}$", phone):
        return jsonify({"error": "Telefon formati noto'g'ri"}), 400
    name = (d.get("name") or "").strip()
    if len(name) > 100:
        return jsonify({"error": "Ism 100 ta belgidan oshmasligi kerak"}), 400
    conn = get_db()
    try:
        db_exec(conn, "INSERT INTO customers (name, phone, discount_pct, notes) VALUES (?,?,?,?)",
                (d.get("name",""), phone, d.get("discount_pct", 0), d.get("notes","")))
        conn.commit()
    except Exception as e:
        err = str(e).lower()
        if "unique" in err or "duplicate" in err or "already exists" in err:
            return jsonify({"error": "Bu telefon allaqachon mavjud"}), 409
        log.error("add_customer DB xato: %s", e)
        return jsonify({"error": "Saqlashda xato yuz berdi"}), 500
    return jsonify({"ok": True})


@bp.route("/api/customers/<int:cid>", methods=["PUT"])
def update_customer(cid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_db()
    db_exec(conn, "UPDATE customers SET name=?, phone=?, discount_pct=?, notes=? WHERE id=?",
            (d.get("name",""), d.get("phone",""), d.get("discount_pct",0), d.get("notes",""), cid))
    conn.commit()
    return jsonify({"ok": True})


@bp.route("/api/customers/<int:cid>", methods=["DELETE"])
@limiter.limit("10 per minute")
def delete_customer(cid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_db()
    try:
        db_exec(conn, "DELETE FROM customers WHERE id=?", (cid,))
        conn.commit()
    except Exception as _dbe:
        try: conn.rollback()
        except Exception: pass
        log.error("DB xato: %s", _dbe)
        return jsonify({"error": "Server xatosi"}), 500
    return jsonify({"ok": True})


@bp.route("/api/loyalty-card/<int:cid>", methods=["GET"])
@limiter.limit("10 per minute; 30 per hour")
def loyalty_card(cid):
    conn = get_db()
    cur = db_exec(conn, "SELECT id,name,phone,total_spent,visits,loyalty_points,discount_pct FROM customers WHERE id=?", (cid,))
    rows = rows_to_list(cur)
    if not rows:
        return jsonify({"error": "Mijoz topilmadi"}), 404
    if not check_auth():
        phone_last4 = request.args.get("verify", "").strip()
        db_phone = str(rows[0].get("phone", ""))
        if not phone_last4 or not db_phone.endswith(phone_last4) or len(phone_last4) != 4:
            return jsonify({"error": "Tasdiqlash talab qilinadi"}), 403
    c = rows[0]
    pts = c.get("loyalty_points") or 0
    tier = ("Platinum" if pts >= 500 else "Gold" if pts >= 200 else "Silver" if pts >= 100 else "Bronze" if pts >= 1 else "Yangi")
    if pts < 1:    next_tier_pts = 1
    elif pts < 100: next_tier_pts = 100
    elif pts < 200: next_tier_pts = 200
    elif pts < 500: next_tier_pts = 500
    else:           next_tier_pts = pts
    return jsonify({
        "id": c["id"], "name": c["name"] or "Mijoz",
        "phone": str(c["phone"])[:4] + "****" + str(c["phone"])[-2:],
        "total_spent": c["total_spent"], "visits": c["visits"],
        "loyalty_points": pts, "discount_pct": c["discount_pct"],
        "tier": tier, "next_tier_pts": max(0, next_tier_pts - pts),
    })
