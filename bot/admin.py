"""Admin bot: menyu, hisobotlar, smenalar, inventar, mijozlar."""
import datetime
from core import api, send_kb, send_msg, STATUS_LABELS, _ascii_bar


def main_menu(chat_id):
    now = datetime.datetime.now().strftime("%H:%M")
    send_kb(chat_id,
        f"👋 <b>Rayyon Admin Bot</b>  <i>{now}</i>\n\nNimani ko'rmoqchisiz?",
        [
            [{"text": "📦 Buyurtmalar",  "callback_data": "orders"},
             {"text": "📅 Bronlar",      "callback_data": "reservations"}],
            [{"text": "🪑 Stollar",      "callback_data": "tables"},
             {"text": "📦 Inventar",     "callback_data": "inventory"}],
            [{"text": "💼 Smena",        "callback_data": "shifts"},
             {"text": "💳 Mijozlar",     "callback_data": "customers"}],
            [{"text": "📊 Bugun",        "callback_data": "today"},
             {"text": "📈 Hafta 📉",     "callback_data": "week"},
             {"text": "🗓 Oy",           "callback_data": "month"}],
            [{"text": "👥 Xodimlar",     "callback_data": "staff"},
             {"text": "📊 Top taomlar",  "callback_data": "top_menu"}],
        ]
    )


def show_orders(chat_id):
    items = api("GET", "/api/orders?status=new")
    if not isinstance(items, list) or not items:
        send_kb(chat_id, "📦 Yangi buyurtmalar yo'q.",
                [[{"text": "🏠 Menyu", "callback_data": "main"}]])
        return
    for o in items[:10]:
        txt = (
            f"📦 <b>Buyurtma #{o['id']}</b>\n"
            f"🍽 {o.get('item_name','')} x{o.get('quantity',1)}\n"
            f"💰 {int(o.get('total_price',0)):,} so'm\n"
            f"👤 {o.get('customer_name','')} · {o.get('customer_phone','')}\n"
            + (f"📝 {o['note']}\n" if o.get("note") else "")
            + f"📊 {STATUS_LABELS.get(o.get('status'), o.get('status',''))}"
        )
        btns = [[
            {"text": "✅ Tasdiqlash", "callback_data": f"ord_confirmed_{o['id']}"},
            {"text": "✔️ Bajarildi",  "callback_data": f"ord_done_{o['id']}"},
            {"text": "❌ Bekor",      "callback_data": f"ord_cancelled_{o['id']}"},
        ]]
        send_kb(chat_id, txt, btns)


def show_reservations(chat_id):
    items = api("GET", "/api/reservations")
    if not isinstance(items, list):
        send_kb(chat_id, "📅 Bronlar yo'q.",
                [[{"text": "🏠 Menyu", "callback_data": "main"}]])
        return
    new_only = [r for r in items if r.get("status") in ("new", "confirmed")][:10]
    if not new_only:
        send_kb(chat_id, "📅 Yangi bronlar yo'q.",
                [[{"text": "🏠 Menyu", "callback_data": "main"}]])
        return
    for r in new_only:
        txt = (
            f"📅 <b>Bron #{r['id']}</b>\n"
            f"👤 {r.get('customer_name','')} · {r.get('customer_phone','')}\n"
            f"📆 {r.get('date','')} {r.get('time','')}\n"
            f"👥 {r.get('guests',2)} mehmon\n"
            + (f"📝 {r['note']}\n" if r.get("note") else "")
            + f"📊 {STATUS_LABELS.get(r.get('status'), r.get('status',''))}"
        )
        btns = [[
            {"text": "✅ Tasdiqlash", "callback_data": f"res_confirmed_{r['id']}"},
            {"text": "❌ Bekor",      "callback_data": f"res_cancelled_{r['id']}"},
        ]]
        send_kb(chat_id, txt, btns)


