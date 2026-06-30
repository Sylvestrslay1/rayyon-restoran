"""Xodim boti: login, ofitsiant, oshpaz, kassir."""
from core import (
    api, send_kb, send_msg,
    set_state, clear_state,
    get_staff, staff_logout, _staff_sessions, _waiter_carts,
    get_menu, CATS, ROLE_ICONS, WAITER_ROLES, KITCHEN_ROLES, CASHIER_ROLES,
    set_user_role,
)


def staff_login_start(chat_id):
    set_state(chat_id, 'staff_pin')
    send_kb(chat_id,
        "🔐 <b>Xodim paneli</b>\n\nPIN kodingizni kiriting:",
        [[{"text": "❌ Bekor", "callback_data": "c_main"}]])


def staff_pin_submit(chat_id, pin):
    res = api("POST", "/api/staff/login", {"pin": pin})
    clear_state(chat_id)
    if not res or not res.get('ok'):
        send_kb(chat_id,
            "❌ PIN noto'g'ri yoki xodim topilmadi.",
            [[{"text": "🔄 Qayta urinish", "callback_data": "s_login"},
              {"text": "🏠 Bosh menyu",    "callback_data": "c_main"}]])
        return
    staff = {'name': res['name'], 'role': res['role'], 'id': res['id'], 'pin': pin}
    _staff_sessions[chat_id] = staff
    set_user_role(chat_id, 'staff')
    api("POST", "/api/staff/checkin", {"pin": pin})
    staff_main_menu(chat_id, staff)


def staff_main_menu(chat_id, staff=None):
    if staff is None:
        staff = get_staff(chat_id)
    if not staff:
        staff_login_start(chat_id); return
    role = staff['role']
    icon = ROLE_ICONS.get(role, '👤')

    if role in WAITER_ROLES:
        btns = [
            [{"text": "🪑 Mening stollarim",  "callback_data": "s_my_tables"},
             {"text": "✅ Tayyor buyurtmalar", "callback_data": "s_ready"}],
            [{"text": "📋 Barcha stollar",     "callback_data": "s_all_tables"}],
            [{"text": "🔓 Chiqish",            "callback_data": "s_logout"}],
        ]
    elif role in KITCHEN_ROLES:
        btns = [
            [{"text": "🍳 Navbatdagi taomlar", "callback_data": "s_kitchen"}],
            [{"text": "✅ Tayyor buyurtmalar",  "callback_data": "s_ready"}],
            [{"text": "🔓 Chiqish",            "callback_data": "s_logout"}],
        ]
    elif role in CASHIER_ROLES:
        btns = [
            [{"text": "🪑 Stollar", "callback_data": "s_all_tables"},
             {"text": "💼 Smena",  "callback_data": "s_shift"}],
            [{"text": "🔓 Chiqish", "callback_data": "s_logout"}],
        ]
    else:
        btns = [
            [{"text": "🪑 Stollar",  "callback_data": "s_all_tables"}],
            [{"text": "🔓 Chiqish", "callback_data": "s_logout"}],
        ]
    send_kb(chat_id,
        f"{icon} <b>{staff['name']}</b> — Xush kelibsiz!\n"
        f"Rol: <i>{role}</i>",
        btns)


# ── Ofitsiant — stollar ───────────────────────────────────────

def show_waiter_tables(chat_id, my_only=True):
    staff  = get_staff(chat_id)
    tables = api("GET", "/api/tables")
    if not isinstance(tables, list):
        send_msg(chat_id, "❌ Stollar yuklanmadi."); return

    free_ct = sum(1 for t in tables if t.get('status') == 'free')
    if my_only and staff:
        active = [t for t in tables if t.get('status') != 'free'
                  and (t.get('waiter_name') == staff['name']
                       or t.get('waiter_id') == staff['id'])]
        title  = "🪑 Mening stollarim"
        if not active:
            active = [t for t in tables if t.get('status') != 'free']
            title  = "🪑 Band stollar (hammasi)"
    else:
        active = [t for t in tables if t.get('status') != 'free']
        title  = "🪑 Band stollar"

    if not active:
        send_kb(chat_id, f"🪑 Hamma {len(tables)} ta stol bo'sh.",
                [[{"text": "🏠 Panel", "callback_data": "s_main"}]])
        return

    lines = [f"{title} ({len(active)} ta)\n"]
    btns  = []
    for t in active:
        icon = "🧾" if t.get('status') == 'bill_requested' else "🔴"
        amt  = f"{int(t.get('total_amount', 0)):,}" if t.get('total_amount') else "—"
        mins = t.get('minutes_open') or 0
        lines.append(f"{icon} <b>#{t['number']}</b> — {mins}d — {amt} so'm")
        btns.append([{"text": f"Stol #{t['number']}  {amt} so'm",
                      "callback_data": f"s_table_{t['id']}"}])
    lines.append(f"\n✅ Bo'sh: {free_ct} ta")
    btns.append([{"text": "🔄 Yangilash", "callback_data": "s_my_tables" if my_only else "s_all_tables"},
                 {"text": "🏠 Panel",     "callback_data": "s_main"}])
    send_kb(chat_id, "\n".join(lines), btns)


