"""menu.py — menu CRUD + popular + stoplist"""
import logging

from flask import Blueprint, request, jsonify
from database import rows_to_list
from helpers import (
    check_auth, audit, _validate_str, db_exec, get_db, limiter,
)

log = logging.getLogger(__name__)
bp = Blueprint('menu', __name__)


@bp.route("/api/menu/popular", methods=["GET"])
@limiter.limit("120 per minute")
def popular_menu():
    limit = min(int(request.args.get("limit", 5)), 20)
    conn  = get_db()
    try:
        cur = db_exec(conn, """
            SELECT oi.menu_item_id AS id, oi.item_name AS name, oi.item_emoji AS emoji,
                   m.price, SUM(oi.quantity) AS total_ordered
            FROM order_items oi
            LEFT JOIN menu m ON oi.menu_item_id = m.id
            WHERE oi.status != 'cancelled' AND oi.menu_item_id IS NOT NULL
            GROUP BY oi.menu_item_id, oi.item_name, oi.item_emoji, m.price
            ORDER BY total_ordered DESC
            LIMIT ?
        """, (limit,))
        items = rows_to_list(cur)
    except Exception:
        items = []
    if not items:
        cur2 = db_exec(conn, "SELECT id, name, emoji, price FROM menu WHERE available=1 ORDER BY id LIMIT ?", (limit,))
        items = rows_to_list(cur2)
    return jsonify(items)


@bp.route("/api/menu", methods=["GET"])
@limiter.limit("120 per minute")
def get_menu():
    conn = get_db()
    category = request.args.get("category")
    if category and category != "all":
        cur = db_exec(conn, "SELECT * FROM menu WHERE category=? ORDER BY id", (category,))
    else:
        cur = db_exec(conn, "SELECT * FROM menu ORDER BY category, id")
    result = rows_to_list(cur)
    return jsonify(result)


@bp.route("/api/menu", methods=["POST"])
def add_menu():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    try:
        _validate_str(d.get("name"), 100, "Taom nomi")
        _validate_str(d.get("description"), 500, "Tavsif")
        _validate_str(d.get("emoji"), 10, "Emoji")
        price = float(d.get("price") or 0)
        if price <= 0:
            raise ValueError("Narx 0 dan katta bo'lishi kerak")
    except (ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    conn = get_db()
    try:
        db_exec(conn,
            "INSERT INTO menu (name, category, description, price, emoji, available) VALUES (?,?,?,?,?,?)",
            (d.get("name"), d.get("category"), d.get("description"), d.get("price"), d.get("emoji", "🍽"), d.get("available", 1))
        )
        conn.commit()
    except Exception as _dbe:
        try: conn.rollback()
        except Exception: pass
        log.error("add_menu DB xato: %s", _dbe)
        return jsonify({"error": "Server xatosi"}), 500
    audit("menu_add", "menu", user_name="admin", details={"name": d.get("name"), "price": d.get("price")})
    return jsonify({"ok": True})


@bp.route("/api/menu/<int:item_id>", methods=["PUT"])
def update_menu(item_id):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    try:
        _validate_str(d.get("name"), 100, "Taom nomi")
        _validate_str(d.get("description"), 500, "Tavsif")
        _validate_str(d.get("emoji"), 10, "Emoji")
        if "price" in d:
            price = float(d.get("price") or 0)
            if price <= 0:
                raise ValueError("Narx 0 dan katta bo'lishi kerak")
    except (ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    conn = get_db()
    try:
        db_exec(conn,
            "UPDATE menu SET name=?, category=?, description=?, price=?, emoji=?, available=? WHERE id=?",
            (d.get("name"), d.get("category"), d.get("description"), d.get("price"), d.get("emoji", "🍽"), d.get("available", 1), item_id)
        )
        conn.commit()
    except Exception as _dbe:
        try: conn.rollback()
        except Exception: pass
        log.error("update_menu DB xato: %s", _dbe)
        return jsonify({"error": "Server xatosi"}), 500
    audit("menu_update", "menu", item_id, "admin", {"name": d.get("name"), "price": d.get("price")})
    return jsonify({"ok": True})


@bp.route("/api/menu/<int:item_id>", methods=["DELETE"])
@limiter.limit("10 per minute")
def delete_menu(item_id):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_db()
    try:
        db_exec(conn, "DELETE FROM menu WHERE id=?", (item_id,))
        conn.commit()
    except Exception as _dbe:
        try: conn.rollback()
        except Exception: pass
        log.error("DB xato: %s", _dbe)
        return jsonify({"error": "Server xatosi"}), 500
    audit("menu_delete", "menu", item_id, "admin")
    return jsonify({"ok": True})


@bp.route("/api/menu/<int:item_id>/stoplist", methods=["PUT"])
def toggle_stoplist(item_id):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_db()
    try:
        db_exec(conn, "UPDATE menu SET available=? WHERE id=?",
                (0 if d.get("stop") else 1, item_id))
        conn.commit()
    except Exception as _dbe:
        try: conn.rollback()
        except Exception: pass
        log.error("toggle_stoplist DB xato: %s", _dbe)
        return jsonify({"error": "Server xatosi"}), 500
    return jsonify({"ok": True})