def show_tables(chat_id):
    tables = api("GET", "/api/tables")
    if not isinstance(tables, list):
        send_msg(chat_id, "❌ Stollar ma'lumoti olinmadi.")
        return
    occupied = [t for t in tables if t.get("status") != "free"]
    free_ct  = len(tables) - len(occupied)
    if not occupied:
        send_kb(chat_id, f"🪑 Hamma {len(tables)} ta stol bo'sh.",
                [[{"text": "🏠 Menyu", "callback_data": "main"}]])
        return
    lines = [f"🪑 <b>Stollar ({len(occupied)}/{len(tables)} band)</b>\n"]
    for t in occupied:
        mins = t.get("minutes_open", 0) or 0
        time_str = f"{mins//60}s {mins%60}d" if mins >= 60 else f"{mins}d"
        overtime = "⚠ " if mins > 120 else ""
        status_icon = "🧾" if t.get("status") == "bill_requested" else "🔴"
        amt = f"{int(t.get('total_amount',0)):,} so'm" if t.get("total_amount") else "—"
        waiter = t.get("waiter_name", "")
        lines.append(
            f"{status_icon} <b>Stol #{t['number']}</b> — {overtime}{time_str} — {amt}"
            + (f" | 👤{waiter}" if waiter else "")
        )
    lines.append(f"\n✅ Bo'sh stollar: {free_ct} ta")
    send_kb(chat_id, "\n".join(lines),
            [[{"text": "🔄 Yangilash", "callback_data": "tables"},
              {"text": "🏠 Menyu",     "callback_data": "main"}]])


def show_shifts(chat_id):
    shifts = api("GET", "/api/shifts?status=open&limit=5")
    tables = api("GET", "/api/tables")
    occupied_ct  = sum(1 for t in (tables if isinstance(tables, list) else []) if t.get("status") != "free")
    total_amount = sum(int(t.get("total_amount") or 0) for t in (tables if isinstance(tables, list) else []))

    if not isinstance(shifts, list) or not shifts:
        send_kb(chat_id,
            f"💼 <b>Joriy holat</b>\n\n"
            f"🪑 Band stollar: <b>{occupied_ct}</b> ta\n"
            f"💰 Kutilayotgan: <b>{total_amount:,} so'm</b>\n"
            f"ℹ️ Ochiq smena topilmadi.",
            [[{"text": "🪑 Stollar", "callback_data": "tables"},
              {"text": "🏠 Menyu",   "callback_data": "main"}]])
        return

    lines = ["💼 <b>Ochiq smenalar</b>\n"]
    btns  = []
    for s in shifts:
        cashier  = s.get("cashier_name", "?")
        opened   = str(s.get("opened_at", ""))[:16]
        sessions = s.get("sessions_count", 0)
        revenue  = int(s.get("total_revenue") or s.get("total_collected") or 0)
        sid      = s.get("id")
        lines.append(
            f"👤 <b>{cashier}</b> — {opened}\n"
            f"   🧾 {sessions} xizmat · 💰 {revenue:,} so'm"
        )
        if sid:
            btns.append([{"text": f"🔒 Smenani yopish ({cashier})",
                          "callback_data": f"shift_close_{sid}"}])
    lines.append(f"\n🪑 Band stollar: <b>{occupied_ct}</b> ta")
    lines.append(f"💰 Kutilayotgan: <b>{total_amount:,} so'm</b>")
    btns.append([{"text": "🔄 Yangilash", "callback_data": "shifts"},
                 {"text": "🏠 Menyu",     "callback_data": "main"}])
    send_kb(chat_id, "\n".join(lines), btns)


