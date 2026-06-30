"""orders.py — orders + session oqimi (open/order/close/bill/void/discount/receipt)"""
import secrets, datetime, logging

from flask import Blueprint, request, jsonify
from database import get_conn, rows_to_list, USE_PG
from helpers import (
    check_auth, check_staff_pin, check_kitchen_auth,
    has_role, audit, _validate_str, _int_param,
    db_exec, get_db, limiter, tg_send, _tg_escape,
    _sse_broadcast, _calc_session_total,
    deduct_inventory, restore_inventory,
)

log = logging.getLogger(__name__)
bp = Blueprint('orders', __name__)


# ===== ESKI ORDERS (website) =====
@bp.route("/api/orders", methods=["GET"])
def get_orders():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    limit  = _int_param("limit", 200, max_val=1000)
    offset = _int_param("offset", 0, min_val=0)
    status = request.args.get("status")
    conn   = get_db()
    if status:
        cur = db_exec(conn,
            "SELECT * FROM orders WHERE status=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (status, limit, offset))
    else:
        cur = db_exec(conn,
            "SELECT * FROM orders ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset))
    result = rows_to_list(cur)
    return jsonify({"data": result, "limit": limit, "offset": offset, "count": len(result)})


@bp.route("/api/orders", methods=["POST"])
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
    conn = get_db()
    db_exec(conn,
        "INSERT INTO orders (item_name, item_id, quantity, total_price, customer_name, customer_phone, note) VALUES (?,?,?,?,?,?,?)",
        (d.get("item_name"), d.get("item_id"), d.get("quantity", 1),
         d.get("total_price"), d.get("customer_name"), d.get("customer_phone"), d.get("note"))
    )
    conn.commit()
    tg_send(
        f"🛒 <b>Yangi buyurtma!</b>\n"
        f"📌 Taom: {_tg_escape(d.get('item_name',''))} x{d.get('quantity',1)}\n"
        f"💰 Narx: {d.get('total_price',0):,} so'm\n"
        f"👤 Mijoz: {_tg_escape(d.get('customer_name',''))}\n"
        f"📞 Telefon: {_tg_escape(d.get('customer_phone',''))}\n"
        + (f"📝 Izoh: {_tg_escape(d.get('note',''))}" if d.get("note") else "")
    )
    return jsonify({"ok": True})


@bp.route("/api/orders/<int:order_id>", methods=["PUT"])
def update_order(order_id):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_db()
    db_exec(conn, "UPDATE orders SET status=? WHERE id=?", (d.get("status"), order_id))
    conn.commit()
    return jsonify({"ok": True})


# ===== SESSIYALAR =====
@bp.route("/api/session/open", methods=["POST"])
def open_session():
    d = request.json or {}
    staff = check_staff_pin(d.get("waiter_pin")) if d.get("waiter_pin") else None
    if not check_auth() and not staff:
        return jsonify({"error": "Ruxsat yo'q"}), 403
    if staff and not has_role(staff, "waiter", "cashier", "manager"):
        return jsonify({"error": "Faqat ofitsiant yoki kassir stol ocha oladi"}), 403
    if staff and not d.get("waiter_name"):
        d["waiter_name"] = staff["name"]
    table_id = d.get("table_id")
    conn = get_db()
    cur = db_exec(conn, "SELECT * FROM tables WHERE id=?", (table_id,))
    tbl = rows_to_list(cur)
    if not tbl: return jsonify({"error": "Stol topilmadi"}), 404
    tbl = tbl[0]
    if tbl["status"] != "free" and tbl.get("current_session_id"):
        return jsonify({"error": "Stol band", "session_id": tbl["current_session_id"]}), 409
    token = secrets.token_urlsafe(12)
    db_exec(conn, """INSERT INTO sessions (table_id, table_number, token, waiter_id, waiter_name, service_charge)
        VALUES (?,?,?,?,?,?)""",
        (table_id, tbl["number"], token, d.get("waiter_id"), d.get("waiter_name",""), d.get("service_charge", 0)))
    cur2 = db_exec(conn, "SELECT id FROM sessions WHERE token=?", (token,))
    row  = cur2.fetchone()
    sid  = row[0] if USE_PG else row["id"]
    db_exec(conn, "UPDATE tables SET status='occupied', current_session_id=? WHERE id=?", (sid, table_id))
    conn.commit()
    return jsonify({"ok": True, "token": token, "session_id": sid, "table_number": tbl["number"]})


@bp.route("/api/session/validate", methods=["GET"])
def validate_session():
    token = request.args.get("token")
    if not token: return jsonify({"valid": False}), 400
    conn = get_db()
    cur  = db_exec(conn, "SELECT * FROM sessions WHERE token=? AND status='active'", (token,))
    rows = rows_to_list(cur)
    if not rows: return jsonify({"valid": False, "error": "Token eskirgan yoki noto'g'ri"}), 404
    s = rows[0]
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


@bp.route("/api/session/<int:sid>", methods=["GET"])
def get_session(sid):
    token = request.headers.get("X-Session-Token","")
    conn  = get_db()
    cur   = db_exec(conn, "SELECT * FROM sessions WHERE id=?", (sid,))
    rows  = rows_to_list(cur)
    if not rows: return jsonify({"error": "Topilmadi"}), 404
    s = rows[0]
    if s["token"] != token and not check_auth():
        return jsonify({"error": "Ruxsat yo'q"}), 403
    cur2 = db_exec(conn, "SELECT * FROM order_items WHERE session_id=? ORDER BY created_at", (sid,))
    items = rows_to_list(cur2)
    cur3  = db_exec(conn, "SELECT * FROM payments WHERE session_id=?", (sid,))
    payments = rows_to_list(cur3)
    total = sum(i["total_price"] for i in items if i["status"] != "cancelled")
    sc    = total * s.get("service_charge", 0) / 100
    disc  = total * s.get("discount", 0) / 100
    return jsonify({**s, "items": items, "payments": payments,
                    "subtotal": total, "service_charge_amount": int(sc),
                    "discount_amount": int(disc), "grand_total": int(total + sc - disc)})


@bp.route("/api/session/<int:sid>/order", methods=["POST"])
def add_order_item(sid):
    token = request.headers.get("X-Session-Token","")
    conn  = get_db()
    cur   = db_exec(conn, "SELECT * FROM sessions WHERE id=? AND status='active'", (sid,))
    rows  = rows_to_list(cur)
    if not rows: return jsonify({"error": "Sessiya topilmadi yoki yopilgan"}), 404
    s = rows[0]
    body = request.json or {}
    staff = check_staff_pin(body.get("waiter_pin"), conn) if body.get("waiter_pin") else None
    if s["token"] != token and not check_auth() and not staff:
        return jsonify({"error": "Ruxsat yo'q"}), 403
    if staff and not has_role(staff, "waiter", "cashier", "manager"):
        return jsonify({"error": "Faqat ofitsiant yoki kassir buyurtma bera oladi"}), 403
    items = body.get("items", [])
    if not items: return jsonify({"error": "Buyurtma bo'sh"}), 400
    for item in items:
        try:
            _validate_str(item.get("name"), 100, "Taom nomi")
            _validate_str(item.get("comment"), 500, "Izoh")
        except ValueError as e:
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
    cur2 = db_exec(conn, "SELECT SUM(total_price) FROM order_items WHERE session_id=? AND status!='cancelled'", (sid,))
    row  = cur2.fetchone()
    total_sum = (row[0] or 0)
    db_exec(conn, "UPDATE sessions SET total_amount=? WHERE id=?", (total_sum, sid))
    conn.commit()
    names = ", ".join(f"{i.get('name')} x{i.get('quantity',1)}" for i in items)
    tg_send(f"🍽 <b>Stol #{s['table_number']} — Yangi buyurtma!</b>\n{names}")
    _sse_broadcast("new_order", {"session_id": sid, "table": s["table_number"], "items": names})
    return jsonify({"ok": True})


@bp.route("/api/session/<int:sid>/item/<int:iid>/status", methods=["PUT"])
def update_item_status(sid, iid):
    d    = request.json or {}
    status = d.get("status")
    valid  = ["pending","cooking","ready","served","cancelled"]
    if status not in valid: return jsonify({"error": "Noto'g'ri status"}), 400

    staff = check_staff_pin(d.get("pin")) if d.get("pin") else None
    is_authed = check_auth() or check_kitchen_auth() or (staff is not None)
    if not is_authed:
        return jsonify({"error": "Ruxsat yo'q — PIN yoki token kerak"}), 403

    if status == "cancelled" and not check_auth():
        return jsonify({"error": "Bekor qilish uchun admin ruxsati kerak"}), 403
    conn = get_db()
    pre_cur = db_exec(conn, "SELECT * FROM order_items WHERE id=? AND session_id=?", (iid, sid))
    pre_rows = rows_to_list(pre_cur)
    db_exec(conn, "UPDATE order_items SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=? AND session_id=?",
        (status, iid, sid))
    if status == "cooking" and pre_rows:
        item = pre_rows[0]
        if item["status"] == "pending":
            try:
                deduct_inventory(item["menu_item_id"], item["quantity"], conn,
                    f"Stol #{item['table_number']} — {item['item_name']}")
            except Exception as _inv_e:
                log.warning("deduct_inventory xato (item_id=%s): %s", item["menu_item_id"], _inv_e)
    if status == "ready" and pre_rows:
        item = pre_rows[0]
        tg_send(f"✅ <b>Stol #{item['table_number']} — Tayyor!</b>\n🍽 {item['item_name']}\nOfitsiant olib keling!")
        _sse_broadcast("item_ready", {"session_id": sid, "item_id": iid,
                                      "item_name": item["item_name"], "table": item.get("table_number")})
    elif status == "cooking" and pre_rows:
        _sse_broadcast("item_cooking", {"session_id": sid, "item_id": iid,
                                        "item_name": pre_rows[0]["item_name"]})
    conn.commit()
    return jsonify({"ok": True})


@bp.route("/api/session/<int:sid>/bill", methods=["POST"])
def request_bill(sid):
    token = request.headers.get("X-Session-Token","")
    conn  = get_db()
    cur   = db_exec(conn, "SELECT * FROM sessions WHERE id=? AND status='active'", (sid,))
    rows  = rows_to_list(cur)
    if not rows: return jsonify({"error": "Sessiya topilmadi"}), 404
    s = rows[0]
    if s["token"] != token and not check_auth():
        return jsonify({"error": "Ruxsat yo'q"}), 403
    db_exec(conn, "UPDATE tables SET status='bill_requested' WHERE number=?", (s["table_number"],))
    conn.commit()
    tg_send(f"🧾 <b>Stol #{s['table_number']} — Hisob so'radi!</b>\nJami: {s.get('total_amount',0):,} so'm")
    return jsonify({"ok": True})


@bp.route("/api/session/<int:sid>/close", methods=["POST"])
def close_session(sid):
    d    = request.json or {}
    staff = check_staff_pin(d.get("pin")) if d.get("pin") else None
    if not check_auth() and not staff:
        return jsonify({"error": "Ruxsat yo'q"}), 403
    if staff and not has_role(staff, "cashier", "manager"):
        return jsonify({"error": "Faqat kassir to'lov qabul qila oladi"}), 403
    conn = get_db()
    cur  = db_exec(conn, "SELECT * FROM sessions WHERE id=?", (sid,))
    rows = rows_to_list(cur)
    if not rows: return jsonify({"error": "Topilmadi"}), 404
    s = rows[0]

    server_total = _calc_session_total(sid, conn)
    payments     = d.get("payments", [])
    if not payments:
        return jsonify({"error": "To'lov ma'lumotlari yo'q"}), 400
    for p in payments:
        if int(p.get("amount", 0)) < 0:
            return jsonify({"error": "To'lov summasi manfi bo'lishi mumkin emas"}), 400
    client_total = sum(int(p.get("amount", 0)) for p in payments)

    if server_total > 0 and abs(server_total - client_total) > 500:
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
        log.error("close_session xato (sid=%s): %s", sid, e)
        return jsonify({"error": f"To'lov saqlanmadi: {e}"}), 500

    audit("payment", "session", sid, cashier_name,
          {"total": server_total, "table": s.get("table_number"), "methods": [p.get("method") for p in payments]})
    return jsonify({"ok": True, "total": server_total})


@bp.route("/api/session/<int:sid>/discount", methods=["PUT"])
def set_discount(sid):
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
    conn = get_db()
    try:
        db_exec(conn, "UPDATE sessions SET discount=?, service_charge=? WHERE id=?",
            (discount, service_charge, sid))
        conn.commit()
    except Exception as _dbe:
        try: conn.rollback()
        except Exception: pass
        log.error("set_discount DB xato: %s", _dbe)
        return jsonify({"error": "Server xatosi"}), 500
    return jsonify({"ok": True})


@bp.route("/api/session/<int:sid>/item/<int:iid>/void", methods=["POST"])
@limiter.limit("20 per minute")
def void_item(sid, iid):
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
    conn = get_db()
    cur = db_exec(conn, "SELECT * FROM order_items WHERE id=? AND session_id=?", (iid, sid))
    rows = rows_to_list(cur)
    if not rows:
        return jsonify({"error": "Item topilmadi"}), 404
    item = rows[0]
    if item["status"] == "cancelled":
        return jsonify({"error": "Item allaqachon bekor qilingan"}), 400
    db_exec(conn, """UPDATE order_items SET status='cancelled', void_by=?, void_reason=?,
        voided_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=? AND session_id=?""",
        (voider, reason, iid, sid))
    if item.get("status") in ("cooking", "ready", "served"):
        try:
            restore_inventory(item.get("menu_item_id"), item.get("quantity", 1), conn,
                              f"Void: {item.get('item_name')} — {reason}")
        except Exception as e:
            log.warning("restore_inventory xato: %s", e)
    cur2 = db_exec(conn, "SELECT COALESCE(SUM(total_price),0) FROM order_items WHERE session_id=? AND status!='cancelled'", (sid,))
    row2 = cur2.fetchone()
    new_total = int(row2[0] if USE_PG else (row2[0] or 0))
    db_exec(conn, "UPDATE sessions SET total_amount=? WHERE id=?", (new_total, sid))
    conn.commit()
    audit("void", "order_item", iid, voider,
          {"item": item.get("item_name"), "reason": reason, "session_id": sid})
    tg_send(f"🚫 <b>VOID</b> — Stol #{item.get('table_number')}\n"
            f"❌ {item.get('item_name')} x{item.get('quantity')}\n"
            f"📝 Sabab: {reason}\n👤 {voider}")
    return jsonify({"ok": True, "new_total": new_total})


@bp.route("/api/receipt/<int:sid>", methods=["GET"])
def get_receipt(sid):
    token = request.headers.get("X-Session-Token", "")
    pin   = request.headers.get("X-Staff-Pin", "") or request.args.get("pin", "")
    conn  = get_db()
    cur   = db_exec(conn, "SELECT * FROM sessions WHERE id=?", (sid,))
    sessions = rows_to_list(cur)
    if not sessions:
        return jsonify({"error": "Sessiya topilmadi"}), 404
    s = sessions[0]
    staff = check_staff_pin(pin, conn) if pin else None
    if s["token"] != token and not check_auth() and not staff:
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


@bp.route("/api/payments", methods=["GET"])
def get_payments():
    pin = request.headers.get("X-Staff-Pin", "") or request.args.get("pin", "")
    staff = check_staff_pin(pin) if pin else None
    if not check_auth() and not staff:
        return jsonify({"error": "Ruxsat yo'q"}), 403
    if staff and not has_role(staff, "cashier", "manager", "accountant"):
        return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_db()
    date = request.args.get("date")
    shift_id = request.args.get("shift_id")
    try:
        limit_n = _int_param("limit", 100, max_val=500)
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
    return jsonify(result)


@bp.route("/api/stats", methods=["GET"])
def get_stats():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_db()
    try:
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
            "orders_total": val("SELECT COUNT(*) FROM orders"),
            "orders_new":   val("SELECT COUNT(*) FROM orders WHERE status='new'"),
        }
    except Exception as _dbe:
        try: conn.rollback()
        except Exception: pass
        log.error("DB xato: %s", _dbe)
        return jsonify({"error": "Server xatosi"}), 500
    return jsonify(result)
