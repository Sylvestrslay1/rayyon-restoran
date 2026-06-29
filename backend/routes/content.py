"""content.py — news + gallery + promotions + upload"""
import os, time, logging

from flask import Blueprint, request, jsonify, send_from_directory
from database import rows_to_list
from helpers import (
    check_auth, _validate_str,
    db_exec, get_db, limiter,
    allowed_file, check_image_mime,
)

log = logging.getLogger(__name__)
bp = Blueprint('content', __name__)


# ===== NEWS =====
@bp.route("/api/news", methods=["GET"])
def get_news():
    conn = get_db()
    if request.args.get("active") == "1":
        cur = db_exec(conn, "SELECT * FROM news WHERE active=1 ORDER BY created_at DESC")
    else:
        cur = db_exec(conn, "SELECT * FROM news ORDER BY created_at DESC")
    result = rows_to_list(cur)
    return jsonify(result)


@bp.route("/api/news", methods=["POST"])
def add_news():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    try:
        _validate_str(d.get("title"), 200, "Sarlavha")
        _validate_str(d.get("content"), 2000, "Matn")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    try:
        conn = get_db()
        db_exec(conn,
            "INSERT INTO news (title, content, image, active) VALUES (?,?,?,?)",
            (d.get("title"), d.get("content"), d.get("image"), d.get("active", 1))
        )
        conn.commit()
    except Exception as e:
        log.error("add_news DB xato: %s", e)
        return jsonify({"error": f"DB xato: {e}"}), 500
    return jsonify({"ok": True})


@bp.route("/api/news/<int:news_id>", methods=["PUT"])
def update_news(news_id):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_db()
    try:
        db_exec(conn,
            "UPDATE news SET title=?, content=?, active=? WHERE id=?",
            (d.get("title"), d.get("content"), d.get("active", 1), news_id)
        )
        conn.commit()
    except Exception as _dbe:
        try: conn.rollback()
        except Exception: pass
        log.error("update_news DB xato: %s", _dbe)
        return jsonify({"error": "Server xatosi"}), 500
    return jsonify({"ok": True})


@bp.route("/api/news/<int:news_id>", methods=["DELETE"])
@limiter.limit("10 per minute")
def delete_news(news_id):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_db()
    try:
        db_exec(conn, "DELETE FROM news WHERE id=?", (news_id,))
        conn.commit()
    except Exception as _dbe:
        try: conn.rollback()
        except Exception: pass
        log.error("DB xato: %s", _dbe)
        return jsonify({"error": "Server xatosi"}), 500
    return jsonify({"ok": True})


# ===== GALEREYA =====
@bp.route("/api/gallery", methods=["GET"])
def get_gallery():
    conn = get_db()
    active = request.args.get("active")
    if active == "1":
        cur = db_exec(conn, "SELECT * FROM gallery WHERE active=1 ORDER BY sort_order, id")
    else:
        cur = db_exec(conn, "SELECT * FROM gallery ORDER BY sort_order, id")
    result = rows_to_list(cur)
    return jsonify(result)


@bp.route("/api/gallery", methods=["POST"])
def add_gallery():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    try:
        _validate_str(d.get("title"), 200, "Sarlavha")
        _validate_str(d.get("emoji"),  10, "Emoji")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    conn = get_db()
    try:
        db_exec(conn, "INSERT INTO gallery (title, emoji, image, sort_order, active) VALUES (?,?,?,?,?)",
            (d.get("title"), d.get("emoji","🖼"), d.get("image"), d.get("sort_order",0), d.get("active",1)))
        conn.commit()
    except Exception as _dbe:
        try: conn.rollback()
        except Exception: pass
        log.error("add_gallery DB xato: %s", _dbe)
        return jsonify({"error": "Server xatosi"}), 500
    return jsonify({"ok": True})


