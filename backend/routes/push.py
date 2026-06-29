"""push.py — push notifications (VAPID)"""
import json, os, logging

from flask import Blueprint, request, jsonify
from database import rows_to_list
from helpers import check_auth, db_exec, get_db

log = logging.getLogger(__name__)
bp = Blueprint('push', __name__)

VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC_KEY  = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_CLAIMS      = {"sub": f"mailto:{os.environ.get('VAPID_EMAIL', 'admin@rayyon.uz')}"}


@bp.route("/api/push/vapid-key", methods=["GET"])
def push_vapid_key():
    if not VAPID_PUBLIC_KEY:
        return jsonify({"ok": False, "error": "VAPID_PUBLIC_KEY o'rnatilmagan"}), 503
    return jsonify({"ok": True, "key": VAPID_PUBLIC_KEY})


@bp.route("/api/push/subscribe", methods=["POST"])
def push_subscribe():
    if not check_auth():
        return jsonify({"ok": False, "error": "Ruxsat yo'q"}), 403
    data = request.json or {}
    subscription = data.get("subscription")
    if not subscription:
        return jsonify({"ok": False, "error": "subscription yo'q"}), 400
    endpoint = subscription.get("endpoint", "")
    if not endpoint:
        return jsonify({"ok": False, "error": "endpoint yo'q"}), 400
    keys    = subscription.get("keys", {})
    p256dh  = keys.get("p256dh", "")
    auth_key = keys.get("auth", "")
    conn = get_db()
    try:
        db_exec(conn, """
            INSERT OR IGNORE INTO push_subscriptions (endpoint, p256dh, auth)
            VALUES (?, ?, ?)
        """, (endpoint, p256dh, auth_key))
        conn.commit()
    except Exception as _dbe:
        try: conn.rollback()
        except Exception: pass
        log.error("DB xato: %s", _dbe)
        return jsonify({"error": "Server xatosi"}), 500
    return jsonify({"ok": True})


@bp.route("/api/push/unsubscribe", methods=["POST"])
def push_unsubscribe():
    data = request.json or {}
    endpoint = data.get("endpoint", "")
    if not endpoint:
        return jsonify({"ok": False}), 400
    conn = get_db()
    try:
        db_exec(conn, "DELETE FROM push_subscriptions WHERE endpoint=?", (endpoint,))
        conn.commit()
    except Exception as _dbe:
        try: conn.rollback()
        except Exception: pass
        log.error("DB xato: %s", _dbe)
        return jsonify({"error": "Server xatosi"}), 500
    return jsonify({"ok": True})


@bp.route("/api/push/send", methods=["POST"])
def push_send():
    if not check_auth():
        return jsonify({"ok": False, "error": "Ruxsat yo'q"}), 403
    if not VAPID_PRIVATE_KEY or not VAPID_PUBLIC_KEY:
        return jsonify({"ok": False, "error": "VAPID kalitlari o'rnatilmagan"}), 503
    data = request.json or {}
    payload = json.dumps({
        "title": data.get("title", "Rayyon Restoran"),
        "body":  data.get("body", ""),
        "url":   data.get("url", "/"),
        "tag":   data.get("tag", "rayyon"),
    })
    conn = get_db()
    try:
        cur = db_exec(conn, "SELECT * FROM push_subscriptions", ())
        subs = rows_to_list(cur)
    except Exception as _dbe:
        try: conn.rollback()
        except Exception: pass
        log.error("DB xato: %s", _dbe)
        return jsonify({"error": "Server xatosi"}), 500
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        return jsonify({"ok": False, "error": "pywebpush o'rnatilmagan"}), 503
    sent = 0
    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub["endpoint"],
                    "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
                },
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS,
            )
            sent += 1
        except Exception as e:
            log.warning("Push yuborilmadi %s: %s", sub["endpoint"][:40], e)
    return jsonify({"ok": True, "sent": sent, "total": len(subs)})
