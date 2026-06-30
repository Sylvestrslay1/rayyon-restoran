"""inventory.py — inventory + recipes"""
import logging

from flask import Blueprint, request, jsonify
from database import get_conn, rows_to_list
from helpers import (
    check_auth, _int_param,
    db_exec, get_db, limiter,
)

log = logging.getLogger(__name__)
bp = Blueprint('inventory', __name__)


@bp.route("/api/inventory", methods=["GET"])
def get_inventory():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    limit  = _int_param("limit", 500, max_val=2000)
    offset = _int_param("offset", 0, min_val=0)
    search = request.args.get("q", "").strip()
    conn   = get_db()
    if search:
        cur = db_exec(conn,
            "SELECT * FROM inventory WHERE name LIKE ? ORDER BY name LIMIT ? OFFSET ?",
            (f"%{search}%", limit, offset))
    else:
        cur = db_exec(conn,
            "SELECT * FROM inventory ORDER BY name LIMIT ? OFFSET ?",
            (limit, offset))
    result = rows_to_list(cur)
    return jsonify({"data": result, "limit": limit, "offset": offset, "count": len(result)})


@bp.route("/api/inventory", methods=["POST"])
def add_inventory():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    name = (d.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Mahsulot nomi kiritilmadi"}), 400
    unit = (d.get("unit") or "kg").strip()
    if not unit:
        return jsonify({"error": "Birlik kiritilmadi"}), 400
    try:
        qty = float(d.get("quantity", 0))
        if qty < 0:
            return jsonify({"error": "Miqdor manfi bo'lishi mumkin emas"}), 400
    except (ValueError, TypeError):
        return jsonify({"error": "Miqdor noto'g'ri formatda"}), 400
    conn = get_db()
    db_exec(conn,
        "INSERT INTO inventory (name, unit, quantity, min_quantity, price_per_unit) VALUES (?,?,?,?,?)",
        (name, unit, qty, d.get("min_quantity", 0), d.get("price_per_unit", 0))
    )
    conn.commit()
    return jsonify({"ok": True})


@bp.route("/api/inventory/<int:iid>", methods=["PUT"])
def update_inventory(iid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d    = request.json or {}
    new_qty = d.get("quantity")
    if new_qty is not None and float(new_qty) < 0:
        return jsonify({"error": "Miqdor manfi bo'lishi mumkin emas"}), 400
    conn = get_db()
    cur  = db_exec(conn, "SELECT name, quantity FROM inventory WHERE id=?", (iid,))
    row  = cur.fetchone()
    if row:
        from database import USE_PG
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
    conn.commit()
    return jsonify({"ok": True})


@bp.route("/api/inventory/<int:iid>", methods=["DELETE"])
@limiter.limit("10 per minute")
def delete_inventory(iid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_db()
    try:
        db_exec(conn, "DELETE FROM inventory WHERE id=?", (iid,))
        conn.commit()
    except Exception as _dbe:
        try: conn.rollback()
        except Exception: pass
        log.error("DB xato: %s", _dbe)
        return jsonify({"error": "Server xatosi"}), 500
    return jsonify({"ok": True})


@bp.route("/api/inventory/log", methods=["GET"])
def get_inventory_log():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    limit  = _int_param("limit", 100, max_val=500)
    offset = _int_param("offset", 0, min_val=0)
    conn   = get_db()
    cur    = db_exec(conn,
        "SELECT * FROM inventory_log ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (limit, offset))
    result = rows_to_list(cur)
    return jsonify({"data": result, "limit": limit, "offset": offset, "count": len(result)})


# ===== RETSEPTLAR =====
@bp.route("/api/recipes", methods=["GET"])
def get_recipes():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    menu_item_id = request.args.get("menu_item_id")
    conn = get_db()
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
    return jsonify(result)


@bp.route("/api/recipes", methods=["POST"])
def add_recipe():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    menu_item_id = d.get("menu_item_id")
    inventory_id = d.get("inventory_id")
    if not menu_item_id:
        return jsonify({"error": "Taom tanlanmadi"}), 400
    if not inventory_id:
        return jsonify({"error": "Mahsulot tanlanmadi"}), 400
    try:
        qty = float(d.get("quantity", 0))
        if qty <= 0:
            return jsonify({"error": "Miqdor 0 dan katta bo'lishi kerak"}), 400
    except (ValueError, TypeError):
        return jsonify({"error": "Miqdor noto'g'ri formatda"}), 400
    conn = get_db()
    db_exec(conn, "DELETE FROM recipes WHERE menu_item_id=? AND inventory_id=?",
            (menu_item_id, inventory_id))
    db_exec(conn,
        "INSERT INTO recipes (menu_item_id, inventory_id, quantity, unit) VALUES (?,?,?,?)",
        (menu_item_id, inventory_id, qty, d.get("unit", "g"))
    )
    conn.commit()
    return jsonify({"ok": True})


@bp.route("/api/recipes/<int:rid>", methods=["DELETE"])
@limiter.limit("10 per minute")
def delete_recipe(rid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_db()
    try:
        db_exec(conn, "DELETE FROM recipes WHERE id=?", (rid,))
        conn.commit()
    except Exception as _dbe:
        try: conn.rollback()
        except Exception: pass
        log.error("DB xato: %s", _dbe)
        return jsonify({"error": "Server xatosi"}), 500
    return jsonify({"ok": True})