@bp.route("/api/gallery/<int:gid>", methods=["PUT"])
def update_gallery(gid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_db()
    try:
        db_exec(conn, "UPDATE gallery SET title=?, emoji=?, image=?, sort_order=?, active=? WHERE id=?",
            (d.get("title"), d.get("emoji","🖼"), d.get("image"), d.get("sort_order",0), d.get("active",1), gid))
        conn.commit()
    except Exception as _dbe:
        try: conn.rollback()
        except Exception: pass
        log.error("update_gallery DB xato: %s", _dbe)
        return jsonify({"error": "Server xatosi"}), 500
    return jsonify({"ok": True})


@bp.route("/api/gallery/<int:gid>", methods=["DELETE"])
@limiter.limit("10 per minute")
def delete_gallery(gid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_db()
    try:
        db_exec(conn, "DELETE FROM gallery WHERE id=?", (gid,))
        conn.commit()
    except Exception as _dbe:
        try: conn.rollback()
        except Exception: pass
        log.error("DB xato: %s", _dbe)
        return jsonify({"error": "Server xatosi"}), 500
    return jsonify({"ok": True})


# ===== AKSIYALAR =====
@bp.route("/api/promotions", methods=["GET"])
def get_promotions():
    conn = get_db()
    active = request.args.get("active")
    if active == "1":
        cur = db_exec(conn, "SELECT * FROM promotions WHERE active=1 ORDER BY sort_order, id")
    else:
        cur = db_exec(conn, "SELECT * FROM promotions ORDER BY sort_order, id")
    result = rows_to_list(cur)
    return jsonify(result)


@bp.route("/api/promotions", methods=["POST"])
def add_promotion():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    try:
        _validate_str(d.get("title"),       200,  "Sarlavha")
        _validate_str(d.get("description"), 1000, "Tavsif")
        _validate_str(d.get("badge"),        20,  "Badge")
        _validate_str(d.get("time_info"),   100,  "Vaqt ma'lumoti")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    conn = get_db()
    try:
        db_exec(conn, "INSERT INTO promotions (title, description, badge, emoji, time_info, sort_order, active) VALUES (?,?,?,?,?,?,?)",
            (d.get("title"), d.get("description"), d.get("badge"), d.get("emoji","🎁"), d.get("time_info"), d.get("sort_order",0), d.get("active",1)))
        conn.commit()
    except Exception as _dbe:
        try: conn.rollback()
        except Exception: pass
        log.error("add_promotion DB xato: %s", _dbe)
        return jsonify({"error": "Server xatosi"}), 500
    return jsonify({"ok": True})


@bp.route("/api/promotions/<int:pid>", methods=["PUT"])
def update_promotion(pid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    d = request.json or {}
    conn = get_db()
    try:
        db_exec(conn, "UPDATE promotions SET title=?, description=?, badge=?, emoji=?, time_info=?, sort_order=?, active=? WHERE id=?",
            (d.get("title"), d.get("description"), d.get("badge"), d.get("emoji","🎁"), d.get("time_info"), d.get("sort_order",0), d.get("active",1), pid))
        conn.commit()
    except Exception as _dbe:
        try: conn.rollback()
        except Exception: pass
        log.error("update_promotion DB xato: %s", _dbe)
        return jsonify({"error": "Server xatosi"}), 500
    return jsonify({"ok": True})


@bp.route("/api/promotions/<int:pid>", methods=["DELETE"])
@limiter.limit("10 per minute")
def delete_promotion(pid):
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    conn = get_db()
    try:
        db_exec(conn, "DELETE FROM promotions WHERE id=?", (pid,))
        conn.commit()
    except Exception as _dbe:
        try: conn.rollback()
        except Exception: pass
        log.error("DB xato: %s", _dbe)
        return jsonify({"error": "Server xatosi"}), 500
    return jsonify({"ok": True})


# ===== IMAGE UPLOAD =====
@bp.route("/api/upload", methods=["POST"])
def upload_image():
    if not check_auth(): return jsonify({"error": "Ruxsat yo'q"}), 403
    if "file" not in request.files: return jsonify({"error": "Fayl topilmadi"}), 400
    file = request.files["file"]
    if file.filename == "" or not allowed_file(file.filename):
        return jsonify({"error": "Noto'g'ri fayl turi (png, jpg, gif, webp)"}), 400
    if not check_image_mime(file.stream):
        return jsonify({"error": "Fayl mazmuni rasm emas (MIME tekshiruvi muvaffaqiyatsiz)"}), 400
    try:
        from PIL import Image as _Img
        img = _Img.open(file.stream)
        w, h = img.size
        if w > 4000 or h > 4000:
            return jsonify({"error": f"Rasm o'lchami juda katta ({w}x{h}). Maksimal 4000x4000px"}), 400
        file.stream.seek(0)
    except ImportError:
        file.stream.seek(0)
    except Exception:
        file.stream.seek(0)
    from werkzeug.utils import secure_filename
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "..", "uploads")
    filename = str(int(time.time())) + "_" + secure_filename(file.filename)
    file.save(os.path.join(UPLOAD_FOLDER, filename))
    return jsonify({"ok": True, "url": f"/uploads/{filename}"})


@bp.route("/uploads/<filename>")
def uploaded_file(filename):
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "..", "uploads")
    return send_from_directory(UPLOAD_FOLDER, filename)
