"""
Rayyon Restoran Telegram Bot — asosiy kirish nuqtasi
Muhit o'zgaruvchilari:
  TELEGRAM_BOT_TOKEN  - BotFather dan olingan token
  TELEGRAM_CHAT_ID    - Bildirishnomalar chat ID (vergul bilan bir nechta)
  RAYYON_API_URL      - Backend URL
  RAYYON_ADMIN_PASS   - Admin paroli
  DAILY_REPORT_HOUR   - Kunlik hisobot soati (standart: 22)
  NOTIF_INTERVAL      - Bildirishnoma tekshiruv intervali soniyada (standart: 60)
Ishga tushirish: python bot/bot.py
"""
import time, threading

from core import (
    TOKEN, log, tg, is_allowed, login, api,
    get_state, clear_state, cart_clear, get_staff,
    STATUS_LABELS, get_user_role, set_user_role,
    send_kb, ALLOWED_CHAT_IDS,
    get_lang, get_cust_name, _load_persist,
)
from admin import (
    main_menu, show_orders, show_reservations, show_tables,
    show_shifts, show_staff, show_inventory, show_customers,
    show_today, show_period, show_top_menu, close_shift,
)
from customer import (
    customer_start, customer_main, show_cat_menu, bron_start, ball_start,
    order_handle_name, order_handle_phone,
    bron_handle_name, bron_handle_phone, bron_handle_date,
    bron_handle_time, bron_handle_note, ball_by_phone,
    handle_customer_callback, cust_name_handle,
)
from staff import (
    staff_main_menu, staff_login_start, staff_pin_submit,
    handle_staff_callback,
)
from notifications import _notification_loop


def _customer_start_with_param(chat_id, text):
    """QR deeplink param ni ajratib customer_start ga uzatadi.
    Misol: '/start t5' → table_num=5
    """
    parts = text.split(None, 1)
    param = parts[1].strip() if len(parts) > 1 else ''
    table_num = None
    if param.startswith('t') and param[1:].isdigit():
        table_num = int(param[1:])
    customer_start(chat_id, table_num)


def handle_message(msg):
    chat_id  = msg["chat"]["id"]
    text     = msg.get("text", "").strip()
    is_admin = is_allowed(chat_id)

    # ── Suhbat holati tekshiruvi ──────────────────────────────
    state = get_state(chat_id)
    step  = state.get('step', '')
    data  = state.get('data', {})

    if step == 'cust_name':
        cust_name_handle(chat_id, text); return
    if step == 'staff_pin':
        staff_pin_submit(chat_id, text); return
    if step == 'order_name':
        order_handle_name(chat_id, text); return
    if step == 'order_phone':
        order_handle_phone(chat_id, text, data); return
    if step == 'bron_name':
        bron_handle_name(chat_id, text); return
    if step == 'bron_phone':
        bron_handle_phone(chat_id, text, data); return
    if step in ('bron_date', 'bron_date_manual'):
        bron_handle_date(chat_id, text, data); return
    if step == 'bron_time':
        bron_handle_time(chat_id, text, data); return
    if step == 'bron_note':
        bron_handle_note(chat_id, text, data); return
    if step == 'ball_phone':
        ball_by_phone(chat_id, text); return

    # ── /cancel ───────────────────────────────────────────────
    if text == '/cancel':
        clear_state(chat_id)
        cart_clear(chat_id)
        if is_admin:
            main_menu(chat_id)
        else:
            customer_start(chat_id)
        return

    # ── /help ─────────────────────────────────────────────────
    if text == '/help':
        lang = get_lang(chat_id) or 'uz'
        help_texts = {
            'uz': (
                "ℹ️ <b>Rayyon Restoran Boti</b>\n\n"
                "/start — Bosh menyuga qaytish\n"
                "/menu — Menyu va buyurtma berish\n"
                "/cancel — Joriy amalni bekor qilish\n"
                "/help — Ushbu yordam xabari\n\n"
                "📌 Savollar uchun: @rayyon_admin"
            ),
            'ru': (
                "ℹ️ <b>Бот Rayyon Restoran</b>\n\n"
                "/start — Главное меню\n"
                "/menu — Меню и заказ\n"
                "/cancel — Отменить текущее действие\n"
                "/help — Эта справка\n\n"
                "📌 По вопросам: @rayyon_admin"
            ),
            'en': (
                "ℹ️ <b>Rayyon Restaurant Bot</b>\n\n"
                "/start — Main menu\n"
                "/menu — Menu & ordering\n"
                "/cancel — Cancel current action\n"
                "/help — This help message\n\n"
                "📌 Support: @rayyon_admin"
            ),
        }
        from core import send_msg as _sm
        _sm(chat_id, help_texts.get(lang, help_texts['uz']))
        return

    # ── /start ────────────────────────────────────────────────
    if text.startswith('/start'):
        clear_state(chat_id)
        if is_admin:
            main_menu(chat_id)
        elif get_user_role(chat_id) == 'staff':
            staff = get_staff(chat_id)
            if staff:
                staff_main_menu(chat_id, staff)
            else:
                set_user_role(chat_id, None)
                _customer_start_with_param(chat_id, text)
        else:
            _customer_start_with_param(chat_id, text)
        return

    # ── /xodim ────────────────────────────────────────────────
    if text == '/xodim':
        staff = get_staff(chat_id)
        if staff:
            staff_main_menu(chat_id, staff)
        else:
            staff_login_start(chat_id)
        return

    # ── Mijoz buyruqlari (hamma uchun) ────────────────────────
    if text == '/menu':
        show_cat_menu(chat_id); return
    if text == '/bron':
        bron_start(chat_id); return
    if text == '/ball':
        ball_start(chat_id); return

    # ── Admin buyruqlari ──────────────────────────────────────
    if is_admin:
        cmds = {
            "/orders":       show_orders,
            "/reservations": show_reservations,
            "/stollar":      show_tables,
            "/smena":        show_shifts,
            "/inventar":     show_inventory,
            "/mijozlar":     show_customers,
            "/bugun":        show_today,
            "/xodimlar":     show_staff,
        }
        if text in cmds:
            cmds[text](chat_id)
        elif text == "/hafta":
            show_period(chat_id, "weekly", "Haftalik")
        elif text == "/oy":
            show_period(chat_id, "monthly", "Oylik")
        else:
            send_kb(chat_id,
                "📌 Mavjud buyruqlar:\n"
                "/orders — Buyurtmalar\n/reservations — Bronlar\n"
                "/stollar — Stollar\n/smena — Smena\n"
                "/inventar — Inventar\n/mijozlar — Top mijozlar\n"
                "/bugun — Bugun\n/hafta — Hafta\n/oy — Oy\n"
                "/xodimlar — Xodimlar",
                [[{"text": "🏠 Asosiy menyu", "callback_data": "main"}]])
    else:
        customer_main(chat_id)


