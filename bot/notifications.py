"""Proaktiv bildirishnomalar: fon thread, yangi bronlar/buyurtmalar/hisob/inventar/kunlik hisobot."""
import datetime, time
from core import (
    api, send_kb, send_msg, log,
    ALLOWED_CHAT_IDS, _NOTIF_INTERVAL, _DAILY_REPORT_HOUR,
)

_notified_res   = set()   # bron ID lari — allaqachon xabar yuborilgan
_notified_ord   = set()   # QR buyurtma ID lari
_notified_bill  = set()   # hisob so'ragan sessiya ID lari
_notified_low   = set()   # kam inventar item ID lari (kun davomida bir marta)
_last_daily_day = None    # kunlik hisobot yuborilgan kun (ISO sana)


def notify_all(text, buttons=None):
    """Barcha ruxsatli chatlarga xabar yuboradi."""
    if not ALLOWED_CHAT_IDS:
        return
    for cid in ALLOWED_CHAT_IDS:
        try:
            if buttons:
                send_kb(cid, text, buttons)
            else:
                send_msg(cid, text)
        except Exception as e:
            log.error(f"notify_all {cid}: {e}")


def check_new_reservations():
    items = api("GET", "/api/reservations")
    if not isinstance(items, list):
        return
    for r in items:
        rid = r.get("id")
        if not rid or rid in _notified_res:
            continue
        if r.get("status") not in ("new",):
            _notified_res.add(rid)
            continue
        _notified_res.add(rid)
        txt = (
            f"📅 <b>YANGI BRON #{rid}</b>\n"
            f"👤 {r.get('customer_name','')} · {r.get('customer_phone','')}\n"
            f"📆 {r.get('date','')} {r.get('time','')}\n"
            f"👥 {r.get('guests', 2)} mehmon"
            + (f"\n📝 {r['note']}" if r.get("note") else "")
        )
        btns = [[
            {"text": "✅ Tasdiqlash", "callback_data": f"res_confirmed_{rid}"},
            {"text": "❌ Bekor",      "callback_data": f"res_cancelled_{rid}"},
        ]]
        notify_all(txt, btns)
        log.info(f"Yangi bron xabari yuborildi: #{rid}")


def check_new_orders():
    items = api("GET", "/api/orders?status=new")
    if not isinstance(items, list):
        return
    for o in items:
        oid = o.get("id")
        if not oid or oid in _notified_ord:
            continue
        _notified_ord.add(oid)
        txt = (
            f"📦 <b>YANGI BUYURTMA #{oid}</b>\n"
            f"🍽 {o.get('item_name','')} × {o.get('quantity', 1)}\n"
            f"💰 {int(o.get('total_price', 0)):,} so'm\n"
            f"👤 {o.get('customer_name','')} · {o.get('customer_phone','')}"
            + (f"\n📝 {o['note']}" if o.get("note") else "")
        )
        btns = [[
            {"text": "✅ Tasdiqlash", "callback_data": f"ord_confirmed_{oid}"},
            {"text": "✔️ Bajarildi",  "callback_data": f"ord_done_{oid}"},
            {"text": "❌ Bekor",      "callback_data": f"ord_cancelled_{oid}"},
        ]]
        notify_all(txt, btns)
        log.info(f"Yangi buyurtma xabari yuborildi: #{oid}")


def check_bill_requests():
    tables = api("GET", "/api/tables")
    if not isinstance(tables, list):
        return
    for t in tables:
        if t.get("status") != "bill_requested":
            continue
        sid = t.get("current_session_id")
        if not sid or sid in _notified_bill:
            continue
        _notified_bill.add(sid)
        amt = f"{int(t.get('total_amount', 0)):,} so'm" if t.get("total_amount") else "—"
        txt = (
            f"🧾 <b>HISOB SO'RALDI — Stol #{t['number']}</b>\n"
            f"💰 Summa: {amt}\n"
            f"👤 Ofitsiant: {t.get('waiter_name', '—')}\n"
            f"⏱ {t.get('minutes_open', 0)} daqiqa"
        )
        notify_all(txt)
        log.info(f"Hisob so'rash xabari: stol #{t['number']}")


def check_low_inventory():
    items = api("GET", "/api/inventory")
    if not isinstance(items, list):
        return
    low = [i for i in items
           if (i.get("quantity") or 0) <= (i.get("min_quantity") or 0)
           and i["id"] not in _notified_low]
    if not low:
        return
    for i in low:
        _notified_low.add(i["id"])
    lines = [f"⚠️ <b>KAM MAHSULOTLAR ({len(low)} ta)</b>\n"]
    for i in low[:15]:
        lines.append(f"🔴 {i['name']}: {i.get('quantity', 0)} {i.get('unit', '')} "
                     f"(min: {i.get('min_quantity', 0)})")
    notify_all("\n".join(lines))
    log.info(f"Kam inventar xabari yuborildi: {len(low)} ta")


def send_daily_report():
    global _last_daily_day
    now   = datetime.datetime.now()
    today = now.date().isoformat()
    if now.hour < _DAILY_REPORT_HOUR or _last_daily_day == today:
        return
    _last_daily_day = today
    stats = api("GET", "/api/analytics/summary?period=daily")
    if not stats or not isinstance(stats, dict):
        return
    revenue  = int(stats.get("revenue", 0))
    expenses = int(stats.get("expenses", 0))
    profit   = revenue - expenses
    sessions = stats.get("sessions", 0)
    items_ct = stats.get("items_sold", 0)
    avg      = int(stats.get("avg_bill", 0))
    txt = (
        f"📊 <b>KUNLIK HISOBOT — {today}</b>\n\n"
        f"💰 Daromad:   <b>{revenue:,} so'm</b>\n"
        f"📤 Xarajat:   <b>{expenses:,} so'm</b>\n"
        f"📈 Foyda:     <b>{profit:,} so'm</b>\n"
        f"🪑 Xizmatlar: <b>{sessions}</b> ta\n"
        f"🍽 Taomlar:   <b>{items_ct}</b> ta\n"
        f"🧾 O'rtacha:  <b>{avg:,} so'm</b>"
    )
    notify_all(txt)
    log.info(f"Kunlik hisobot yuborildi: {today}")


def _notification_loop():
    log.info(f"Bildirishnoma tekshiruvi boshlandi (har {_NOTIF_INTERVAL}s)")
    while True:
        try:
            check_new_reservations()
            check_new_orders()
            check_bill_requests()
            check_low_inventory()
            send_daily_report()
        except Exception as e:
            log.error(f"Bildirishnoma xatosi: {e}")
        time.sleep(_NOTIF_INTERVAL)
