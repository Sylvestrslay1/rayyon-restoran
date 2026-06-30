"""health.py — health check + client-errors + static HTML files"""
import os, logging

from flask import Blueprint, request, jsonify, send_from_directory, redirect
from database import USE_PG, get_conn as _get_conn_db, DATABASE_URL

log = logging.getLogger(__name__)
bp = Blueprint('health', __name__)


@bp.route("/api/health", methods=["GET"])
def health_check():
    from helpers import _db_ready, _db_error
    db_ok = False
    connect_error = None
    try:
        _conn = _get_conn_db()
        _cur = _conn.cursor()
        _cur.execute("SELECT 1")
        _conn.close()
        db_ok = True
    except Exception as _ce:
        connect_error = f"{type(_ce).__name__}: {_ce}"
    resp = {
        "status": "ok",
        "db_ready": db_ok,
        "init_done": _db_ready,
        "version": "1.0.0",
        "db_engine": "postgresql" if USE_PG else "sqlite",
        "db_url_set": bool(DATABASE_URL),
    }
    if _db_error:
        resp["init_error"] = _db_error
    if connect_error:
        resp["connect_error"] = connect_error
    return jsonify(resp), 200


@bp.route("/api/client-errors", methods=["POST"])
def client_errors():
    try:
        data = request.get_json(silent=True) or {}
        msg     = str(data.get("message", ""))[:500]
        source  = str(data.get("source", "unknown"))[:100]
        stack   = str(data.get("stack", ""))[:1000]
        url     = str(data.get("url", ""))[:200]
        ua      = request.headers.get("User-Agent", "")[:200]
        ip      = request.remote_addr
        log.error(
            "CLIENT_ERROR | source=%s | msg=%s | url=%s | ip=%s | ua=%s | stack=%s",
            source, msg, url, ip, ua, stack[:200]
        )
        return jsonify({"ok": True}), 200
    except Exception as e:
        log.warning("client_errors handler xato: %s", e)
        return jsonify({"ok": False}), 200


# ===== STATIC FILES =====
@bp.route("/")
def serve_site():
    base = os.path.join(os.path.dirname(__file__), "..", "..")
    return send_from_directory(base, "index.html")


@bp.route("/admin")
@bp.route("/admin/")
def serve_admin():
    base = os.path.join(os.path.dirname(__file__), "..", "..", "admin")
    return send_from_directory(base, "index.html")


@bp.route("/admin/<path:path>")
def serve_admin_files(path):
    base = os.path.join(os.path.dirname(__file__), "..", "..", "admin")
    return send_from_directory(base, path)


@bp.route("/login.html")
def redirect_login_html():
    return redirect("/admin/login.html", code=301)


@bp.route("/<path:path>")
def serve_static(path):
    base = os.path.join(os.path.dirname(__file__), "..", "..")
    full = os.path.join(base, path)
    if os.path.isdir(full):
        return send_from_directory(full, "index.html")
    return send_from_directory(base, path)
