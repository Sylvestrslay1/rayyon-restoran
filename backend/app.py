from flask import Flask, request, jsonify, send_from_directory, session
from flask_cors import CORS
import os, time, urllib.request, urllib.parse, json, secrets, hashlib
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


def check_staff_pin(pin, conn=None):
    """PIN to'g'ri staff (waiter/cashier) ga tegishli ekanligini tekshiradi"""
    if not pin: return None
    h = hashlib.sha256(str(pin).encode()).hexdigest()
    close = conn is None
    if close: conn = get_conn()
    cur = db_exec(conn, "SELECT * FROM staff WHERE pin=? AND active=1", (h,))
    rows = rows_to_list(cur)
    if close: conn.close()
    return rows[0] if rows else None


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


# ===== STOLLAR =====
@app.route("/api/tables", methods=["GET"])
def get_tables():
    conn = get_conn()
    cur  = db_exec(conn, """
        SELECT t.*, s.opened_at, s.total_amount, s.token, s.waiter_name
        FROM tables t
        LEFT JOIN sessions s ON t.current_session_id = s.id
        ORDER BY t.number
    """)
    tables = rows_to_list(cur)
    conn.close()
    # Har bir stol uchun ochiq vaqtni hisoblash
    for tbl in tables:
        if tbl.get("opened_at"):
            import datetime
            opened = tbl["opened_at"]
            if isinstance(opened, str):
                try: opened = datetime.datetime.fromisoformat(opened.replace("Z",""))
                except: opened = None
            if opened:
                diff = datetime.datetime.utcnow() - opened.replace(tzinfo=None)
                tbl["minutes_open"] = int(diff.total_seconds() // 60)
    return jsonify(tables)

@app.route("/api/tables", methods=["POST"])
def add_table():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    db_exec(conn, "INSERT INTO tables (number, name, capacity) VALUES (?,?,?)",
        (d.get("number"), d.get("name", f"Stol {d.get('number')}"), d.get("capacity", 4)))
    conn.commit(); conn.close()
    return jsonify({"ok": True})

@app.route("/api/tables/<int:tid>", methods=["PUT"])
def update_table(tid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    db_exec(conn, "UPDATE tables SET number=?, name=?, capacity=? WHERE id=?",
        (d.get("number"), d.get("name"), d.get("capacity", 4), tid))
    conn.commit(); conn.close()
    return jsonify({"ok": True})

@app.route("/api/tables/<int:tid>", methods=["DELETE"])
def delete_table(tid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    db_exec(conn, "DELETE FROM tables WHERE id=?", (tid,))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


# ===== SESSIYALAR =====
@app.route("/api/session/open", methods=["POST"])
def open_session():
    """Stol ochish — kassir yoki ofitsiant tomonidan"""
    d = request.json or {}
    staff = check_staff_pin(d.get("waiter_pin")) if d.get("waiter_pin") else None
    if not check_auth() and not staff:
        return jsonify({"error": "Ruxsat yo'q"}), 403
    if staff and not d.get("waiter_name"):
        d["waiter_name"] = staff["name"]
    table_id = d.get("table_id")
    conn = get_conn()
    # Stol mavjudligini tekshirish
    cur = db_exec(conn, "SELECT * FROM tables WHERE id=?", (table_id,))
    tbl = rows_to_list(cur)
    if not tbl: conn.close(); return jsonify({"error": "Stol topilmadi"}), 404
    tbl = tbl[0]
    if tbl["status"] != "free" and tbl.get("current_session_id"):
        conn.close()
        return jsonify({"error": "Stol band", "session_id": tbl["current_session_id"]}), 409
    # Noyob token yaratish
    token = secrets.token_urlsafe(12)
    db_exec(conn, """INSERT INTO sessions (table_id, table_number, token, waiter_id, waiter_name, service_charge)
        VALUES (?,?,?,?,?,?)""",
        (table_id, tbl["number"], token, d.get("waiter_id"), d.get("waiter_name",""), d.get("service_charge", 0)))
    # session id olish
    cur2 = db_exec(conn, "SELECT id FROM sessions WHERE token=?", (token,))
    row  = cur2.fetchone()
    sid  = row[0] if USE_PG else row["id"]
    db_exec(conn, "UPDATE tables SET status='occupied', current_session_id=? WHERE id=?", (sid, table_id))
    conn.commit(); conn.close()
    return jsonify({"ok": True, "token": token, "session_id": sid, "table_number": tbl["number"]})

@app.route("/api/session/validate", methods=["GET"])
def validate_session():
    """QR token tekshirish"""
    token = request.args.get("token")
    if not token: return jsonify({"valid": False}), 400
    conn = get_conn()
    cur  = db_exec(conn, "SELECT * FROM sessions WHERE token=? AND status='active'", (token,))
    rows = rows_to_list(cur)
    conn.close()
    if not rows: return jsonify({"valid": False, "error": "Token eskirgan yoki noto'g'ri"}), 404
    s = rows[0]
    return jsonify({"valid": True, "table_number": s["table_number"], "session_id": s["id"]})

@app.route("/api/session/<int:sid>", methods=["GET"])
def get_session(sid):
    """Sessiya ma'lumotlari va barcha buyurtmalar"""
    token = request.headers.get("X-Session-Token","")
    conn  = get_conn()
    cur   = db_exec(conn, "SELECT * FROM sessions WHERE id=?", (sid,))
    rows  = rows_to_list(cur)
    if not rows: conn.close(); return jsonify({"error": "Topilmadi"}), 404
    s = rows[0]
    # Token yoki admin tekshirish
    if s["token"] != token and not check_auth():
        conn.close(); return jsonify({"error": "Ruxsat yo'q"}), 403
    cur2 = db_exec(conn, "SELECT * FROM order_items WHERE session_id=? ORDER BY created_at", (sid,))
    items = rows_to_list(cur2)
    cur3  = db_exec(conn, "SELECT * FROM payments WHERE session_id=?", (sid,))
    payments = rows_to_list(cur3)
    conn.close()
    total = sum(i["total_price"] for i in items if i["status"] != "cancelled")
    sc    = total * s.get("service_charge", 0) / 100
    disc  = total * s.get("discount", 0) / 100
    return jsonify({**s, "items": items, "payments": payments,
                    "subtotal": total, "service_charge_amount": int(sc),
                    "discount_amount": int(disc), "grand_total": int(total + sc - disc)})

@app.route("/api/session/<int:sid>/order", methods=["POST"])
def add_order_item(sid):
    """Sessiyaga buyurtma qo'shish"""
    token = request.headers.get("X-Session-Token","")
    conn  = get_conn()
    cur   = db_exec(conn, "SELECT * FROM sessions WHERE id=? AND status='active'", (sid,))
    rows  = rows_to_list(cur)
    if not rows: conn.close(); return jsonify({"error": "Sessiya topilmadi yoki yopilgan"}), 404
    s = rows[0]
    body = request.json or {}
    staff = check_staff_pin(body.get("waiter_pin"), conn) if body.get("waiter_pin") else None
    if s["token"] != token and not check_auth() and not staff:
        conn.close(); return jsonify({"error": "Ruxsat yo'q"}), 403
    items = body.get("items", [])
    if not items: conn.close(); return jsonify({"error": "Buyurtma bo'sh"}), 400
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
    # Umumiy summani yangilash
    cur2 = db_exec(conn, "SELECT SUM(total_price) FROM order_items WHERE session_id=? AND status!='cancelled'", (sid,))
    row  = cur2.fetchone()
    total_sum = (row[0] or 0)
    db_exec(conn, "UPDATE sessions SET total_amount=? WHERE id=?", (total_sum, sid))
    conn.commit(); conn.close()
    # Telegram xabarnomasi
    names = ", ".join(f"{i.get('name')} x{i.get('quantity',1)}" for i in items)
    tg_send(f"🍽 <b>Stol #{s['table_number']} — Yangi buyurtma!</b>\n{names}")
    return jsonify({"ok": True})

@app.route("/api/session/<int:sid>/item/<int:iid>/status", methods=["PUT"])
def update_item_status(sid, iid):
    """Buyurtma item statusini o'zgartirish (oshxona/ofitsiant)"""
    d    = request.json or {}
    status = d.get("status")
    valid  = ["pending","cooking","ready","served","cancelled"]
    if status not in valid: return jsonify({"error": "Noto'g'ri status"}), 400
    # Cancel uchun admin token kerak
    if status == "cancelled" and not check_auth():
        return jsonify({"error": "Bekor qilish uchun admin ruxsati kerak"}), 403
    conn = get_conn()
    # Oldingi item ma'lumotlarini olib qo'yish (deduct uchun)
    pre_cur = db_exec(conn, "SELECT * FROM order_items WHERE id=? AND session_id=?", (iid, sid))
    pre_rows = rows_to_list(pre_cur)
    db_exec(conn, "UPDATE order_items SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=? AND session_id=?",
        (status, iid, sid))
    # Agar tayyorlash boshlansa → ombordan chiqarish
    if status == "cooking" and pre_rows:
        item = pre_rows[0]
        if item["status"] == "pending":  # faqat bir marta chiqarish
            try:
                deduct_inventory(item["menu_item_id"], item["quantity"], conn,
                    f"Stol #{item['table_number']} — {item['item_name']}")
            except Exception:
                pass  # ombor moduli bo'lmasa ham ishlaydi
    # Agar tayyor bo'lsa → Telegram ga xabar
    if status == "ready" and pre_rows:
        item = pre_rows[0]
        tg_send(f"✅ <b>Stol #{item['table_number']} — Tayyor!</b>\n🍽 {item['item_name']}\nOfitsiant olib keling!")
    conn.commit(); conn.close()
    return jsonify({"ok": True})

@app.route("/api/session/<int:sid>/bill", methods=["POST"])
def request_bill(sid):
    """Mijoz hisob so'radi"""
    token = request.headers.get("X-Session-Token","")
    conn  = get_conn()
    cur   = db_exec(conn, "SELECT * FROM sessions WHERE id=? AND status='active'", (sid,))
    rows  = rows_to_list(cur)
    if not rows: conn.close(); return jsonify({"error": "Sessiya topilmadi"}), 404
    s = rows[0]
    if s["token"] != token and not check_auth():
        conn.close(); return jsonify({"error": "Ruxsat yo'q"}), 403
    db_exec(conn, "UPDATE tables SET status='bill_requested' WHERE number=?", (s["table_number"],))
    conn.commit(); conn.close()
    tg_send(f"🧾 <b>Stol #{s['table_number']} — Hisob so'radi!</b>\nJami: {s.get('total_amount',0):,} so'm")
    return jsonify({"ok": True})

@app.route("/api/session/<int:sid>/close", methods=["POST"])
def close_session(sid):
    """Sessiyani yopish va to'lovni qayd etish"""
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d    = request.json or {}
    conn = get_conn()
    cur  = db_exec(conn, "SELECT * FROM sessions WHERE id=?", (sid,))
    rows = rows_to_list(cur)
    if not rows: conn.close(); return jsonify({"error": "Topilmadi"}), 404
    s = rows[0]
    # To'lovlarni qayd etish
    payments = d.get("payments", [])
    for p in payments:
        db_exec(conn, "INSERT INTO payments (session_id, table_number, amount, method, notes) VALUES (?,?,?,?,?)",
            (sid, s["table_number"], p.get("amount",0), p.get("method","cash"), p.get("notes","")))
    # Sessiyani yopish
    db_exec(conn, "UPDATE sessions SET status='completed', closed_at=CURRENT_TIMESTAMP WHERE id=?", (sid,))
    db_exec(conn, "UPDATE tables SET status='free', current_session_id=NULL WHERE id=?", (s["table_id"],))
    conn.commit(); conn.close()
    return jsonify({"ok": True})

@app.route("/api/session/<int:sid>/discount", methods=["PUT"])
def set_discount(sid):
    """Chegirma yoki xizmat haqi o'rnatish"""
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    db_exec(conn, "UPDATE sessions SET discount=?, service_charge=? WHERE id=?",
        (d.get("discount",0), d.get("service_charge",0), sid))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


# ===== OSHXONA (KDS) =====
@app.route("/api/kitchen", methods=["GET"])
def kitchen_orders():
    """Oshxona ekrani uchun — faqat pending va cooking itemlar"""
    conn = get_conn()
    category = request.args.get("category")
    if category:
        cur = db_exec(conn, """SELECT oi.*, s.table_number
            FROM order_items oi JOIN sessions s ON oi.session_id=s.id
            WHERE oi.status IN ('pending','cooking') AND oi.category=?
            ORDER BY oi.course, oi.created_at""", (category,))
    else:
        cur = db_exec(conn, """SELECT oi.*, s.table_number as tnum
            FROM order_items oi JOIN sessions s ON oi.session_id=s.id
            WHERE oi.status IN ('pending','cooking')
            ORDER BY oi.course, oi.created_at""")
    items = rows_to_list(cur)
    conn.close()
    # Stol bo'yicha guruhlash
    grouped = {}
    for item in items:
        tbl = str(item.get("table_number") or item.get("tnum") or "?")
        if tbl not in grouped:
            grouped[tbl] = {"table": tbl, "session_id": item["session_id"], "items": []}
        grouped[tbl]["items"].append(item)
    return jsonify(list(grouped.values()))

@app.route("/api/kitchen/ready", methods=["GET"])
def kitchen_ready():
    """Tayyor bo'lgan buyurtmalar — ofitsiant olishi kerak"""
    conn = get_conn()
    cur  = db_exec(conn, """SELECT oi.* FROM order_items oi
        WHERE oi.status='ready' ORDER BY oi.updated_at""")
    items = rows_to_list(cur)
    conn.close()
    return jsonify(items)


# ===== XODIMLAR =====
@app.route("/api/staff", methods=["GET"])
def get_staff():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    cur  = db_exec(conn, "SELECT id,name,role,phone,salary_type,salary_amount,active FROM staff ORDER BY name")
    result = rows_to_list(cur)
    conn.close()
    return jsonify(result)

@app.route("/api/staff", methods=["POST"])
def add_staff():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    pin_hash = hashlib.sha256(str(d.get("pin","0000")).encode()).hexdigest()[:8] if d.get("pin") else None
    conn = get_conn()
    db_exec(conn, "INSERT INTO staff (name,role,pin,phone,salary_type,salary_amount) VALUES (?,?,?,?,?,?)",
        (d.get("name"), d.get("role"), pin_hash, d.get("phone"), d.get("salary_type","monthly"), d.get("salary_amount",0)))
    conn.commit(); conn.close()
    return jsonify({"ok": True})

@app.route("/api/staff/<int:sid>", methods=["PUT"])
def update_staff(sid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    if d.get("pin"):
        pin_hash = hashlib.sha256(str(d["pin"]).encode()).hexdigest()[:8]
        db_exec(conn, "UPDATE staff SET name=?,role=?,pin=?,phone=?,salary_type=?,salary_amount=?,active=? WHERE id=?",
            (d.get("name"),d.get("role"),pin_hash,d.get("phone"),d.get("salary_type"),d.get("salary_amount"),d.get("active",1),sid))
    else:
        db_exec(conn, "UPDATE staff SET name=?,role=?,phone=?,salary_type=?,salary_amount=?,active=? WHERE id=?",
            (d.get("name"),d.get("role"),d.get("phone"),d.get("salary_type"),d.get("salary_amount"),d.get("active",1),sid))
    conn.commit(); conn.close()
    return jsonify({"ok": True})

@app.route("/api/staff/<int:sid>", methods=["DELETE"])
def delete_staff(sid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    db_exec(conn, "UPDATE staff SET active=0 WHERE id=?", (sid,))
    conn.commit(); conn.close()
    return jsonify({"ok": True})

@app.route("/api/staff/checkin", methods=["POST"])
def staff_checkin():
    """PIN bilan kirish"""
    d = request.json or {}
    pin_hash = hashlib.sha256(str(d.get("pin","")).encode()).hexdigest()[:8]
    conn = get_conn()
    cur  = db_exec(conn, "SELECT * FROM staff WHERE pin=? AND active=1", (pin_hash,))
    rows = rows_to_list(cur)
    if not rows: conn.close(); return jsonify({"ok": False, "error": "PIN noto'g'ri"}), 401
    staff = rows[0]
    import datetime
    today = datetime.date.today().isoformat()
    # Bugun allaqachon kirganmi?
    cur2 = db_exec(conn, "SELECT * FROM attendance WHERE staff_id=? AND date=? AND check_out IS NULL", (staff["id"], today))
    existing = rows_to_list(cur2)
    if existing:
        # Check-out
        att = existing[0]
        check_in = att["check_in"]
        if isinstance(check_in, str):
            check_in = datetime.datetime.fromisoformat(check_in)
        hours = (datetime.datetime.utcnow() - check_in.replace(tzinfo=None)).total_seconds() / 3600
        db_exec(conn, "UPDATE attendance SET check_out=CURRENT_TIMESTAMP, hours_worked=? WHERE id=?",
            (round(hours,2), att["id"]))
        conn.commit(); conn.close()
        return jsonify({"ok": True, "action": "checkout", "name": staff["name"], "hours": round(hours,2)})
    else:
        # Check-in
        db_exec(conn, "INSERT INTO attendance (staff_id, staff_name, check_in, date) VALUES (?,?,CURRENT_TIMESTAMP,?)",
            (staff["id"], staff["name"], today))
        conn.commit(); conn.close()
        return jsonify({"ok": True, "action": "checkin", "name": staff["name"], "role": staff["role"]})

@app.route("/api/attendance", methods=["GET"])
def get_attendance():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    date = request.args.get("date")
    conn = get_conn()
    if date:
        cur = db_exec(conn, "SELECT * FROM attendance WHERE date=? ORDER BY check_in DESC", (date,))
    else:
        cur = db_exec(conn, "SELECT * FROM attendance ORDER BY check_in DESC")
    result = rows_to_list(cur)
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


# ===== RETSEPTLAR =====
@app.route("/api/recipes", methods=["GET"])
def get_recipes():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    menu_item_id = request.args.get("menu_item_id")
    conn = get_conn()
    if menu_item_id:
        cur = db_exec(conn, """
            SELECT r.*, i.name AS inv_name, i.unit AS inv_unit, i.quantity AS inv_qty
            FROM recipes r
            JOIN inventory i ON r.inventory_id = i.id
            WHERE r.menu_item_id=?
        """, (menu_item_id,))
    else:
        cur = db_exec(conn, """
            SELECT r.*, i.name AS inv_name, i.unit AS inv_unit, i.quantity AS inv_qty,
                   m.name AS menu_name
            FROM recipes r
            JOIN inventory i ON r.inventory_id = i.id
            JOIN menu m ON r.menu_item_id = m.id
            ORDER BY m.name
        """)
    result = rows_to_list(cur)
    conn.close()
    return jsonify(result)


@app.route("/api/recipes", methods=["POST"])
def add_recipe():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    # Eski o'chirib yangi kiritish (upsert)
    db_exec(conn, "DELETE FROM recipes WHERE menu_item_id=? AND inventory_id=?",
            (d.get("menu_item_id"), d.get("inventory_id")))
    db_exec(conn,
        "INSERT INTO recipes (menu_item_id, inventory_id, quantity, unit) VALUES (?,?,?,?)",
        (d.get("menu_item_id"), d.get("inventory_id"), d.get("quantity", 0), d.get("unit", "g"))
    )
    conn.commit(); conn.close()
    return jsonify({"ok": True})


@app.route("/api/recipes/<int:rid>", methods=["DELETE"])
def delete_recipe(rid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    db_exec(conn, "DELETE FROM recipes WHERE id=?", (rid,))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


def deduct_inventory(menu_item_id, quantity, conn, note=""):
    """Retsept bo'yicha ombordan avtomatik hisobdan chiqarish"""
    cur = db_exec(conn, "SELECT * FROM recipes WHERE menu_item_id=?", (menu_item_id,))
    recipes = rows_to_list(cur)
    for r in recipes:
        needed = r["quantity"] * quantity
        # Unit konvertatsiya: g→kg, ml→l
        if r["unit"] == "g":
            needed_kg = needed / 1000.0
            db_exec(conn,
                "UPDATE inventory SET quantity = MAX(0, quantity - ?) WHERE id=? AND unit='kg'",
                (needed_kg, r["inventory_id"]))
            db_exec(conn, "UPDATE inventory SET quantity = MAX(0, quantity - ?) WHERE id=? AND unit='g'",
                (needed, r["inventory_id"]))
        elif r["unit"] == "ml":
            needed_l = needed / 1000.0
            db_exec(conn,
                "UPDATE inventory SET quantity = MAX(0, quantity - ?) WHERE id=? AND unit='l'",
                (needed_l, r["inventory_id"]))
            db_exec(conn, "UPDATE inventory SET quantity = MAX(0, quantity - ?) WHERE id=? AND unit='ml'",
                (needed, r["inventory_id"]))
        else:
            db_exec(conn, "UPDATE inventory SET quantity = MAX(0, quantity - ?) WHERE id=?",
                (needed, r["inventory_id"]))
        # Log
        inv_cur = db_exec(conn, "SELECT name FROM inventory WHERE id=?", (r["inventory_id"],))
        inv_row = inv_cur.fetchone()
        inv_name = inv_row[0] if USE_PG else (inv_row["name"] if inv_row else "?")
        db_exec(conn,
            "INSERT INTO inventory_log (item_id, item_name, type, quantity, note) VALUES (?,?,?,?,?)",
            (r["inventory_id"], inv_name, "expense", needed, note or "Auto chiqim"))


# ===== STOP-LIST =====
@app.route("/api/menu/<int:item_id>/stoplist", methods=["PUT"])
def toggle_stoplist(item_id):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    db_exec(conn, "UPDATE menu SET available=? WHERE id=?",
            (0 if d.get("stop") else 1, item_id))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


# ===== KENGAYTIRILGAN HISOBOTLAR =====
@app.route("/api/analytics/summary", methods=["GET"])
def analytics_summary():
    """Sessiyalar asosida to'liq hisobot"""
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    period = request.args.get("period", "daily")
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

    # Payment usullari
    pay_cur = conn.cursor()
    pay_cur.execute(f"SELECT method, COALESCE(SUM(amount),0) FROM payments WHERE {df2.replace('created_at','created_at')} GROUP BY method")
    pay_by_method = [{"method": r[0], "total": r[1]} for r in pay_cur.fetchall()]

    # Grafik
    c2 = conn.cursor(); c2.execute(chart_sql)
    chart = [{"day": r[0], "rev": r[1]} for r in c2.fetchall()]

    # Top taomlar
    c3 = conn.cursor(); c3.execute(top_sql)
    top_items = [{"name": r[0], "emoji": r[1], "count": r[2], "revenue": r[3]} for r in c3.fetchall()]

    # Ofitsiantlar samaradorligi
    c4 = conn.cursor(); c4.execute(staff_sql)
    staff_perf = [{"name": r[0], "sessions": r[1], "revenue": r[2]} for r in c4.fetchall()]

    # Ombor kam qolganlar
    c5 = conn.cursor(); c5.execute("SELECT name, quantity, min_quantity, unit FROM inventory WHERE quantity <= min_quantity ORDER BY quantity")
    low_stock = [{"name": r[0], "quantity": r[1], "min_quantity": r[2], "unit": r[3]} for r in c5.fetchall()]

    conn.close()
    return jsonify({
        "revenue": revenue, "expenses": expenses, "profit": revenue - expenses,
        "sessions": sessions_ct, "items_sold": items_ct, "avg_bill": round(avg_bill),
        "chart": chart, "top_items": top_items, "staff_perf": staff_perf,
        "low_stock": low_stock, "pay_by_method": pay_by_method
    })


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