def show_table_detail(chat_id, table_id):
    tables = api("GET", "/api/tables")
    if not isinstance(tables, list):
        send_msg(chat_id, "❌ Xato."); return
    table = next((t for t in tables if t['id'] == table_id), None)
    if not table:
        send_msg(chat_id, "❌ Stol topilmadi."); return

    sid = table.get('current_session_id')
    if not sid:
        send_kb(chat_id,
            f"🪑 <b>Stol #{table['number']}</b> — Bo'sh",
            [[{"text": "▶ Stolni ochish", "callback_data": f"s_open_{table_id}"},
              {"text": "◀ Orqaga",        "callback_data": "s_my_tables"}]])
        return

    session = api("GET", f"/api/session/{sid}")
    if not isinstance(session, dict):
        send_msg(chat_id, "❌ Sessiya yuklanmadi."); return

    items  = [i for i in (session.get('items') or []) if i.get('status') != 'cancelled']
    s_icon = {'pending': '⏳', 'cooking': '🍳', 'ready': '✅', 'served': '✔️'}
    lines  = [f"🪑 <b>Stol #{table['number']}</b>\n"]
    for i in items:
        lines.append(f"  {s_icon.get(i.get('status',''), '•')} "
                     f"{i.get('item_emoji','🍽')} {i.get('item_name','')} ×{i.get('quantity',1)}")
    total = int(session.get('grand_total') or 0)
    lines.append(f"\n💰 Jami: <b>{total:,} so'm</b>")
    send_kb(chat_id, "\n".join(lines), [
        [{"text": "➕ Buyurtma qo'shish", "callback_data": f"s_add_order_{table_id}_{sid}"}],
        [{"text": "🧾 Hisob so'rash",     "callback_data": f"s_bill_{sid}"}],
        [{"text": "◀ Orqaga",             "callback_data": "s_my_tables"}],
    ])


def waiter_open_table(chat_id, table_id):
    staff = get_staff(chat_id)
    if not staff:
        staff_login_start(chat_id); return
    res = api("POST", "/api/session/open", {
        "table_id":    table_id,
        "waiter_name": staff['name'],
        "waiter_pin":  staff['pin'],
    })
    if res.get('ok') or res.get('session_id'):
        send_kb(chat_id, "✅ Stol ochildi!",
                [[{"text": "➕ Buyurtma qo'shish", "callback_data": f"s_table_{table_id}"},
                  {"text": "🪑 Stollar",           "callback_data": "s_my_tables"}]])
    else:
        send_kb(chat_id, "❌ Stol ochilmadi (ehtimol allaqachon band).",
                [[{"text": "🪑 Stollar", "callback_data": "s_my_tables"}]])


def waiter_bill(chat_id, session_id):
    res = api("POST", f"/api/session/{session_id}/bill", {})
    if res and (res.get('ok') or res.get('status')):
        send_kb(chat_id, "✅ Kassirga hisob so'rovi yuborildi!",
                [[{"text": "🪑 Stollar", "callback_data": "s_my_tables"},
                  {"text": "🏠 Panel",  "callback_data": "s_main"}]])
    else:
        send_kb(chat_id, "❌ Hisob so'rovi yuborilmadi.",
                [[{"text": "◀ Orqaga", "callback_data": "s_my_tables"}]])


# ── Ofitsiant — buyurtma qo'shish (stol uchun) ───────────────

