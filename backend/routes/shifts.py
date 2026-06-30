"""shifts.py — shift open/close/report/email"""
import time, datetime, logging

from flask import Blueprint, request, jsonify
from database import rows_to_list, USE_PG
from helpers import (
    check_auth, check_staff_pin, has_role,
    db_exec, get_db, limiter,
    tg_send, send_email,
    _int_param,
)

log = logging.getLogger(__name__)
bp = Blueprint('shifts', __name__)


@bp.route("/api/shift/open", methods=["POST"])
@limiter.limit("10 per minute")
def shift_open():
    d = request.json or {}
    staff = check_staff_pin(d.get("pin"))
    if not staff:
        time.sleep(0.3)
        return jsonify({"ok": False, "error": "PIN noto'g'ri"}), 401
    if staff["role"] not in ("cashier", "manager", "admin"):
        return jsonify({"ok": False, "error": "Faqat kassir yoki menejer smena ocha oladi"}), 403
    conn = get_db()
    cur = db_exec(conn, "SELECT * FROM shifts WHERE cashier_id=? AND status='open'", (staff["id"],))
    existing = rows_to_list(cur)
    if existing:
        return jsonify({"ok": True, "shift_id": existing[0]["id"],
                        "already_open": True, "cashier": staff["name"]})
    opening_cash = int(d.get("opening_cash") or 0)
    try:
        db_exec(conn, "INSERT INTO shifts (cashier_id, cashier_name, status, opening_cash) VALUES (?,?,?,?)",
                (staff["id"], staff["name"], "open", opening_cash))
        cur2 = db_exec(conn, "SELECT id FROM shifts WHERE cashier_id=? AND status='open' ORDER BY id DESC", (staff["id"],))
        row = cur2.fetchone()
        shift_id = row[0] if USE_PG else row["id"]
        conn.commit()
    except Exception as _dbe:
        try: conn.rollback()
        except Exception: pass
        log.error("shift_open DB xato: %s", _dbe)
        return jsonify({"ok": False, "error": "Server xatosi"}), 500
    tg_send(f"💼 <b>Smena ochildi</b>\n👤 Kassir: {staff['name']}\n🆔 Smena #{shift_id}")
    return jsonify({"ok": True, "shift_id": shift_id, "cashier": staff["name"]})


@bp.route("/api/shift/current", methods=["POST"])
@limiter.limit("30 per minute")
def shift_current():
    d = request.json or {}
    staff = check_staff_pin(d.get("pin"))
    if not staff:
        time.sleep(0.3)
        return jsonify({"ok": False, "error": "PIN noto'g'ri"}), 401
    conn = get_db()
    cur = db_exec(conn, "SELECT * FROM shifts WHERE cashier_id=? AND status='open' ORDER BY id DESC", (staff["id"],))
    shifts = rows_to_list(cur)
    if not shifts:
        return jsonify({"ok": True, "shift": None, "cashier": staff["name"], "role": staff["role"],
                        "cashier_id": staff["id"]})
    return jsonify({"ok": True, "shift": shifts[0], "cashier": staff["name"], "role": staff["role"],
                    "cashier_id": staff["id"]})


