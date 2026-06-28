"""Mijoz boti: til tanlash, menyu, buyurtma (session API), bron, loyalty, aloqa."""
import datetime, threading, urllib.parse
from core import (
    api, api_raw, send_kb, send_msg,
    get_state, set_state, clear_state,
    get_cart, cart_add, cart_clear, cart_total,
    get_menu, CATS,
    get_lang, set_lang,
    get_cust_name, set_cust_name,
    get_cust_phone, set_cust_phone,
    get_table, set_table,
    log, _phone_valid,
)
from i18n import t, cats as i18n_cats

# ── Inaktivlik taymerlari ─────────────────────────────────────
_timers: dict = {}  # chat_id -> threading.Timer


def _reset_timer(chat_id):
    if chat_id in _timers:
        _timers[chat_id].cancel()
    lang = get_lang(chat_id) or 'uz'
    timer = threading.Timer(600, _suggest_popular, args=(chat_id, lang))
    timer.daemon = True
    _timers[chat_id] = timer
    timer.start()


def _cancel_timer(chat_id):
    if chat_id in _timers:
        _timers[chat_id].cancel()
        _timers.pop(chat_id, None)


def _suggest_popular(chat_id, lang):
    """10 daqiqa inaktivlik → mashhur taomlarni taklif qil."""
    _timers.pop(chat_id, None)
    items = api_raw("GET", "/api/menu/popular?limit=5")
    if not isinstance(items, list) or not items:
        send_kb(chat_id, t(lang, 'popular_suggest', items='🍽 Menyuimizni ko\'ring!'),
                [[{"text": t(lang, 'menu'), "callback_data": "c_menu"}]])
        return
    lines = []
    btns  = []
    for it in items[:5]:
        emoji = it.get('emoji', '🍽')
        name  = it.get('name', '')
        price = int(it.get('price') or 0)
        lines.append(f"{emoji} {name} — {price:,} so'm")
        btns.append([{"text": f"+ {emoji} {name}", "callback_data": f"c_add_{it.get('id',0)}"}])
    btns.append([{"text": t(lang, 'home'), "callback_data": "c_main"}])
    send_kb(chat_id, t(lang, 'popular_suggest', items='\n'.join(lines)), btns)


# ── Kirish nuqtasi ────────────────────────────────────────────

def customer_start(chat_id, table_num=None):
    """QR yoki /start orqali kirishda chaqiriladi."""
    if table_num:
        set_table(chat_id, table_num)
    lang = get_lang(chat_id)
    if not lang:
        _lang_select(chat_id)
        return
    name = get_cust_name(chat_id)
    if not name:
        _ask_name(chat_id, lang)
        return
    customer_main(chat_id)


def _lang_select(chat_id):
    send_kb(chat_id,
        '🌐 Tilni tanlang / Выберите язык / Choose language:',
        [[{"text": "🇺🇿 O'zbek",    "callback_data": "c_lang_uz"}],
         [{"text": "🇷🇺 Русский",   "callback_data": "c_lang_ru"}],
         [{"text": "🇬🇧 English",   "callback_data": "c_lang_en"}]])


def _ask_name(chat_id, lang):
    set_state(chat_id, 'cust_name')
    send_msg(chat_id, t(lang, 'ask_name'))


def customer_main(chat_id):
    lang  = get_lang(chat_id) or 'uz'
    name  = get_cust_name(chat_id)
    table = get_table(chat_id)
    cart  = get_cart(chat_id)

    if name:
        greeting = t(lang, 'welcome_back', name=name)
    else:
        greeting = t(lang, 'welcome_new', name='')
        greeting = greeting.split('\n\n')[1] if '\n\n' in greeting else greeting

    prefix = t(lang, 'table_info', table=table) if table else ''
    rows = [
        [{"text": t(lang, 'menu'),    "callback_data": "c_menu"},
         {"text": t(lang, 'bron'),    "callback_data": "c_bron"}],
        [{"text": t(lang, 'ball'),    "callback_data": "c_ball"},
         {"text": "🎁 Aksiyalar",     "callback_data": "c_promos"}],
        [{"text": t(lang, 'contact'), "callback_data": "c_contact"},
         {"text": t(lang, 'staff'),   "callback_data": "s_login"}],
    ]
    if cart:
        rows.insert(0, [{"text": t(lang, 'view_cart', count=len(cart)), "callback_data": "c_cart"}])

    greeting_text = f"{prefix}{greeting}" if name else f"{prefix}👋 <b>Rayyon Restoran</b>\n\n{t(lang, 'menu')} — {t(lang, 'bron')} — {t(lang, 'ball')}"
    send_kb(chat_id, greeting_text, rows)
    _reset_timer(chat_id)


