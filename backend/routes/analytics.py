"""analytics.py — analytics + expenses + accounting + export + audit_log"""
import datetime, logging

from flask import Blueprint, request, jsonify
from database import get_conn, rows_to_list, USE_PG
from helpers import (
    check_auth, audit, _int_param,
    db_exec, get_db, limiter,
    _csv_response, ALLOWED_PERIODS,
)

log = logging.getLogger(__name__)
bp = Blueprint('analytics', __name__)


@bp.route("/api/analytics", methods=["GET"])
def analytics_alias():
    return analytics_summary()


@bp.route("/api/analytics/summary", methods=["GET"])
def analytics_summary():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
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

    pay_cur = conn.cursor()
    pay_cur.execute(f"SELECT method, COALESCE(SUM(amount),0) FROM payments WHERE {df2.replace('created_at','created_at')} GROUP BY method")
    pay_by_method = [{"method": r[0], "total": r[1]} for r in pay_cur.fetchall()]

    c2 = conn.cursor(); c2.execute(chart_sql)
    chart = [{"day": r[0], "rev": r[1]} for r in c2.fetchall()]

    c3 = conn.cursor(); c3.execute(top_sql)
    top_items = [{"name": r[0], "emoji": r[1], "count": r[2], "revenue": r[3]} for r in c3.fetchall()]

    c4 = conn.cursor(); c4.execute(staff_sql)
    staff_perf = [{"name": r[0], "sessions": r[1], "revenue": r[2]} for r in c4.fetchall()]

    c5 = conn.cursor(); c5.execute("SELECT name, quantity, min_quantity, unit FROM inventory WHERE quantity <= min_quantity ORDER BY quantity")
    low_stock = [{"name": r[0], "quantity": r[1], "min_quantity": r[2], "unit": r[3]} for r in c5.fetchall()]

    return jsonify({
        "revenue": revenue, "expenses": expenses, "profit": revenue - expenses,
        "sessions": sessions_ct, "items_sold": items_ct, "avg_bill": round(avg_bill),
        "chart": chart, "top_items": top_items, "staff_perf": staff_perf,
        "low_stock": low_stock, "pay_by_method": pay_by_method
    })


@bp.route("/api/accounting/report", methods=["GET"])
def accounting_report():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
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
    chart = [{"day": r[0], "rev": r[1]} for r in cur2.fetchall()]

    cur3 = conn.cursor()
    cur3.execute(f"SELECT category, COALESCE(SUM(amount),0) AS total FROM expenses WHERE {exp_filter} GROUP BY category ORDER BY total DESC")
    exp_by_cat = [{"cat": r[0], "total": r[1]} for r in cur3.fetchall()]

    return jsonify({
        "revenue": revenue,
        "expenses": expenses,
        "profit": revenue - expenses,
        "orders": orders_ct,
        "chart": chart,
        "expenses_by_cat": exp_by_cat,
    })


@bp.route("/api/expenses", methods=["GET"])
def get_expenses():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    limit     = _int_param("limit", 200, max_val=1000)
    offset    = _int_param("offset", 0, min_val=0)
    date_from = request.args.get("from")
    date_to   = request.args.get("to")
    conn = get_db()
    if date_from and date_to:
        cur = db_exec(conn,
            "SELECT * FROM expenses WHERE date>=? AND date<=? ORDER BY date DESC, id DESC LIMIT ? OFFSET ?",
            (date_from, date_to, limit, offset))
    else:
        cur = db_exec(conn,
            "SELECT * FROM expenses ORDER BY date DESC, id DESC LIMIT ? OFFSET ?",
            (limit, offset))
    result = rows_to_list(cur)
    return jsonify({"data": result, "limit": limit, "offset": offset, "count": len(result)})


@bp.route("/api/expenses", methods=["POST"])
def add_expense():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    from helpers import _validate_str
    try:
        _validate_str(d.get("category"),    50,  "Kategoriya")
        _validate_str(d.get("description"), 500, "Tavsif")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    raw_date = (d.get("date") or "").strip()
    try:
        import datetime as _dt
        exp_date = _dt.date.fromisoformat(raw_date).isoformat()
    except (ValueError, AttributeError):
        exp_date = datetime.date.today().isoformat()
    conn = get_db()
    db_exec(conn,
        "INSERT INTO expenses (category, description, amount, date) VALUES (?,?,?,?)",
        (d.get("category"), d.get("description"), int(d.get("amount", 0) or 0), exp_date)
    )
    conn.commit()
    audit("expense_add", "expense", user_name="admin",
          details={"category": d.get("category"), "amount": d.get("amount"), "date": d.get("date")})
    return jsonify({"ok": True})