def close_shift(chat_id, shift_id):
    res = api("POST", f"/api/shift/{shift_id}/close", {})
    if not res or not (res.get('ok') or res.get('shift')):
        send_kb(chat_id, "❌ Smena yopilmadi.",
                [[{"text": "💼 Smena", "callback_data": "shifts"},
                  {"text": "🏠 Menyu", "callback_data": "main"}]])
        return
    shift    = res.get('shift') or res
    revenue  = int(shift.get('total_collected') or shift.get('total_revenue') or 0)
    sessions = shift.get('sessions_count', 0)
    opened   = str(shift.get('opened_at', ''))[:16]
    closed   = str(shift.get('closed_at', datetime.datetime.now().isoformat()))[:16]
    send_kb(chat_id,
        f"✅ <b>Smena yopildi!</b>\n\n"
        f"🕐 Boshlangan: {opened}\n"
        f"🕑 Yopilgan:   {closed}\n"
        f"🪑 Xizmatlar:  {sessions} ta\n"
        f"💰 Tushum:     <b>{revenue:,} so'm</b>",
        [[{"text": "📊 Bugun", "callback_data": "today"},
          {"text": "🏠 Menyu", "callback_data": "main"}]])


def show_staff(chat_id):
    staff_list = api("GET", "/api/staff")
    if not isinstance(staff_list, list):
        send_msg(chat_id, "❌ Xodimlar ma'lumoti olinmadi.")
        return
    active = [s for s in staff_list if s.get("active", 1)]
    if not active:
        send_kb(chat_id, "👥 Aktiv xodimlar yo'q.",
                [[{"text": "🏠 Menyu", "callback_data": "main"}]])
        return
    role_icons = {
        "admin": "👑", "director": "🏆", "manager": "📋",
        "cashier": "💳", "waiter": "🍽", "kitchen": "👨‍🍳",
        "cook": "🧑‍🍳", "chef": "👨‍🍳", "accountant": "📊",
        "cleaner": "🧹",
    }
    lines = [f"👥 <b>Xodimlar ({len(active)} ta)</b>\n"]
    for s in active[:20]:
        role = s.get("role", "?")
        icon = role_icons.get(role, "👤")
        name = s.get("name", "?")
        lines.append(f"{icon} <b>{name}</b> — {role}")
    send_kb(chat_id, "\n".join(lines),
            [[{"text": "🔄 Yangilash", "callback_data": "staff"},
              {"text": "🏠 Menyu",     "callback_data": "main"}]])


def show_inventory(chat_id):
    items = api("GET", "/api/inventory")
    if not isinstance(items, list):
        send_msg(chat_id, "❌ Inventar ma'lumoti olinmadi.")
        return
    low = [i for i in items if (i.get("quantity") or 0) <= (i.get("min_quantity") or 0)]
    if not low:
        send_kb(chat_id, f"📦 Inventar yaxshi — {len(items)} ta mahsulot, hammasi yetarli.",
                [[{"text": "🏠 Menyu", "callback_data": "main"}]])
        return
    lines = [f"⚠️ <b>Kam mahsulotlar ({len(low)} ta)</b>\n"]
    for i in low[:15]:
        lines.append(f"🔴 {i['name']}: <b>{i.get('quantity',0)} {i.get('unit','')}</b> "
                     f"(min: {i.get('min_quantity',0)})")
    send_kb(chat_id, "\n".join(lines),
            [[{"text": "🔄 Yangilash", "callback_data": "inventory"},
              {"text": "🏠 Menyu",     "callback_data": "main"}]])


def show_customers(chat_id):
    customers = api("GET", "/api/customers")
    if not isinstance(customers, list):
        send_msg(chat_id, "❌ Mijozlar ma'lumoti olinmadi.")
        return
    if not customers:
        send_kb(chat_id, "💳 Loyalty mijozlar ro'yxati bo'sh.",
                [[{"text": "🏠 Menyu", "callback_data": "main"}]])
        return
    top = sorted(customers, key=lambda x: x.get("total_spent", 0), reverse=True)[:10]
    lines = [f"💳 <b>Top {len(top)} mijoz</b>\n"]
    for i, c in enumerate(top, 1):
        name   = c.get("name") or c.get("phone", "?")
        spent  = int(c.get("total_spent", 0))
        visits = c.get("visits", 0)
        disc   = c.get("discount_pct", 0)
        lines.append(
            f"{i}. {name} — {spent:,} so'm · {visits} tashrif"
            + (f" · {disc}% chegirma" if disc else "")
        )
    send_kb(chat_id, "\n".join(lines),
            [[{"text": "🏠 Menyu", "callback_data": "main"}]])