# ── Menyu ─────────────────────────────────────────────────────

def show_cat_menu(chat_id):
    lang = get_lang(chat_id) or 'uz'
    btns = [[{"text": name, "callback_data": f"c_cat_{cat}"}] for cat, name in i18n_cats(lang)]
    cart = get_cart(chat_id)
    if cart:
        btns.append([{"text": t(lang, 'view_cart', count=len(cart)), "callback_data": "c_cart"}])
    btns.append([{"text": t(lang, 'home'), "callback_data": "c_main"}])
    send_kb(chat_id, t(lang, 'choose_cat'), btns)
    _reset_timer(chat_id)


def show_items(chat_id, cat):
    lang     = get_lang(chat_id) or 'uz'
    items    = [i for i in get_menu() if i.get('category') == cat and i.get('available')]
    cat_name = dict(i18n_cats(lang)).get(cat, cat)
    if not items:
        send_kb(chat_id, t(lang, 'empty_cat'),
                [[{"text": t(lang, 'back'), "callback_data": "c_menu"}]]); return
    lines = [f"🍽 <b>{cat_name}</b>\n"]
    btns  = []
    for i in items[:12]:
        lines.append(f"{i.get('emoji','🍽')} {i['name']} — {int(i['price']):,} so'm")
        btns.append([{"text": f"+ {i.get('emoji','')} {i['name']}", "callback_data": f"c_add_{i['id']}"}])
    cart = get_cart(chat_id)
    nav  = [{"text": t(lang, 'back'), "callback_data": "c_menu"}]
    if cart:
        nav.append({"text": t(lang, 'view_cart', count=len(cart)), "callback_data": "c_cart"})
    btns.append(nav)
    send_kb(chat_id, "\n".join(lines), btns)
    _reset_timer(chat_id)


def add_to_cart(chat_id, item_id):
    lang = get_lang(chat_id) or 'uz'
    item = next((i for i in get_menu() if i['id'] == item_id), None)
    if not item:
        send_msg(chat_id, "❌ Taom topilmadi."); return
    cart_add(chat_id, {
        'id': item['id'], 'name': item['name'],
        'emoji': item.get('emoji', '🍽'), 'price': item['price'],
        'category': item.get('category', ''),
    })
    cart = get_cart(chat_id)
    send_kb(chat_id,
        t(lang, 'added_to_cart', emoji=item.get('emoji','🍽'),
          name=item['name'], count=sum(c['qty'] for c in cart)),
        [[{"text": t(lang, 'view_cart', count=len(cart)), "callback_data": "c_cart"},
          {"text": t(lang, 'add_more'),                  "callback_data": f"c_cat_{item.get('category','milliy')}"}],
         [{"text": t(lang, 'home'),                      "callback_data": "c_main"}]])
    _reset_timer(chat_id)


def show_cart(chat_id):
    lang = get_lang(chat_id) or 'uz'
    cart = get_cart(chat_id)
    if not cart:
        send_kb(chat_id, t(lang, 'cart_empty'),
                [[{"text": t(lang, 'menu'), "callback_data": "c_menu"},
                  {"text": t(lang, 'home'), "callback_data": "c_main"}]]); return
    lines = [t(lang, 'cart_header')]
    for c in cart:
        lines.append(f"{c.get('emoji','🍽')} {c['name']} ×{c['qty']} — {int(c['price']*c['qty']):,} so'm")
    lines.append(t(lang, 'cart_total', total=f"{int(cart_total(chat_id)):,}"))
    send_kb(chat_id, "\n".join(lines), [
        [{"text": t(lang, 'order_btn'),  "callback_data": "c_order_start"}],
        [{"text": t(lang, 'clear_cart'), "callback_data": "c_cart_clear"},
         {"text": t(lang, 'menu'),       "callback_data": "c_menu"}],
    ])


# ── Buyurtma oqimi ────────────────────────────────────────────