def waiter_order_start(chat_id, table_id, session_id):
    _waiter_carts[chat_id] = {'table_id': table_id, 'session_id': session_id, 'items': []}
    btns = [[{"text": name, "callback_data": f"sw_cat_{cat}"}] for cat, name in CATS]
    btns.append([{"text": "❌ Bekor", "callback_data": f"s_table_{table_id}"}])
    send_kb(chat_id, "🍽 Kategoriya tanlang:", btns)


def waiter_show_items(chat_id, cat):
    wc       = _waiter_carts.get(chat_id, {})
    items    = [i for i in get_menu() if i.get('category') == cat and i.get('available')]
    cat_name = dict(CATS).get(cat, cat)
    if not items:
        send_kb(chat_id, f"😔 {cat_name} da hozircha taom yo'q.",
                [[{"text": "◀ Orqaga", "callback_data": "sw_menu"}]]); return
    lines = [f"🍽 <b>{cat_name}</b>\n"]
    btns  = []
    for i in items[:12]:
        lines.append(f"{i.get('emoji','🍽')} {i['name']} — {int(i['price']):,} so'm")
        btns.append([{"text": f"+ {i.get('emoji','')} {i['name']}",
                      "callback_data": f"sw_add_{i['id']}"}])
    wi  = wc.get('items', [])
    nav = [{"text": "◀ Kategoriyalar", "callback_data": "sw_menu"}]
    if wi:
        nav.append({"text": f"🛒 Savat ({len(wi)})", "callback_data": "sw_cart"})
    btns.append(nav)
    send_kb(chat_id, "\n".join(lines), btns)


def waiter_add_item(chat_id, item_id):
    wc = _waiter_carts.get(chat_id)
    if not wc:
        send_msg(chat_id, "❌ Avval stol tanlang."); return
    item = next((i for i in get_menu() if i['id'] == item_id), None)
    if not item:
        send_msg(chat_id, "❌ Taom topilmadi."); return
    items = wc['items']
    for c in items:
        if c['id'] == item_id:
            c['qty'] += 1; break
    else:
        items.append({'id': item['id'], 'name': item['name'],
                      'emoji': item.get('emoji', '🍽'), 'price': item['price'], 'qty': 1})
    send_kb(chat_id,
        f"✅ <b>{item.get('emoji','')} {item['name']}</b> qo'shildi! (Savat: {len(items)} ta)",
        [[{"text": "🛒 Savatni ko'rish", "callback_data": "sw_cart"},
          {"text": "➕ Yana qo'shish",   "callback_data": f"sw_cat_{item.get('category','milliy')}"}]])


def waiter_show_cart(chat_id):
    wc = _waiter_carts.get(chat_id)
    if not wc or not wc.get('items'):
        send_kb(chat_id, "🛒 Savat bo'sh.",
                [[{"text": "🍽 Menyu", "callback_data": "sw_menu"},
                  {"text": "🏠 Panel", "callback_data": "s_main"}]]); return
    items = wc['items']
    total = sum(c['price'] * c['qty'] for c in items)
    lines = [f"🛒 <b>Buyurtma — Stol #{wc.get('table_id','?')}</b>\n"]
    for c in items:
        lines.append(f"{c.get('emoji','🍽')} {c['name']} ×{c['qty']} — {int(c['price']*c['qty']):,} so'm")
    lines.append(f"\n💰 Jami: <b>{int(total):,} so'm</b>")
    send_kb(chat_id, "\n".join(lines), [
        [{"text": "✅ Oshxonaga yuborish", "callback_data": "sw_submit"}],
        [{"text": "🍽 Yana qo'shish",     "callback_data": "sw_menu"},
         {"text": "🗑 Tozalash",          "callback_data": "sw_clear"}],
    ])


def waiter_submit_order(chat_id):
    staff = get_staff(chat_id)
    wc    = _waiter_carts.get(chat_id)
    if not wc or not wc.get('items') or not staff:
        send_msg(chat_id, "❌ Savat bo'sh yoki kirish talab qilinadi."); return
    sid   = wc['session_id']
    items = [{'menu_item_id': c['id'], 'name': c['name'], 'emoji': c['emoji'],
              'price': c['price'], 'quantity': c['qty'],
              'comment': '', 'category': '', 'waiter_name': staff['name']}
             for c in wc['items']]
    res = api("POST", f"/api/session/{sid}/order",
              {"items": items, "waiter_pin": staff['pin']})
    if res and (res.get('ok') or res.get('added')):
        _waiter_carts.pop(chat_id, None)
        send_kb(chat_id, "✅ Buyurtma oshxonaga yuborildi!",
                [[{"text": "🪑 Stollar", "callback_data": "s_my_tables"},
                  {"text": "🏠 Panel",  "callback_data": "s_main"}]])
    else:
        send_kb(chat_id, "❌ Buyurtma yuborilmadi.",
                [[{"text": "🔄 Qayta", "callback_data": "sw_cart"}]])