@bp.route("/api/shift/<int:shift_id>/close", methods=["POST"])
def shift_close(shift_id):
    d = request.json or {}
    staff = check_staff_pin(d.get("pin")) if d.get("pin") else None
    if not check_auth() and not staff:
        return jsonify({"ok": False, "error": "PIN yoki admin token kerak"}), 401
    if staff and not has_role(staff, "cashier", "manager"):
        return jsonify({"ok": False, "error": "Faqat kassir smena yopa oladi"}), 403
    cashier_id = staff["id"] if staff else None
    conn = get_db()
    if cashier_id:
        cur = db_exec(conn, "SELECT * FROM shifts WHERE id=? AND cashier_id=? AND status='open'",
                      (shift_id, cashier_id))
    else:
        cur = db_exec(conn, "SELECT * FROM shifts WHERE id=? AND status='open'", (shift_id,))
    shift_rows = rows_to_list(cur)
    if not shift_rows:
        return jsonify({"ok": False, "error": "Smena topilmadi yoki allaqachon yopilgan"}), 404

    force = d.get("force", False)
    active_cur = db_exec(conn, "SELECT COUNT(*) FROM sessions WHERE shift_id=? AND status='active'", (shift_id,))
    active_row = active_cur.fetchone()
    active_cnt = int(active_row[0] if USE_PG else (active_row[0] or 0))
    if active_cnt > 0 and not force:
        return jsonify({
            "ok": False,
            "error": f"{active_cnt} ta ochiq stol bor. Barchasini yoping yoki force=true yuboring.",
            "active_sessions": active_cnt
        }), 409

    cur2 = db_exec(conn,
        "SELECT COALESCE(SUM(amount),0) AS total, COUNT(DISTINCT session_id) AS sess FROM payments WHERE shift_id=?",
        (shift_id,))
    row2 = cur2.fetchone()
    total = int(row2[0] if USE_PG else (row2["total"] or 0))
    sess_cnt = int(row2[1] if USE_PG else (row2["sess"] or 0))

    meth_cur = db_exec(conn,
        "SELECT method, COALESCE(SUM(amount),0) AS s FROM payments WHERE shift_id=? GROUP BY method",
        (shift_id,))
    methods = rows_to_list(meth_cur)
    methods_summary = {r["method"]: int(r["s"]) for r in methods}

    shift_opened = shift_rows[0].get("opened_at") or shift_rows[0].get("created_at") or ""
    shift_date = str(shift_opened)[:10]
    exp_cur = db_exec(conn,
        "SELECT COALESCE(SUM(amount),0) FROM expenses WHERE date >= ?", (shift_date,))
    exp_row = exp_cur.fetchone()
    expenses = int(exp_row[0] if USE_PG else (exp_row[0] or 0)) if exp_row else 0
    net = total - expenses

    notes = d.get("notes", "")
    try:
        db_exec(conn,
            "UPDATE shifts SET status='closed', closed_at=CURRENT_TIMESTAMP, total_collected=?, sessions_count=?, notes=?, total_revenue=? WHERE id=?",
            (total, sess_cnt, notes, total, shift_id))
        conn.commit()
    except Exception as _dbe:
        try: conn.rollback()
        except Exception: pass
        log.error("shift_close DB xato: %s", _dbe)
        return jsonify({"ok": False, "error": "Server xatosi"}), 500

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


@bp.route("/api/shift/<int:shift_id>/report", methods=["POST"])
def shift_report(shift_id):
    d = request.json or {}
    staff = check_staff_pin(d.get("pin")) if d.get("pin") else None
    if not check_auth() and not staff:
        return jsonify({"error": "Ruxsat yo'q"}), 403
    if staff and not has_role(staff, "cashier", "manager", "accountant"):
        return jsonify({"error": "Faqat kassir, menejer yoki buxgalter hisobotni ko'ra oladi"}), 403
    conn = get_db()
    cur = db_exec(conn, "SELECT * FROM shifts WHERE id=?", (shift_id,))
    shifts = rows_to_list(cur)
    if not shifts:
        return jsonify({"error": "Smena topilmadi"}), 404
    shift = shifts[0]
    cur2 = db_exec(conn, "SELECT method, COALESCE(SUM(amount),0) AS total, COUNT(*) AS cnt FROM payments WHERE shift_id=? GROUP BY method", (shift_id,))
    by_method = rows_to_list(cur2)
    cur3 = db_exec(conn, """SELECT s.id, s.table_number, s.total_amount, s.opened_at, s.closed_at
        FROM sessions s
        JOIN payments p ON p.session_id = s.id
        WHERE p.shift_id=?
        GROUP BY s.id, s.table_number, s.total_amount, s.opened_at, s.closed_at
        ORDER BY s.closed_at""", (shift_id,))
    sessions_list = rows_to_list(cur3)
    return jsonify({**shift, "by_method": by_method, "sessions": sessions_list})


@bp.route("/api/shift/<int:shift_id>/email-report", methods=["POST"])
def email_shift_report(shift_id):
    if not check_auth():
        d = request.json or {}
        staff = check_staff_pin(d.get("pin")) if d.get("pin") else None
        if not staff or not has_role(staff, "cashier", "manager"):
            return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    to_email = d.get("email", "").strip()
    if not to_email or "@" not in to_email:
        return jsonify({"error": "Email manzil kiritilmadi"}), 400

    conn = get_db()
    cur = db_exec(conn, "SELECT * FROM shifts WHERE id=?", (shift_id,))
    rows = rows_to_list(cur)
    if not rows:
        return jsonify({"error": "Smena topilmadi"}), 404
    s = rows[0]

    cur2 = db_exec(conn, "SELECT method, COALESCE(SUM(amount),0) AS total FROM payments WHERE shift_id=? GROUP BY method", (shift_id,))
    methods = rows_to_list(cur2)
    cur3 = db_exec(conn, "SELECT COALESCE(SUM(amount),0) FROM payments WHERE shift_id=?", (shift_id,))
    total_pay = int((cur3.fetchone() or [0])[0] or 0)
    cur4 = db_exec(conn, "SELECT COUNT(DISTINCT session_id) FROM payments WHERE shift_id=?", (shift_id,))
    sess_cnt = int((cur4.fetchone() or [0])[0] or 0)

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


@bp.route("/api/shifts", methods=["GET"])
def get_shifts():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_db()
    limit_n = _int_param("limit", 100, max_val=500)
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
    return jsonify(result)
