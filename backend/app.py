from flask import Flask, request, jsonify, send_from_directory, session
from flask_cors import CORS
import os, json, time
from database import get_conn, init_db
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "rayyon_secret_2024"
CORS(app, supports_credentials=True)

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
ALLOWED_EXT = {"png", "jpg", "jpeg", "gif", "webp"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10MB

init_db()


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def get_setting(key):
    conn = get_conn()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else None


def rows_to_list(rows):
    return [dict(r) for r in rows]


# ===== AUTH =====
@app.route("/api/login", methods=["POST"])
def login():
    data = request.json or {}
    password = data.get("password", "")
    correct = get_setting("admin_password")
    if password == correct:
        session["admin"] = True
        return jsonify({"ok": True, "token": "admin_" + str(int(time.time()))})
    return jsonify({"ok": False, "error": "Noto'g'ri parol"}), 401


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


def check_auth():
    token = request.headers.get("X-Admin-Token", "")
    return token.startswith("admin_")


# ===== MENU =====
@app.route("/api/menu", methods=["GET"])
def get_menu():
    conn = get_conn()
    category = request.args.get("category")
    if category and category != "all":
        rows = conn.execute("SELECT * FROM menu WHERE category=? ORDER BY id", (category,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM menu ORDER BY category, id").fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


@app.route("/api/menu", methods=["POST"])
def add_menu():
    if not check_auth():
        return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    conn.execute(
        "INSERT INTO menu (name, category, description, price, emoji, available) VALUES (?,?,?,?,?,?)",
        (d.get("name"), d.get("category"), d.get("description"), d.get("price"), d.get("emoji", "🍽"), d.get("available", 1))
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/menu/<int:item_id>", methods=["PUT"])
def update_menu(item_id):
    if not check_auth():
        return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    conn.execute(
        "UPDATE menu SET name=?, category=?, description=?, price=?, emoji=?, available=? WHERE id=?",
        (d.get("name"), d.get("category"), d.get("description"), d.get("price"), d.get("emoji", "🍽"), d.get("available", 1), item_id)
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/menu/<int:item_id>", methods=["DELETE"])
def delete_menu(item_id):
    if not check_auth():
        return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    conn.execute("DELETE FROM menu WHERE id=?", (item_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ===== ORDERS =====
@app.route("/api/orders", methods=["GET"])
def get_orders():
    if not check_auth():
        return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    status = request.args.get("status")
    if status:
        rows = conn.execute("SELECT * FROM orders WHERE status=? ORDER BY created_at DESC", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM orders ORDER BY created_at DESC").fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


@app.route("/api/orders", methods=["POST"])
def add_order():
    d = request.json or {}
    conn = get_conn()
    conn.execute(
        "INSERT INTO orders (item_name, item_id, quantity, total_price, customer_name, customer_phone, note) VALUES (?,?,?,?,?,?,?)",
        (d.get("item_name"), d.get("item_id"), d.get("quantity", 1),
         d.get("total_price"), d.get("customer_name"), d.get("customer_phone"), d.get("note"))
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/orders/<int:order_id>", methods=["PUT"])
def update_order(order_id):
    if not check_auth():
        return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    conn.execute("UPDATE orders SET status=? WHERE id=?", (d.get("status"), order_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ===== RESERVATIONS =====
@app.route("/api/reservations", methods=["GET"])
def get_reservations():
    if not check_auth():
        return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    rows = conn.execute("SELECT * FROM reservations ORDER BY created_at DESC").fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


@app.route("/api/reservations", methods=["POST"])
def add_reservation():
    d = request.json or {}
    conn = get_conn()
    conn.execute(
        "INSERT INTO reservations (customer_name, customer_phone, date, time, guests, note) VALUES (?,?,?,?,?,?)",
        (d.get("customer_name"), d.get("customer_phone"), d.get("date"), d.get("time"), d.get("guests", 2), d.get("note"))
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/reservations/<int:res_id>", methods=["PUT"])
def update_reservation(res_id):
    if not check_auth():
        return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    conn.execute("UPDATE reservations SET status=? WHERE id=?", (d.get("status"), res_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ===== NEWS =====
@app.route("/api/news", methods=["GET"])
def get_news():
    conn = get_conn()
    active_only = request.args.get("active") == "1"
    if active_only:
        rows = conn.execute("SELECT * FROM news WHERE active=1 ORDER BY created_at DESC").fetchall()
    else:
        rows = conn.execute("SELECT * FROM news ORDER BY created_at DESC").fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


@app.route("/api/news", methods=["POST"])
def add_news():
    if not check_auth():
        return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    conn.execute(
        "INSERT INTO news (title, content, image, active) VALUES (?,?,?,?)",
        (d.get("title"), d.get("content"), d.get("image"), d.get("active", 1))
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/news/<int:news_id>", methods=["PUT"])
def update_news(news_id):
    if not check_auth():
        return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    conn.execute(
        "UPDATE news SET title=?, content=?, active=? WHERE id=?",
        (d.get("title"), d.get("content"), d.get("active", 1), news_id)
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/news/<int:news_id>", methods=["DELETE"])
def delete_news(news_id):
    if not check_auth():
        return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    conn.execute("DELETE FROM news WHERE id=?", (news_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ===== IMAGE UPLOAD =====
@app.route("/api/upload", methods=["POST"])
def upload_image():
    if not check_auth():
        return jsonify({"error": "Ruxsat yo'q"}), 403
    if "file" not in request.files:
        return jsonify({"error": "Fayl topilmadi"}), 400
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
    if not check_auth():
        return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    return jsonify({r["key"]: r["value"] for r in rows})


@app.route("/api/settings", methods=["PUT"])
def update_settings():
    if not check_auth():
        return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_conn()
    for key, val in d.items():
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, str(val)))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ===== STATS =====
@app.route("/api/stats", methods=["GET"])
def get_stats():
    if not check_auth():
        return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_conn()
    orders_total = conn.execute("SELECT COUNT(*) as c FROM orders").fetchone()["c"]
    orders_new = conn.execute("SELECT COUNT(*) as c FROM orders WHERE status='new'").fetchone()["c"]
    revenue = conn.execute("SELECT COALESCE(SUM(total_price),0) as s FROM orders WHERE status='done'").fetchone()["s"]
    reservations_today = conn.execute(
        "SELECT COUNT(*) as c FROM reservations WHERE date=date('now','localtime')"
    ).fetchone()["c"]
    menu_count = conn.execute("SELECT COUNT(*) as c FROM menu WHERE available=1").fetchone()["c"]
    conn.close()
    return jsonify({
        "orders_total": orders_total,
        "orders_new": orders_new,
        "revenue": revenue,
        "reservations_today": reservations_today,
        "menu_count": menu_count,
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