@bp.route("/api/expenses/<int:eid>", methods=["DELETE"])
@limiter.limit("10 per minute")
def delete_expense(eid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_db()
    try:
        db_exec(conn, "DELETE FROM expenses WHERE id=?", (eid,))
        conn.commit()
    except Exception as _dbe:
        try: conn.rollback()
        except Exception: pass
        log.error("DB xato: %s", _dbe)
        return jsonify({"error": "Server xatosi"}), 500
    audit("expense_delete", "expense", eid, "admin")
    return jsonify({"ok": True})


@bp.route("/api/audit", methods=["GET"])
def get_audit_log():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    limit  = _int_param("limit", 100, max_val=500)
    offset = _int_param("offset", 0, min_val=0)
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
    return jsonify({"data": result, "limit": limit, "offset": offset, "count": len(result)})


# ===== CSV EKSPORT =====
@bp.route("/api/export/payments", methods=["GET"])
def export_payments():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    month = request.args.get("month", datetime.datetime.utcnow().strftime("%Y-%m"))
    conn  = get_conn()
    if USE_PG:
        cur = db_exec(conn, "SELECT * FROM payments WHERE to_char(created_at,'YYYY-MM')=%s ORDER BY created_at DESC", (month,))
    else:
        cur = db_exec(conn, "SELECT * FROM payments WHERE strftime('%Y-%m',created_at)=? ORDER BY created_at DESC", (month,))
    rows = rows_to_list(cur)
    return _csv_response(rows, f"payments_{month}.csv")


@bp.route("/api/export/sessions", methods=["GET"])
def export_sessions():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    month = request.args.get("month", datetime.datetime.utcnow().strftime("%Y-%m"))
    conn  = get_conn()
    if USE_PG:
        cur = db_exec(conn, "SELECT id,table_number,waiter_name,status,total_amount,discount,service_charge,opened_at,closed_at FROM sessions WHERE to_char(opened_at,'YYYY-MM')=%s ORDER BY opened_at DESC", (month,))
    else:
        cur = db_exec(conn, "SELECT id,table_number,waiter_name,status,total_amount,discount,service_charge,opened_at,closed_at FROM sessions WHERE strftime('%Y-%m',opened_at)=? ORDER BY opened_at DESC", (month,))
    rows = rows_to_list(cur)
    return _csv_response(rows, f"sessions_{month}.csv")


@bp.route("/api/export/staff", methods=["GET"])
def export_staff():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_db()
    cur  = db_exec(conn, "SELECT id,name,role,phone,salary_type,salary_amount,active,created_at FROM staff ORDER BY name")
    rows = rows_to_list(cur)
    return _csv_response(rows, "staff.csv")


@bp.route("/api/export/inventory", methods=["GET"])
def export_inventory():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_db()
    cur  = db_exec(conn, "SELECT * FROM inventory ORDER BY name")
    rows = rows_to_list(cur)
    return _csv_response(rows, "inventory.csv")


@bp.route("/api/export/orders", methods=["GET"])
def export_orders_csv():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    date_from = request.args.get("from")
    date_to   = request.args.get("to")
    conn = get_db()
    if date_from and date_to:
        cur = db_exec(conn,
            "SELECT * FROM orders WHERE created_at>=? AND created_at<=? ORDER BY created_at DESC",
            (date_from, date_to + " 23:59:59"))
    else:
        cur = db_exec(conn, "SELECT * FROM orders ORDER BY created_at DESC")
    rows = rows_to_list(cur)
    return _csv_response(rows, "orders.csv")


@bp.route("/api/export/expenses", methods=["GET"])
def export_expenses_csv():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    date_from = request.args.get("from")
    date_to   = request.args.get("to")
    conn = get_db()
    if date_from and date_to:
        cur = db_exec(conn,
            "SELECT * FROM expenses WHERE date>=? AND date<=? ORDER BY date DESC",
            (date_from, date_to))
    else:
        cur = db_exec(conn, "SELECT * FROM expenses ORDER BY date DESC")
    rows = rows_to_list(cur)
    return _csv_response(rows, "expenses.csv")


@bp.route("/api/export/attendance", methods=["GET"])
def export_attendance_csv():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    date_from = request.args.get("from")
    date_to   = request.args.get("to")
    conn = get_db()
    if date_from and date_to:
        cur = db_exec(conn,
            "SELECT * FROM attendance WHERE date>=? AND date<=? ORDER BY date DESC",
            (date_from, date_to))
    else:
        cur = db_exec(conn, "SELECT * FROM attendance ORDER BY check_in DESC")
    rows = rows_to_list(cur)
    return _csv_response(rows, "attendance.csv")


@bp.route("/api/export/audit", methods=["GET"])
def export_audit_csv():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_db()
    cur  = db_exec(conn, "SELECT * FROM audit_log ORDER BY created_at DESC")
    rows = rows_to_list(cur)
    return _csv_response(rows, "audit_log.csv")