# ── Oshpaz ────────────────────────────────────────────────────

def show_kitchen_orders(chat_id):
    groups = api("GET", "/api/kitchen")
    if not isinstance(groups, list) or not groups:
        send_kb(chat_id, "✅ Hozircha barcha buyurtmalar bajarildi!",
                [[{"text": "🔄 Yangilash", "callback_data": "s_kitchen"},
                  {"text": "🏠 Panel",    "callback_data": "s_main"}]]); return
    lines = ["🍳 <b>Navbatdagi buyurtmalar</b>\n"]
    btns  = []
    for g in groups[:5]:
        lines.append(f"🪑 <b>Stol #{g['table']}</b>:")
        for item in (g.get('items') or [])[:6]:
            s_icon = '🍳' if item['status'] == 'cooking' else '⏳'
            lines.append(f"  {s_icon} {item.get('item_emoji','🍽')} {item.get('item_name','')} ×{item.get('quantity',1)}")
            if item['status'] == 'pending':
                btns.append([{"text": f"▶ Boshlash: {item.get('item_name','')}",
                              "callback_data": f"s_cook_{g['session_id']}_{item['id']}"}])
            else:
                btns.append([{"text": f"✓ Tayyor: {item.get('item_name','')}",
                              "callback_data": f"s_ritem_{g['session_id']}_{item['id']}"}])
    btns.append([{"text": "🔄 Yangilash", "callback_data": "s_kitchen"},
                 {"text": "🏠 Panel",    "callback_data": "s_main"}])
    send_kb(chat_id, "\n".join(lines), btns)


def show_ready_items(chat_id):
    items = api("GET", "/api/kitchen/ready")
    if not isinstance(items, list) or not items:
        send_kb(chat_id, "✅ Tayyor buyurtmalar yo'q.",
                [[{"text": "🔄 Yangilash", "callback_data": "s_ready"},
                  {"text": "🏠 Panel",    "callback_data": "s_main"}]]); return
    lines = [f"✅ <b>Tayyor — {len(items)} ta</b>\n"]
    btns  = []
    for i in items[:10]:
        lines.append(f"🪑 Stol #{i.get('table_number','?')} — "
                     f"{i.get('item_emoji','🍽')} {i.get('item_name','')} ×{i.get('quantity',1)}")
        btns.append([{"text": f"✔ Berildi — Stol #{i.get('table_number','?')} {i.get('item_name','')}",
                      "callback_data": f"s_served_{i.get('session_id')}_{i.get('id')}"}])
    btns.append([{"text": "🔄 Yangilash", "callback_data": "s_ready"},
                 {"text": "🏠 Panel",    "callback_data": "s_main"}])
    send_kb(chat_id, "\n".join(lines), btns)


def update_item_status(chat_id, session_id, item_id, status):
    res   = api("PUT", f"/api/session/{session_id}/item/{item_id}/status", {"status": status})
    label = {'cooking': '🍳 Pishirilmoqda', 'ready': '✅ Tayyor', 'served': '✔️ Berildi'}.get(status, status)
    if res and res.get('ok'):
        back = "s_kitchen" if status in ('cooking', 'ready') else "s_ready"
        send_kb(chat_id, f"✅ {label}",
                [[{"text": "🔄 Orqaga", "callback_data": back},
                  {"text": "🏠 Panel", "callback_data": "s_main"}]])
    else:
        send_kb(chat_id, "❌ Holat yangilanmadi.",
                [[{"text": "🔄 Qayta", "callback_data": "s_kitchen"}]])


# ── Smena (kassir/manager) ────────────────────────────────────

