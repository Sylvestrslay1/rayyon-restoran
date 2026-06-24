from flask import Flask, request, jsonify, send_from_directory, session
from flask_cors import CORS
import os, time, urllib.request, urllib.parse, json
from database import get_conn, init_db, rows_to_list, USE_PG
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "rayyon_secret_2024"
CORS(app, supports_credentials=True)

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
ALLOWED_EXT = {"png", "jpg", "jpeg", "gif", "webp"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

init_db()

TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT  = os.environ.get("TELEGRAM_CHAT_ID", "")


def tg_send(text):
    """Telegram guruhiga xabar yuborish"""
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
    except Exception:
        pass


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def q(sql):
    """? -> %s for PostgreSQL"""
    return sql.replace("?", "%s") if USE_PG else sql


def get_setting(key):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(q("SELECT value FROM settings WHERE key=?"), (key,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return row["value"] if not USE_PG else row[0]


def check_auth():
    return request.headers.get("X-Admin-Token", "").startswith("admin_")


def db_exec(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(q(sql), params)
    return cur


# ===== AUTH =====
@app.route("/api/login", methods=["POST"])
def login():
    data = request.json or {}
    correct = get_setting("admin_password")
    if data.get("password") == correct:
        return jsonify({"ok": True, "token": "admin_" + str(int(time.time()))})
    return jsonify({"ok": False}), 401


@app.route("/api/logout", methods=["POST"])
def logout():
    return jsonify({"ok": True})


# ===== MENU =====
@app.route("/api/menu", methods=["GET"])
def get_menu():
    conn = get_conn()
    category = request.args.get("category")
    if category and category != "all":
        cur = db_exec(conn, "SELECT * FROM menu WHERE category=? ORDER BY id", (category,))
    else:
        cur = db_exec(conn, "SELECT * FROM menu ORDER BY category, id")
    result = rows_to_list(cur)
    conn.close()
    return jsonify(result)


@app.route("/api/menu", methods=["POST"])
def add_menu():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    db_exec(conn,
        "INSERT INTO menu (name, category, description, price, emoji, available) VALUES (?,?,?,?,?,?)",
        (d.get("name"), d.get("category"), d.get("description"), d.get("price"), d.get("emoji", "🍽"), d.get("available", 1))
    )
    conn.commit(); conn.close()
    return jsonify({"ok": True})


@app.route("/api/menu/<int:item_id>", methods=["PUT"])
def update_menu(item_id):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    db_exec(conn,
        "UPDATE menu SET name=?, category=?, description=?, price=?, emoji=?, available=? WHERE id=?",
        (d.get("name"), d.get("category"), d.get("description"), d.get("price"), d.get("emoji", "🍽"), d.get("available", 1), item_id)
    )
    conn.commit(); conn.close()
    return jsonify({"ok": True})


@app.route("/api/menu/<int:item_id>", methods=["DELETE"])
def delete_menu(item_id):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    db_exec(conn, "DELETE FROM menu WHERE id=?", (item_id,))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


# ===== ORDERS =====
@app.route("/api/orders", methods=["GET"])
def get_orders():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    status = request.args.get("status")
    if status:
        cur = db_exec(conn, "SELECT * FROM orders WHERE status=? ORDER BY created_at DESC", (status,))
    else:
        cur = db_exec(conn, "SELECT * FROM orders ORDER BY created_at DESC")
    result = rows_to_list(cur)
    conn.close()
    return jsonify(result)


@app.route("/api/orders", methods=["POST"])
def add_order():
    d = request.json or {}
    conn = get_conn()
    db_exec(conn,
        "INSERT INTO orders (item_name, item_id, quantity, total_price, customer_name, customer_phone, note) VALUES (?,?,?,?,?,?,?)",
        (d.get("item_name"), d.get("item_id"), d.get("quantity", 1),
         d.get("total_price"), d.get("customer_name"), d.get("customer_phone"), d.get("note"))
    )
    conn.commit(); conn.close()
    tg_send(
        f"🛒 <b>Yangi buyurtma!</b>\n"
        f"📌 Taom: {d.get('item_name')} x{d.get('quantity',1)}\n"
        f"💰 Narx: {d.get('total_price',0):,} so'm\n"
        f"👤 Mijoz: {d.get('customer_name')}\n"
        f"📞 Telefon: {d.get('customer_phone')}\n"
        + (f"📝 Izoh: {d.get('note')}" if d.get("note") else "")
    )
    return jsonify({"ok": True})


@app.route("/api/orders/<int:order_id>", methods=["PUT"])
def update_order(order_id):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    db_exec(conn, "UPDATE orders SET status=? WHERE id=?", (d.get("status"), order_id))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


# ===== RESERVATIONS =====
@app.route("/api/reservations", methods=["GET"])
def get_reservations():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    cur = db_exec(conn, "SELECT * FROM reservations ORDER BY created_at DESC")
    result = rows_to_list(cur)
    conn.close()
    return jsonify(result)


@app.route("/api/reservations", methods=["POST"])
def add_reservation():
    d = request.json or {}
    conn = get_conn()
    db_exec(conn,
        "INSERT INTO reservations (customer_name, customer_phone, date, time, guests, note) VALUES (?,?,?,?,?,?)",
        (d.get("customer_name"), d.get("customer_phone"), d.get("date"), d.get("time"), d.get("guests", 2), d.get("note"))
    )
    conn.commit(); conn.close()
    tg_send(
        f"📅 <b>Yangi bron!</b>\n"
        f"👤 Mijoz: {d.get('customer_name')}\n"
        f"📞 Telefon: {d.get('customer_phone')}\n"
        f"📆 Sana: {d.get('date')} {d.get('time')}\n"
        f"👥 Mehmonlar: {d.get('guests',2)} kishi\n"
        + (f"📝 Izoh: {d.get('note')}" if d.get("note") else "")
    )
    return jsonify({"ok": True})


@app.route("/api/reservations/<int:res_id>", methods=["PUT"])
def update_reservation(res_id):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    db_exec(conn, "UPDATE reservations SET status=? WHERE id=?", (d.get("status"), res_id))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


# ===== NEWS =====
@app.route("/api/news", methods=["GET"])
def get_news():
    conn = get_conn()
    if request.args.get("active") == "1":
        cur = db_exec(conn, "SELECT * FROM news WHERE active=1 ORDER BY created_at DESC")
    else:
        cur = db_exec(conn, "SELECT * FROM news ORDER BY created_at DESC")
    result = rows_to_list(cur)
    conn.close()
    return jsonify(result)


@app.route("/api/news", methods=["POST"])
def add_news():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    db_exec(conn,
        "INSERT INTO news (title, content, image, active) VALUES (?,?,?,?)",
        (d.get("title"), d.get("content"), d.get("image"), d.get("active", 1))
    )
    conn.commit(); conn.close()
    return jsonify({"ok": True})


@app.route("/api/news/<int:news_id>", methods=["PUT"])
def update_news(news_id):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    db_exec(conn,
        "UPDATE news SET title=?, content=?, active=? WHERE id=?",
        (d.get("title"), d.get("content"), d.get("active", 1), news_id)
    )
    conn.commit(); conn.close()
    return jsonify({"ok": True})


@app.route("/api/news/<int:news_id>", methods=["DELETE"])
def delete_news(news_id):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    db_exec(conn, "DELETE FROM news WHERE id=?", (news_id,))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


# ===== IMAGE UPLOAD =====
@app.route("/api/upload", methods=["POST"])
def upload_image():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    if "file" not in request.files: return jsonify({"error": "Fayl topilmadi"}), 400
    file = request.files["file"]
    if file.filename == "" or not allowed_file(file.filename):
        return jsonify({"error": "Noto'g'ri fayl turi"}), 400
    filename = str(int(time.time())) + "_" + secure_filename(file.filename)
    file.save(os.path.join(UPLOAD_FOLDER, filename))
    return jsonify({"ok": True, "url": f"/uploads/{filename}"})


@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


# ===== SETTINGS =====
@app.route("/api/settings", methods=["GET"])
def get_settings():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    cur = db_exec(conn, "SELECT key, value FROM settings")
    rows = cur.fetchall()
    conn.close()
    if USE_PG:
        return jsonify({r[0]: r[1] for r in rows})
    return jsonify({r["key"]: r["value"] for r in rows})


@app.route("/api/settings", methods=["PUT"])
def update_settings():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    for key, val in d.items():
        if USE_PG:
            db_exec(conn, "INSERT INTO settings (key,value) VALUES (?,?) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value", (key, str(val)))
        else:
            db_exec(conn, "INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, str(val)))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


# ===== STATS =====
@app.route("/api/stats", methods=["GET"])
def get_stats():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()

    def val(sql):
        cur = db_exec(conn, sql)
        row = cur.fetchone()
        return row[0] if row else 0

    today_sql = "SELECT COUNT(*) FROM reservations WHERE date=CURRENT_DATE" if USE_PG else \
                "SELECT COUNT(*) FROM reservations WHERE date=date('now','localtime')"

    result = {
        "orders_total": val("SELECT COUNT(*) FROM orders"),
        "orders_new": val("SELECT COUNT(*) FROM orders WHERE status='new'"),
        "revenue": val("SELECT COALESCE(SUM(total_price),0) FROM orders WHERE status='done'"),
        "reservations_today": val(today_sql),
        "menu_count": val("SELECT COUNT(*) FROM menu WHERE available=1"),
    }
    conn.close()
    return jsonify(result)


# ===== GALEREYA =====
@app.route("/api/gallery", methods=["GET"])
def get_gallery():
    conn = get_conn()
    active = request.args.get("active")
    if active == "1":
        cur = db_exec(conn, "SELECT * FROM gallery WHERE active=1 ORDER BY sort_order, id")
    else:
        cur = db_exec(conn, "SELECT * FROM gallery ORDER BY sort_order, id")
    result = rows_to_list(cur)
    conn.close()
    return jsonify(result)

@app.route("/api/gallery", methods=["POST"])
def add_gallery():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    db_exec(conn, "INSERT INTO gallery (title, emoji, image, sort_order, active) VALUES (?,?,?,?,?)",
        (d.get("title"), d.get("emoji","🖼"), d.get("image"), d.get("sort_order",0), d.get("active",1)))
    conn.commit(); conn.close()
    return jsonify({"ok": True})

@app.route("/api/gallery/<int:gid>", methods=["PUT"])
def update_gallery(gid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    db_exec(conn, "UPDATE gallery SET title=?, emoji=?, image=?, sort_order=?, active=? WHERE id=?",
        (d.get("title"), d.get("emoji","🖼"), d.get("image"), d.get("sort_order",0), d.get("active",1), gid))
    conn.commit(); conn.close()
    return jsonify({"ok": True})

@app.route("/api/gallery/<int:gid>", methods=["DELETE"])
def delete_gallery(gid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    db_exec(conn, "DELETE FROM gallery WHERE id=?", (gid,))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


# ===== AKSIYALAR =====
@app.route("/api/promotions", methods=["GET"])
def get_promotions():
    conn = get_conn()
    active = request.args.get("active")
    if active == "1":
        cur = db_exec(conn, "SELECT * FROM promotions WHERE active=1 ORDER BY sort_order, id")
    else:
        cur = db_exec(conn, "SELECT * FROM promotions ORDER BY sort_order, id")
    result = rows_to_list(cur)
    conn.close()
    return jsonify(result)

@app.route("/api/promotions", methods=["POST"])
def add_promotion():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    db_exec(conn, "INSERT INTO promotions (title, description, badge, emoji, time_info, sort_order, active) VALUES (?,?,?,?,?,?,?)",
        (d.get("title"), d.get("description"), d.get("badge"), d.get("emoji","🎁"), d.get("time_info"), d.get("sort_order",0), d.get("active",1)))
    conn.commit(); conn.close()
    return jsonify({"ok": True})

@app.route("/api/promotions/<int:pid>", methods=["PUT"])
def update_promotion(pid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    db_exec(conn, "UPDATE promotions SET title=?, description=?, badge=?, emoji=?, time_info=?, sort_order=?, active=? WHERE id=?",
        (d.get("title"), d.get("description"), d.get("badge"), d.get("emoji","🎁"), d.get("time_info"), d.get("sort_order",0), d.get("active",1), pid))
    conn.commit(); conn.close()
    return jsonify({"ok": True})

@app.route("/api/promotions/<int:pid>", methods=["DELETE"])
def delete_promotion(pid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    db_exec(conn, "DELETE FROM promotions WHERE id=?", (pid,))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


# ===== BUXGALTERIYA: HISOBOTLAR =====
@app.route("/api/accounting/report", methods=["GET"])
def accounting_report():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    period = request.args.get("period", "daily")
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

    revenue   = val(f"SELECT COALESCE(SUM(total_price),0) FROM orders WHERE status='done' AND {date_filter}")
    orders_ct = val(f"SELECT COUNT(*) FROM orders WHERE {date_filter}")
    expenses  = val(f"SELECT COALESCE(SUM(amount),0) FROM expenses WHERE {exp_filter}")

    # Kunlik daromad grafigi (oxirgi 7 kun)
    if USE_PG:
        chart_sql = """
            SELECT date_trunc('day', created_at)::date::text AS day,
                   COALESCE(SUM(total_price),0) AS rev
            FROM orders WHERE status='done'
              AND created_at >= CURRENT_DATE - INTERVAL '6 days'
            GROUP BY 1 ORDER BY 1
        """
    else:
        chart_sql = """
            SELECT date(created_at,'localtime') AS day,
                   COALESCE(SUM(total_price),0) AS rev
            FROM orders WHERE status='done'
              AND date(created_at,'localtime') >= date('now','localtime','-6 days')
            GROUP BY 1 ORDER BY 1
        """
    cur2 = conn.cursor()
    cur2.execute(chart_sql)
    if USE_PG:
        chart = [{"day": r[0], "rev": r[1]} for r in cur2.fetchall()]
    else:
        chart = [{"day": r[0], "rev": r[1]} for r in cur2.fetchall()]

    # Kategoriya bo'yicha chiqimlar
    cur3 = conn.cursor()
    cur3.execute(f"SELECT category, COALESCE(SUM(amount),0) AS total FROM expenses WHERE {exp_filter} GROUP BY category ORDER BY total DESC")
    if USE_PG:
        exp_by_cat = [{"cat": r[0], "total": r[1]} for r in cur3.fetchall()]
    else:
        exp_by_cat = [{"cat": r[0], "total": r[1]} for r in cur3.fetchall()]

    conn.close()
    return jsonify({
        "revenue": revenue,
        "expenses": expenses,
        "profit": revenue - expenses,
        "orders": orders_ct,
        "chart": chart,
        "expenses_by_cat": exp_by_cat,
    })


@app.route("/api/expenses", methods=["GET"])
def get_expenses():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    cur  = db_exec(conn, "SELECT * FROM expenses ORDER BY date DESC, id DESC")
    result = rows_to_list(cur)
    conn.close()
    return jsonify(result)


@app.route("/api/expenses", methods=["POST"])
def add_expense():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    db_exec(conn,
        "INSERT INTO expenses (category, description, amount, date) VALUES (?,?,?,?)",
        (d.get("category"), d.get("description"), d.get("amount", 0), d.get("date"))
    )
    conn.commit(); conn.close()
    return jsonify({"ok": True})


@app.route("/api/expenses/<int:eid>", methods=["DELETE"])
def delete_expense(eid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    db_exec(conn, "DELETE FROM expenses WHERE id=?", (eid,))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


# ===== OMBOR =====
@app.route("/api/inventory", methods=["GET"])
def get_inventory():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    cur  = db_exec(conn, "SELECT * FROM inventory ORDER BY name")
    result = rows_to_list(cur)
    conn.close()
    return jsonify(result)


@app.route("/api/inventory", methods=["POST"])
def add_inventory():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    db_exec(conn,
        "INSERT INTO inventory (name, unit, quantity, min_quantity, price_per_unit) VALUES (?,?,?,?,?)",
        (d.get("name"), d.get("unit","kg"), d.get("quantity",0), d.get("min_quantity",0), d.get("price_per_unit",0))
    )
    conn.commit(); conn.close()
    return jsonify({"ok": True})


@app.route("/api/inventory/<int:iid>", methods=["PUT"])
def update_inventory(iid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d    = request.json or {}
    conn = get_conn()
    # Miqdor o'zgartirish va log yozish
    cur  = db_exec(conn, "SELECT name, quantity FROM inventory WHERE id=?", (iid,))
    row  = cur.fetchone()
    if row:
        old_name = row["name"] if not USE_PG else row[0]
        old_qty  = row["quantity"] if not USE_PG else row[1]
        new_qty  = d.get("quantity", old_qty)
        diff     = new_qty - old_qty
        move_type = "kirim" if diff > 0 else "chiqim"
        if diff != 0:
            db_exec(conn,
                "INSERT INTO inventory_log (item_id, item_name, type, quantity, note) VALUES (?,?,?,?,?)",
                (iid, old_name, move_type, abs(diff), d.get("note", ""))
            )
    db_exec(conn,
        "UPDATE inventory SET name=?, unit=?, quantity=?, min_quantity=?, price_per_unit=? WHERE id=?",
        (d.get("name"), d.get("unit","kg"), d.get("quantity",0), d.get("min_quantity",0), d.get("price_per_unit",0), iid)
    )
    conn.commit(); conn.close()
    return jsonify({"ok": True})


@app.route("/api/inventory/<int:iid>", methods=["DELETE"])
def delete_inventory(iid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    db_exec(conn, "DELETE FROM inventory WHERE id=?", (iid,))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


@app.route("/api/inventory/log", methods=["GET"])
def get_inventory_log():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    cur  = db_exec(conn, "SELECT * FROM inventory_log ORDER BY created_at DESC")
    result = rows_to_list(cur)
    conn.close()
    return jsonify(result)


# ===== STATIC FILES =====
@app.route("/")
def serve_site():
    base = os.path.join(os.path.dirname(__file__), "..")
    return send_from_directory(base, "index.html")


@app.route("/<path:path>")
def serve_static(path):
    base = os.path.join(os.path.dirname(__file__), "..")
    return send_from_directory(base, path)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV") != "production"
    print(f"✅ Rayyon backend ishga tushdi: http://localhost:{port}")
    app.run(host="0.0.0.0", debug=debug, port=port)