def order_start(chat_id):
    if not get_cart(chat_id):
        show_cat_menu(chat_id); return
    lang  = get_lang(chat_id) or 'uz'
    phone = get_cust_phone(chat_id)
    if phone:
        # Telefon saqlanган — ism va telefon bor, to'g'ridan tasdiqlash
        _order_show_confirm(chat_id, lang, get_cust_name(chat_id) or '?', phone)
    else:
        set_state(chat_id, 'order_name')
        send_msg(chat_id, t(lang, 'ask_name'))


def order_handle_name(chat_id, name):
    lang = get_lang(chat_id) or 'uz'
    if len(name.strip()) < 2:
        send_msg(chat_id, t(lang, 'name_short')); return
    set_state(chat_id, 'order_phone', {'name': name.strip()})
    send_msg(chat_id, t(lang, 'ask_phone'))


def order_handle_phone(chat_id, phone, data):
    lang = get_lang(chat_id) or 'uz'
    if not _phone_valid(phone):
        msgs = {
            'uz': '📞 Telefon raqami noto\'g\'ri.\nMasalan: +998901234567 yoki 0901234567',
            'ru': '📞 Неверный номер телефона.\nПример: +998901234567',
            'en': '📞 Invalid phone number.\nExample: +998901234567',
        }
        send_msg(chat_id, msgs.get(lang, msgs['uz'])); return
    data['phone'] = phone
    _order_show_confirm(chat_id, lang, data.get('name', ''), phone)


def _order_show_confirm(chat_id, lang, name, phone):
    cart  = get_cart(chat_id)
    lines = []
    for c in cart:
        lines.append(f"  {c.get('emoji','🍽')} {c['name']} ×{c['qty']} — {int(c['price']*c['qty']):,} so'm")
    total = int(cart_total(chat_id))

    # Loyalty chegirmasi tekshirish
    discount_line = ''
    if phone:
        cust = api_raw("GET", f"/api/customers/lookup?phone={urllib.parse.quote(phone)}")
        if isinstance(cust, dict) and cust.get('found'):
            disc = cust.get('customer', {}).get('discount_pct', 0) or 0
            if disc:
                disc_amt = int(total * disc / 100)
                total_after = total - disc_amt
                discount_line = (
                    f"\n🎁 Loyalty chegirma: <b>-{disc}%</b> ({disc_amt:,} so'm)\n"
                    f"💚 To'lov: <b>{total_after:,} so'm</b>"
                )

    set_state(chat_id, 'order_confirm', {'name': name, 'phone': phone})
    confirm_text = t(lang, 'confirm_order', name=name, phone=phone,
                     items='\n'.join(lines), total=f"{total:,}")
    if discount_line:
        confirm_text += discount_line
    send_kb(chat_id, confirm_text,
        [[{"text": t(lang, 'confirm'), "callback_data": "c_order_confirm"},
          {"text": t(lang, 'cancel'),  "callback_data": "c_cart"}]])


def order_submit(chat_id):
    lang  = get_lang(chat_id) or 'uz'
    state = get_state(chat_id)
    data  = state.get('data', {})
    cart  = get_cart(chat_id)
    name  = data.get('name', get_cust_name(chat_id) or '')
    phone = data.get('phone', get_cust_phone(chat_id) or '')

    # Mijoz ma'lumotlarini saqlaymiz
    if name:  set_cust_name(chat_id, name)
    if phone: set_cust_phone(chat_id, phone)

    ok, eta = _submit_via_session(chat_id, cart, name, phone)
    if not ok:
        ok, eta = _submit_via_orders(cart, name, phone)

    cart_clear(chat_id)
    clear_state(chat_id)
    _cancel_timer(chat_id)

    if ok:
        send_kb(chat_id,
            t(lang, 'order_ok', eta=eta),
            [[{"text": t(lang, 'menu'), "callback_data": "c_menu"},
              {"text": t(lang, 'home'), "callback_data": "c_main"}]])
        _try_register_customer(name, phone)
    else:
        send_kb(chat_id, t(lang, 'order_fail'),
                [[{"text": "🛒 Savat", "callback_data": "c_cart"}]])