def handle_callback(cb):
    chat_id = cb["message"]["chat"]["id"]
    msg_id  = cb["message"]["message_id"]
    data    = cb.get("data", "")
    cb_id   = cb["id"]

    tg("answerCallbackQuery", callback_query_id=cb_id)

    # Xodim callbacklari — hamma uchun ochiq
    if data.startswith("s_") or data.startswith("sw_"):
        handle_staff_callback(chat_id, data)
        return

    # Mijoz callbacklari — hamma uchun ochiq
    if data.startswith("c_"):
        handle_customer_callback(chat_id, data)
        return

    # Admin callbacklari — faqat ruxsatli chatlar
    if not is_allowed(chat_id):
        log.warning(f"Ruxsatsiz admin callback: {chat_id}")
        return

    dispatch = {
        "main":         main_menu,
        "orders":       show_orders,
        "reservations": show_reservations,
        "tables":       show_tables,
        "shifts":       show_shifts,
        "inventory":    show_inventory,
        "customers":    show_customers,
        "today":        show_today,
        "staff":        show_staff,
        "top_menu":     show_top_menu,
    }
    if data in dispatch:
        dispatch[data](chat_id)
        return
    if data == "week":
        show_period(chat_id, "weekly", "Haftalik"); return
    if data == "month":
        show_period(chat_id, "monthly", "Oylik"); return

    if data.startswith("ord_"):
        _, status, oid = data.split("_", 2)
        res   = api("PUT", f"/api/orders/{oid}", {"status": status})
        label = STATUS_LABELS.get(status, status)
        if res.get("ok"):
            tg("editMessageText",
               chat_id=chat_id, message_id=msg_id,
               text=f"✅ Buyurtma #{oid} → {label}", parse_mode="HTML")
        return

    if data.startswith("res_"):
        _, status, rid = data.split("_", 2)
        res   = api("PUT", f"/api/reservations/{rid}", {"status": status})
        label = STATUS_LABELS.get(status, status)
        if res.get("ok"):
            tg("editMessageText",
               chat_id=chat_id, message_id=msg_id,
               text=f"✅ Bron #{rid} → {label}", parse_mode="HTML")
        return

    # shift_close_confirm_ AVVAL tekshirilishi kerak (shift_close_ ham match qiladi)
    if data.startswith("shift_close_confirm_"):
        try: close_shift(chat_id, int(data[20:]))
        except ValueError: pass
        return

    if data.startswith("shift_close_"):
        try:
            sid = int(data[12:])
            send_kb(chat_id, "⚠️ Smenani yopishni tasdiqlaysizmi?",
                    [[{"text": "✅ Ha, yop", "callback_data": f"shift_close_confirm_{sid}"},
                      {"text": "❌ Bekor",   "callback_data": "shifts"}]])
        except ValueError:
            pass
        return

    log.debug(f"Noma'lum callback: {data}")


def poll():
    log.info("Bot polling boshlandi")
    if not ALLOWED_CHAT_IDS:
        log.warning("TELEGRAM_CHAT_ID o'rnatilmagan — barcha chatlar ruxsatli (test rejim)!")

    # Bot to'xtatilgan vaqtdagi eski xabarlarni o'tkazib yuboramiz
    res = tg("getUpdates", offset=-1, timeout=0)
    updates = res.get("result", [])
    offset = (updates[-1]["update_id"] + 1) if updates else 0
    log.info(f"Eski xabarlar o'tkazib yuborildi, offset={offset}")

    threading.Thread(target=_notification_loop, daemon=True).start()

    while True:
        res = tg("getUpdates", offset=offset, timeout=30)
        for upd in res.get("result", []):
            offset = upd["update_id"] + 1
            try:
                if "message" in upd:
                    handle_message(upd["message"])
                elif "callback_query" in upd:
                    handle_callback(upd["callback_query"])
            except Exception as e:
                log.error(f"Handler error: {e}")
        time.sleep(0.3)


if __name__ == "__main__":
    if not TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN o'rnatilmagan!")
        print("   export TELEGRAM_BOT_TOKEN=<token>")
        exit(1)
    _load_persist()   # Saqlangan til/ism/telefon ma'lumotlarini yuklash
    login()
    poll()
