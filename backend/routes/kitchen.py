"""kitchen.py — kitchen KDS + SSE events"""
import json, logging

from flask import Blueprint, request, jsonify, Response
from database import rows_to_list
from helpers import (
    check_kitchen_auth, db_exec, get_db,
    _sse_clients, _sse_lock,
)

log = logging.getLogger(__name__)
bp = Blueprint('kitchen', __name__)


@bp.route("/api/kitchen", methods=["GET"])
def kitchen_orders():
    if not check_kitchen_auth():
        return jsonify({"error": "Ruxsat yo'q. Kitchen token kerak."}), 403
    conn = get_db()
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
    grouped = {}
    for item in items:
        tbl = str(item.get("table_number") or item.get("tnum") or "?")
        if tbl not in grouped:
            grouped[tbl] = {"table": tbl, "session_id": item["session_id"], "items": []}
        grouped[tbl]["items"].append(item)
    return jsonify(list(grouped.values()))


@bp.route("/api/kitchen/ready", methods=["GET"])
def kitchen_ready():
    if not check_kitchen_auth():
        return jsonify({"error": "Ruxsat yo'q. Kitchen token kerak."}), 403
    conn = get_db()
    cur  = db_exec(conn, """SELECT oi.* FROM order_items oi
        WHERE oi.status='ready' ORDER BY oi.updated_at""")
    items = rows_to_list(cur)
    return jsonify(items)


@bp.route("/api/events")
def sse_stream():
    from queue import Queue, Empty
    client_q = Queue(maxsize=50)
    with _sse_lock:
        _sse_clients.append(client_q)

    def generate():
        try:
            yield "data: {\"type\": \"connected\"}\n\n"
            while True:
                try:
                    msg = client_q.get(timeout=25)
                    yield msg
                except Empty:
                    yield ": ping\n\n"
        finally:
            with _sse_lock:
                try:
                    _sse_clients.remove(client_q)
                except ValueError:
                    pass

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