def _submit_via_session(chat_id, cart, name, phone):
    """Buyurtmani to'g'ridan kitchen ga (session API orqali)."""
    table_num = get_table(chat_id)
    if not table_num:
        return False, 0
    tables = api("GET", "/api/tables")
    if not isinstance(tables, list):
        return False, 0
    table = next((tb for tb in tables if tb.get('number') == table_num), None)
    if not table:
        return False, 0

    sid = table.get('current_session_id')
    if not sid:
        res = api("POST", "/api/session/open", {
            "table_id":    table['id'],
            "waiter_name": f"QR Bot ({name})",
        })
        if not res.get('ok'):
            log.warning(f"Session open failed for table {table_num}: {res}")
            return False, 0
        sid = res.get('session_id')

    items = [
        {
            "name":         c['name'],
            "emoji":        c.get('emoji', '🍽'),
            "price":        c['price'],
            "quantity":     c['qty'],
            "menu_item_id": c['id'],
            "category":     c.get('category', ''),
            "comment":      f"Mijoz: {name} | Tel: {phone}",
        }
        for c in cart
    ]
    res = api("POST", f"/api/session/{sid}/order", {"items": items})
    if res.get('ok'):
        total_qty = sum(c['qty'] for c in cart)
        eta = min(15 + total_qty * 5, 45)
        return True, eta
    log.warning(f"Session order failed sid={sid}: {res}")
    return False, 0


def _submit_via_orders(cart, name, phone):
    """Fallback: oddiy /api/orders endpoint."""
    ok = 0
    for c in cart:
        res = api("POST", "/api/orders", {
            "item_name":      c['name'],
            "quantity":       c['qty'],
            "total_price":    c['price'] * c['qty'],
            "customer_name":  name,
            "customer_phone": phone,
            "note":           "Telegram bot orqali buyurtma",
        })
        if res.get('id') or res.get('ok'):
            ok += 1
    return (ok > 0), 25


def _try_register_customer(name, phone):
    """Mijozni loyalty tizimiga qo'shish (xato bo'lsa o'tamiz)."""
    if not phone:
        return
    try:
        lookup = api_raw("GET", f"/api/customers/lookup?phone={urllib.parse.quote(phone)}")
        if lookup and lookup.get('found'):
            return
        api("POST", "/api/customers", {"name": name, "phone": phone})
    except Exception as e:
        log.warning(f"Customer register error: {e}")


# ── Ism kiritish (birinchi tashrif) ──────────────────────────

def cust_name_handle(chat_id, name):
    lang = get_lang(chat_id) or 'uz'
    if len(name.strip()) < 2:
        send_msg(chat_id, t(lang, 'name_short')); return
    set_cust_name(chat_id, name.strip())
    clear_state(chat_id)
    send_msg(chat_id, t(lang, 'welcome_new', name=name.strip()))
    customer_main(chat_id)


# ── Bron oqimi ────────────────────────────────────────────────

def bron_start(chat_id):
    lang  = get_lang(chat_id) or 'uz'
    saved_name  = get_cust_name(chat_id)
    saved_phone = get_cust_phone(chat_id)
    if saved_name and saved_phone:
        # Ism va telefon saqlangan — to'g'ridan sana so'rashga o'tish
        data = {'name': saved_name, 'phone': saved_phone}
        set_state(chat_id, 'bron_date', data)
        today    = datetime.date.today()
        tomorrow = today + datetime.timedelta(days=1)
        send_kb(chat_id, t(lang, 'ask_bron_date'), [
            [{"text": t(lang, 'today',    date=today),    "callback_data": f"c_bron_date_{today}"},
             {"text": t(lang, 'tomorrow', date=tomorrow), "callback_data": f"c_bron_date_{tomorrow}"}],
            [{"text": t(lang, 'other_date'), "callback_data": "c_bron_date_manual"}],
        ])
        return
    set_state(chat_id, 'bron_name')
    send_msg(chat_id, t(lang, 'bron_start'))


def bron_handle_name(chat_id, name):
    lang = get_lang(chat_id) or 'uz'
    if len(name.strip()) < 2:
        send_msg(chat_id, t(lang, 'name_short')); return
    set_state(chat_id, 'bron_phone', {'name': name.strip()})
    send_msg(chat_id, t(lang, 'ask_bron_phone'))


