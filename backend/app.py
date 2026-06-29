"""
app.py — Rayyon Restaurant Backend
Flask Blueprint modullarga bo'lingan (refactoring).
"""
import os, threading, logging, secrets

from flask import Flask, request, jsonify, redirect
from flask_cors import CORS
from database import init_db

logging.basicConfig(
    level=logging.getLevelName(os.environ.get("LOG_LEVEL", "INFO")),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

app = Flask(__name__, static_folder='../frontend', static_url_path='')
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_urlsafe(32))

# ===== CORS =====
_cors_origins = os.environ.get("ALLOWED_ORIGINS", "").strip()
_origins = _cors_origins.split(",") if _cors_origins else ["*"]
if not _cors_origins:
    log.warning("XAVFSIZLIK: ALLOWED_ORIGINS o'rnatilmagan — CORS barcha domenga ochiq!")
CORS(app, supports_credentials=True, origins=_origins,
     allow_headers=["Content-Type", "X-Admin-Token", "X-Kitchen-Token", "X-Session-Token", "X-Staff-Pin"],
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])

# ===== LIMITER (helpers.py dan olinadi va app ga bog'lanadi) =====
from helpers import limiter
limiter.init_app(app)

# ===== UPLOAD FOLDER =====
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

# ===== DB INIT (background) =====
import helpers as _helpers_mod

def _init_db_background():
    try:
        init_db()
        _helpers_mod._db_ready = True
        log.info("DB init muvaffaqiyatli yakunlandi")
    except Exception as _e:
        import traceback as _tb
        _helpers_mod._db_error = f"{type(_e).__name__}: {_e}"
        log.error("DB init xato: %s\n%s", _helpers_mod._db_error, _tb.format_exc())

threading.Thread(target=_init_db_background, daemon=True).start()

# ===== BLUEPRINTS =====
from routes.auth         import bp as auth_bp
from routes.menu         import bp as menu_bp
from routes.orders       import bp as orders_bp
from routes.reservations import bp as reservations_bp
from routes.tables       import bp as tables_bp
from routes.staff_routes import bp as staff_bp
from routes.kitchen      import bp as kitchen_bp
from routes.shifts       import bp as shifts_bp
from routes.inventory    import bp as inventory_bp
from routes.customers    import bp as customers_bp
from routes.analytics    import bp as analytics_bp
from routes.content      import bp as content_bp
from routes.settings_routes import bp as settings_bp
from routes.push         import bp as push_bp
from routes.health       import bp as health_bp

app.register_blueprint(auth_bp)
app.register_blueprint(menu_bp)
app.register_blueprint(orders_bp)
app.register_blueprint(reservations_bp)
app.register_blueprint(tables_bp)
app.register_blueprint(staff_bp)
app.register_blueprint(kitchen_bp)
app.register_blueprint(shifts_bp)
app.register_blueprint(inventory_bp)
app.register_blueprint(customers_bp)
app.register_blueprint(analytics_bp)
app.register_blueprint(content_bp)
app.register_blueprint(settings_bp)
app.register_blueprint(push_bp)
app.register_blueprint(health_bp)

# ===== TEARDOWN (per-request DB close) =====
from flask import g as _g

@app.teardown_appcontext
def _close_db(error):
    db = _g.pop("db", None)
    if db is not None:
        try:
            db.close()
        except Exception:
            pass

# ===== BEFORE/AFTER REQUEST =====
_CSRF_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_CSRF_PUBLIC_PATHS = {
    "/api/staff/login",
    "/api/staff/checkin",
    "/api/orders",
    "/api/reservations",
    "/api/events",
    "/api/health",
    "/api/logout",
}

@app.before_request
def force_https():
    if os.environ.get("FLASK_ENV") == "production":
        proto = request.headers.get("X-Forwarded-Proto", "https")
        if proto == "http":
            url = request.url.replace("http://", "https://", 1)
            return redirect(url, code=301)

@app.before_request
def csrf_origin_check():
    if request.method in _CSRF_SAFE_METHODS:
        return
    if request.path in _CSRF_PUBLIC_PATHS:
        return
    if request.headers.get("X-Admin-Token") or request.headers.get("X-Staff-Pin"):
        return
    if request.headers.get("X-Kitchen-Token"):
        return
    origin = request.headers.get("Origin") or request.headers.get("Referer", "")
    if not origin:
        return
    server_host = request.host
    try:
        from urllib.parse import urlparse
        origin_host = urlparse(origin).netloc
        if origin_host and origin_host != server_host:
            log.warning("CSRF tekshiruvdan o'tmadi: origin=%s host=%s path=%s",
                        origin_host, server_host, request.path)
            return jsonify({"error": "Ruxsat yo'q (CSRF)"}), 403
    except Exception:
        pass

@app.after_request
def add_security_headers(response):
    if request.path.startswith(("/css/", "/js/", "/assets/", "/uploads/", "/favicon")):
        response.headers["Cache-Control"] = "public, max-age=86400"
    elif request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if os.environ.get("FLASK_ENV") == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com https://cdnjs.cloudflare.com https://api.telegram.org; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: blob: https:; "
        "connect-src 'self' https://api.telegram.org; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self';"
    )
    return response

# ===== ERROR HANDLERS =====
@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Endpoint topilmadi", "path": request.path}), 404
    return jsonify({"error": "Sahifa topilmadi"}), 404

@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({"error": "Bu method ruxsat etilmagan", "allowed": e.valid_methods}), 405

@app.errorhandler(500)
def internal_error(e):
    log.error("500 xato: %s — %s", request.path, e)
    return jsonify({"error": "Server ichki xatosi"}), 500

@app.errorhandler(429)
def too_many_requests(e):
    return jsonify({"error": "Juda ko'p so'rov. Biroz kuting."}), 429

# ===== STARTUP CHECKS =====
def _startup_checks():
    if not os.environ.get("ADMIN_PASSWORD"):
        log.warning("=" * 60)
        log.warning("XAVFSIZLIK: ADMIN_PASSWORD o'rnatilmagan!")
        log.warning("Admin panelga kirish BLOKLANADI.")
        log.warning("Render > Environment: ADMIN_PASSWORD=kuchli_parol")
        log.warning("=" * 60)
    if not os.environ.get("SECRET_KEY"):
        log.warning("SECRET_KEY o'rnatilmagan — har restartda sessiyalar o'chadi!")
    if not os.environ.get("REDIS_URL") and os.environ.get("FLASK_ENV") == "production":
        log.warning("REDIS_URL yo'q — multi-worker rejimida auth sessiyalar yo'qolishi mumkin!")

_startup_checks()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV") != "production"
    print(f"Rayyon backend ishga tushdi: http://localhost:{port}")
    app.run(host="0.0.0.0", debug=debug, port=port)