def show_today(chat_id):
    show_period(chat_id, "daily", "Bugungi")


def show_period(chat_id, period: str, label: str):
    stats = api("GET", f"/api/analytics/summary?period={period}")
    if not stats or not isinstance(stats, dict):
        send_msg(chat_id, "❌ Statistika olinmadi.")
        return
    revenue  = int(stats.get("revenue", 0))
    expenses = int(stats.get("expenses", 0))
    profit   = revenue - expenses
    sessions = stats.get("sessions", 0)
    items_ct = stats.get("items_sold", 0)
    avg      = int(stats.get("avg_bill", 0))
    cb_key   = {"daily": "today", "weekly": "week", "monthly": "month"}.get(period, "today")

    chart = ""
    if period == "weekly":
        # /api/analytics dict qaytaradi — chart[] maydoni ichida kunlik ma'lumotlar
        days_data = stats.get("chart", [])
        if days_data:
            max_rev = max((int(d.get("rev", 0)) for d in days_data), default=1) or 1
            lines   = ["\n<b>Haftalik grafik:</b>"]
            for d in days_data[-7:]:
                rev  = int(d.get("rev", 0))
                day  = str(d.get("day", ""))[-5:]
                bar  = _ascii_bar(rev, max_rev)
                lines.append(f"<code>{day} {bar} {rev//1000}k</code>")
            chart = "\n".join(lines)

    send_kb(chat_id,
        f"📊 <b>{label} hisobot</b>\n\n"
        f"💰 Daromad:    <b>{revenue:,} so'm</b>\n"
        f"📤 Xarajat:    <b>{expenses:,} so'm</b>\n"
        f"📈 Foyda:      <b>{profit:,} so'm</b>\n"
        f"🪑 Xizmatlar:  <b>{sessions}</b> ta\n"
        f"🍽 Taomlar:    <b>{items_ct}</b> ta sotilgan\n"
        f"🧾 O'rtacha:   <b>{avg:,} so'm</b>"
        + chart,
        [[{"text": "🔄 Yangilash", "callback_data": cb_key},
          {"text": "🏠 Menyu",     "callback_data": "main"}]])


def show_top_menu(chat_id):
    stats = api("GET", "/api/analytics?period=monthly")
    if not isinstance(stats, (list, dict)):
        send_msg(chat_id, "❌ Ma'lumot olinmadi."); return
    data = stats if isinstance(stats, list) else stats.get("top_items", [])
    if not data:
        send_kb(chat_id, "📊 Hozircha ma'lumot yo'q.",
                [[{"text": "🏠 Menyu", "callback_data": "main"}]]); return
    max_qty = max((int(d.get("count") or d.get("quantity") or 1) for d in data), default=1)
    lines   = ["📊 <b>Top taomlar (bu oy)</b>\n"]
    medals  = ["🥇", "🥈", "🥉"]
    for i, d in enumerate(data[:10]):
        name  = d.get("name") or d.get("item_name", "?")
        qty   = int(d.get("count") or d.get("quantity") or 0)
        rev   = int(d.get("revenue") or d.get("total_revenue") or 0)
        bar   = _ascii_bar(qty, max_qty, 8)
        medal = medals[i] if i < 3 else f"{i+1}."
        lines.append(f"{medal} <code>{bar}</code> {name} — {qty} ta · {rev//1000}k so'm")
    send_kb(chat_id, "\n".join(lines),
            [[{"text": "🔄 Yangilash", "callback_data": "top_menu"},
              {"text": "🏠 Menyu",     "callback_data": "main"}]])