def bron_handle_phone(chat_id, phone, data):
    lang = get_lang(chat_id) or 'uz'
    if not _phone_valid(phone):
        msgs = {
            'uz': '📞 Telefon raqami noto\'g\'ri.\nMasalan: +998901234567 yoki 0901234567',
            'ru': '📞 Неверный номер телефона.\nПример: +998901234567',
            'en': '📞 Invalid phone number.\nExample: +998901234567',
        }
        send_msg(chat_id, msgs.get(lang, msgs['uz'])); return
    data['phone'] = phone
    set_state(chat_id, 'bron_date', data)
    today    = datetime.date.today()
    tomorrow = today + datetime.timedelta(days=1)
    send_kb(chat_id, t(lang, 'ask_bron_date'), [
        [{"text": t(lang, 'today',    date=today),    "callback_data": f"c_bron_date_{today}"},
         {"text": t(lang, 'tomorrow', date=tomorrow), "callback_data": f"c_bron_date_{tomorrow}"}],
        [{"text": t(lang, 'other_date'), "callback_data": "c_bron_date_manual"}],
    ])


def bron_handle_date(chat_id, date_str, data):
    lang = get_lang(chat_id) or 'uz'
    data['date'] = date_str
    set_state(chat_id, 'bron_time', data)
    send_kb(chat_id, t(lang, 'ask_bron_time'), [
        [{"text": "12:00", "callback_data": "c_bron_time_12:00"},
         {"text": "13:00", "callback_data": "c_bron_time_13:00"},
         {"text": "14:00", "callback_data": "c_bron_time_14:00"}],
        [{"text": "17:00", "callback_data": "c_bron_time_17:00"},
         {"text": "18:00", "callback_data": "c_bron_time_18:00"},
         {"text": "19:00", "callback_data": "c_bron_time_19:00"}],
        [{"text": "20:00", "callback_data": "c_bron_time_20:00"},
         {"text": "21:00", "callback_data": "c_bron_time_21:00"}],
    ])


def bron_handle_time(chat_id, time_str, data):
    lang = get_lang(chat_id) or 'uz'
    data['time'] = time_str
    set_state(chat_id, 'bron_guests', data)
    send_kb(chat_id, t(lang, 'ask_guests'), [
        [{"text": "1", "callback_data": "c_bron_g_1"},
         {"text": "2", "callback_data": "c_bron_g_2"},
         {"text": "3", "callback_data": "c_bron_g_3"},
         {"text": "4", "callback_data": "c_bron_g_4"}],
        [{"text": "5", "callback_data": "c_bron_g_5"},
         {"text": "6", "callback_data": "c_bron_g_6"},
         {"text": "7+", "callback_data": "c_bron_g_7"}],
    ])


def bron_handle_guests(chat_id, guests, data):
    lang = get_lang(chat_id) or 'uz'
    data['guests'] = guests
    set_state(chat_id, 'bron_note', data)
    send_kb(chat_id, t(lang, 'ask_note'),
            [[{"text": t(lang, 'no_note'), "callback_data": "c_bron_note_none"}]])


def bron_handle_note(chat_id, note, data):
    lang = get_lang(chat_id) or 'uz'
    data['note'] = note
    set_state(chat_id, 'bron_confirm', data)
    note_line = f"\n📝 {note}" if note and note != 'none' else ''
    send_kb(chat_id,
        t(lang, 'bron_confirm', name=data['name'], phone=data['phone'],
          date=data['date'], time=data['time'], guests=data['guests'], note=note_line),
        [[{"text": t(lang, 'confirm'), "callback_data": "c_bron_confirm"},
          {"text": t(lang, 'cancel'),  "callback_data": "c_main"}]])


def bron_submit(chat_id):
    lang  = get_lang(chat_id) or 'uz'
    state = get_state(chat_id)
    data  = state.get('data', {})
    note  = data.get('note', '')
    res   = api("POST", "/api/reservations", {
        "customer_name":  data.get('name', ''),
        "customer_phone": data.get('phone', ''),
        "date":           data.get('date', ''),
        "time":           data.get('time', ''),
        "guests":         int(data.get('guests', 2)),
        "note":           note if note != 'none' else '',
    })
    clear_state(chat_id)
    if res.get('id') or res.get('ok'):
        send_kb(chat_id,
            t(lang, 'bron_ok', date=data.get('date',''), time=data.get('time',''), guests=data.get('guests',2)),
            [[{"text": t(lang, 'home'), "callback_data": "c_main"}]])
    else:
        send_kb(chat_id, t(lang, 'bron_fail'),
                [[{"text": t(lang, 'retry_bron'), "callback_data": "c_bron"},
                  {"text": t(lang, 'home'),        "callback_data": "c_main"}]])