def show_shift_status(chat_id):
    staff = get_staff(chat_id)
    if not staff:
        staff_login_start(chat_id); return
    res = api("POST", "/api/shift/current", {"pin": staff["pin"]})
    s = res.get("shift") if isinstance(res, dict) else None
    if not s or not s.get('id'):
        send_kb(chat_id, "💼 Ochiq smena topilmadi.",
                [[{"text": "🏠 Panel", "callback_data": "s_main"}]]); return
    revenue = int(s.get('total_collected') or s.get('total_revenue') or 0)
    opened  = str(s.get('opened_at', ''))[:16]
    send_kb(chat_id,
        f"💼 <b>Joriy smena</b>\n\n"
        f"👤 Kassir: {s.get('cashier_name','?')}\n"
        f"🕐 Boshlangan: {opened}\n"
        f"💰 Tushumlar: {revenue:,} so'm",
        [[{"text": "🔄 Yangilash", "callback_data": "s_shift"},
          {"text": "🏠 Panel",    "callback_data": "s_main"}]])


# ── Xodim callback handler ────────────────────────────────────

def handle_staff_callback(chat_id, data):
    if data == "s_login":
        staff_login_start(chat_id)
    elif data == "s_main":
        staff_main_menu(chat_id)
    elif data == "s_logout":
        staff_logout(chat_id)
        send_kb(chat_id, "👋 Smena yopildi. Xayr!",
                [[{"text": "🔐 Qayta kirish", "callback_data": "s_login"},
                  {"text": "🏠 Bosh menyu",   "callback_data": "c_main"}]])
    elif data == "s_my_tables":
        show_waiter_tables(chat_id, my_only=True)
    elif data == "s_all_tables":
        show_waiter_tables(chat_id, my_only=False)
    elif data.startswith("s_table_"):
        try: show_table_detail(chat_id, int(data[8:]))
        except ValueError: pass
    elif data.startswith("s_open_"):
        try: waiter_open_table(chat_id, int(data[7:]))
        except ValueError: pass
    elif data.startswith("s_bill_"):
        try: waiter_bill(chat_id, int(data[7:]))
        except ValueError: pass
    elif data.startswith("s_add_order_"):
        parts = data[12:].split('_', 1)
        if len(parts) == 2:
            try: waiter_order_start(chat_id, int(parts[0]), int(parts[1]))
            except ValueError: pass
    elif data == "sw_menu":
        btns = [[{"text": name, "callback_data": f"sw_cat_{cat}"}] for cat, name in CATS]
        wc   = _waiter_carts.get(chat_id, {})
        if wc.get('items'):
            btns.append([{"text": f"🛒 Savat ({len(wc['items'])})", "callback_data": "sw_cart"}])
        btns.append([{"text": "❌ Bekor", "callback_data": "s_my_tables"}])
        send_kb(chat_id, "🍽 Kategoriya tanlang:", btns)
    elif data.startswith("sw_cat_"):
        waiter_show_items(chat_id, data[7:])
    elif data.startswith("sw_add_"):
        try: waiter_add_item(chat_id, int(data[7:]))
        except ValueError: pass
    elif data == "sw_cart":
        waiter_show_cart(chat_id)
    elif data == "sw_clear":
        wc = _waiter_carts.get(chat_id, {})
        if wc:
            wc['items'] = []
        send_kb(chat_id, "🗑 Savat tozalandi.",
                [[{"text": "🍽 Menyu", "callback_data": "sw_menu"},
                  {"text": "🏠 Panel", "callback_data": "s_main"}]])
    elif data == "sw_submit":
        waiter_submit_order(chat_id)
    elif data == "s_kitchen":
        show_kitchen_orders(chat_id)
    elif data == "s_ready":
        show_ready_items(chat_id)
    elif data.startswith("s_cook_"):
        parts = data[7:].split('_', 1)
        if len(parts) == 2:
            try: update_item_status(chat_id, int(parts[0]), int(parts[1]), 'cooking')
            except ValueError: pass
    elif data.startswith("s_ritem_"):
        parts = data[8:].split('_', 1)
        if len(parts) == 2:
            try: update_item_status(chat_id, int(parts[0]), int(parts[1]), 'ready')
            except ValueError: pass
    elif data.startswith("s_served_"):
        parts = data[9:].split('_', 1)
        if len(parts) == 2:
            try: update_item_status(chat_id, int(parts[0]), int(parts[1]), 'served')
            except ValueError: pass
    elif data == "s_shift":
        show_shift_status(chat_id)