# ── Loyalty ball ──────────────────────────────────────────────

def ball_start(chat_id):
    lang = get_lang(chat_id) or 'uz'
    set_state(chat_id, 'ball_phone')
    send_kb(chat_id, t(lang, 'ask_ball_phone'),
            [[{"text": t(lang, 'cancel'), "callback_data": "c_main"}]])


def ball_by_phone(chat_id, phone):
    lang = get_lang(chat_id) or 'uz'
    if not _phone_valid(phone):
        msgs = {
            'uz': '📞 Telefon raqami noto\'g\'ri.\nMasalan: +998901234567 yoki 0901234567',
            'ru': '📞 Неверный номер телефона.\nПример: +998901234567',
            'en': '📞 Invalid phone number.\nExample: +998901234567',
        }
        send_msg(chat_id, msgs.get(lang, msgs['uz'])); return
    clear_state(chat_id)
    customer = api_raw("GET", f"/api/customers/lookup?phone={urllib.parse.quote(phone)}")
    if not customer or not isinstance(customer, dict) or not customer.get('found'):
        send_kb(chat_id, t(lang, 'loyalty_none'),
                [[{"text": t(lang, 'home'), "callback_data": "c_main"}]]); return
    c      = customer.get('customer', {})
    name   = c.get('name') or phone
    visits = c.get('visits', 0)
    spent  = int(c.get('total_spent', 0))
    disc   = c.get('discount_pct', 0)
    points = c.get('loyalty_points', 0)
    if visits < 5:
        level = t(lang, 'level_bronze')
        next_visits = 5 - visits
        next_msgs = {'uz': f'\n📈 Kumush darajaga: yana <b>{next_visits}</b> tashrif', 'ru': f'\n📈 До Серебра: ещё <b>{next_visits}</b> визита', 'en': f'\n📈 To Silver: <b>{next_visits}</b> more visit(s)'}
        next_line = next_msgs.get(lang, next_msgs['uz'])
    elif visits < 15:
        level = t(lang, 'level_silver')
        next_visits = 15 - visits
        next_msgs = {'uz': f'\n📈 Oltin darajaga: yana <b>{next_visits}</b> tashrif', 'ru': f'\n📈 До Золота: ещё <b>{next_visits}</b> визита', 'en': f'\n📈 To Gold: <b>{next_visits}</b> more visit(s)'}
        next_line = next_msgs.get(lang, next_msgs['uz'])
    else:
        level = t(lang, 'level_gold')
        next_line = ''
    text = t(lang, 'loyalty_info', name=name, level=level, points=points, visits=visits, spent=f'{spent:,}')
    text += next_line
    if disc:
        text += t(lang, 'loyalty_disc', disc=disc)
    send_kb(chat_id, text, [[{"text": t(lang, 'home'), "callback_data": "c_main"}]])


# ── Aksiyalar ─────────────────────────────────────────────────

def show_promotions(chat_id):
    lang  = get_lang(chat_id) or 'uz'
    promos = api_raw("GET", "/api/promotions")
    if not isinstance(promos, list) or not promos:
        msgs = {
            'uz': '🎁 Hozircha faol aksiyalar yo\'q.\nTez kunda yangi takliflar bo\'ladi!',
            'ru': '🎁 Активных акций пока нет.\nСледите за обновлениями!',
            'en': '🎁 No active promotions right now.\nCheck back soon!',
        }
        send_kb(chat_id, msgs.get(lang, msgs['uz']),
                [[{"text": t(lang, 'home'), "callback_data": "c_main"}]])
        return
    lines = []
    for p in promos:
        if not p.get('active', 1):
            continue
        emoji = p.get('emoji', '🎁')
        title = p.get('title', '')
        desc  = p.get('description', '')
        badge = p.get('badge', '')
        time_info = p.get('time_info', '')
        badge_str = f" <b>[{badge}]</b>" if badge else ''
        time_str  = f"\n⏰ {time_info}" if time_info else ''
        lines.append(f"{emoji} <b>{title}</b>{badge_str}\n{desc}{time_str}")
    if not lines:
        msgs = {
            'uz': '🎁 Hozircha faol aksiyalar yo\'q.',
            'ru': '🎁 Активных акций нет.',
            'en': '🎁 No active promotions.',
        }
        send_kb(chat_id, msgs.get(lang, msgs['uz']),
                [[{"text": t(lang, 'home'), "callback_data": "c_main"}]])
        return
    headers = {'uz': '🎁 <b>AKSIYALAR VA TAKLIFLAR</b>', 'ru': '🎁 <b>АКЦИИ И ПРЕДЛОЖЕНИЯ</b>', 'en': '🎁 <b>PROMOTIONS & OFFERS</b>'}
    text = headers.get(lang, headers['uz']) + '\n\n' + '\n\n'.join(lines)
    send_kb(chat_id, text, [[{"text": t(lang, 'home'), "callback_data": "c_main"}]])


# ── Aloqa ─────────────────────────────────────────────────────

def show_contact(chat_id):
    lang     = get_lang(chat_id) or 'uz'
    settings = api("GET", "/api/settings")
    if not isinstance(settings, dict):
        settings = {}
    send_kb(chat_id,
        t(lang, 'contact_text',
          address=settings.get('address', 'Manzil aniqlanmadi'),
          phone=settings.get('phone', '+998 XX XXX XX XX'),
          hours=settings.get('working_hours', '10:00–23:00')),
        [[{"text": t(lang, 'bron'), "callback_data": "c_bron"},
          {"text": t(lang, 'home'), "callback_data": "c_main"}]])


# ── Mijoz callback handler ────────────────────────────────────

def handle_customer_callback(chat_id, data):
    # Til tanlash
    if data.startswith("c_lang_"):
        lang = data[7:]
        if lang in ('uz', 'ru', 'en'):
            set_lang(chat_id, lang)
            clear_state(chat_id)
            name = get_cust_name(chat_id)
            if not name:
                _ask_name(chat_id, lang)
            else:
                customer_main(chat_id)
        return

    if data == "c_main":
        clear_state(chat_id); customer_main(chat_id)
    elif data == "c_menu":
        clear_state(chat_id); show_cat_menu(chat_id)
    elif data.startswith("c_cat_"):
        show_items(chat_id, data[6:])
    elif data.startswith("c_add_"):
        try: add_to_cart(chat_id, int(data[6:]))
        except ValueError: pass
    elif data == "c_cart":
        show_cart(chat_id)
    elif data == "c_cart_clear":
        cart_clear(chat_id)
        lang = get_lang(chat_id) or 'uz'
        send_kb(chat_id, t(lang, 'cart_cleared'),
                [[{"text": t(lang, 'menu'), "callback_data": "c_menu"},
                  {"text": t(lang, 'home'), "callback_data": "c_main"}]])
    elif data == "c_order_start":
        order_start(chat_id)
    elif data == "c_order_confirm":
        order_submit(chat_id)
    elif data == "c_bron":
        clear_state(chat_id); bron_start(chat_id)
    elif data.startswith("c_bron_date_"):
        val = data[12:]
        if val == "manual":
            set_state(chat_id, 'bron_date_manual', get_state(chat_id).get('data', {}))
            lang = get_lang(chat_id) or 'uz'
            send_msg(chat_id, "📆 Sanani kiriting (masalan: 2026-07-15):")
        else:
            bron_handle_date(chat_id, val, get_state(chat_id).get('data', {}))
    elif data.startswith("c_bron_time_"):
        bron_handle_time(chat_id, data[12:], get_state(chat_id).get('data', {}))
    elif data.startswith("c_bron_g_"):
        bron_handle_guests(chat_id, data[9:], get_state(chat_id).get('data', {}))
    elif data == "c_bron_note_none":
        bron_handle_note(chat_id, 'none', get_state(chat_id).get('data', {}))
    elif data == "c_bron_confirm":
        bron_submit(chat_id)
    elif data == "c_ball":
        clear_state(chat_id); ball_start(chat_id)
    elif data == "c_contact":
        show_contact(chat_id)
    elif data == "c_promos":
        show_promotions(chat_id)
