import logging
import requests
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, filters, ContextTypes
)
from config import BOT_TOKEN, ADMIN_IDS, ADMIN_GROUP_ID, RESTAURANT_NAME, RESTAURANT_PHONE, RESTAURANT_ADDRESS, WORKING_HOURS

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

API = "http://localhost:5000"

# ===== STATES =====
(
    ORDER_CATEGORY, ORDER_ITEM, ORDER_QTY, ORDER_NAME, ORDER_PHONE, ORDER_CONFIRM,
    RESERVE_DATE, RESERVE_TIME, RESERVE_GUESTS, RESERVE_NAME, RESERVE_PHONE, RESERVE_CONFIRM
) = range(12)


# ===== HELPERS =====
def price_fmt(p):
    return f"{int(p):,} so'm".replace(",", " ")

def get_menu(category=None):
    try:
        url = f"{API}/api/menu"
        if category:
            url += f"?category={category}"
        res = requests.get(url, timeout=5)
        return res.json()
    except:
        return []

def get_categories():
    return {
        "milliy": "🇺🇿 Milliy taomlar",
        "grill":  "🔥 Grill",
        "salad":  "🥗 Salatlar",
        "drink":  "🥤 Ichimliklar",
    }

def save_order(data):
    try:
        requests.post(f"{API}/api/orders", json=data, timeout=5)
    except:
        pass

def save_reservation(data):
    try:
        requests.post(f"{API}/api/reservations", json=data, timeout=5)
    except:
        pass

def main_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🍽 Menyu"), KeyboardButton("🛒 Buyurtma berish")],
        [KeyboardButton("📅 Stol bron qilish"), KeyboardButton("📞 Aloqa")],
        [KeyboardButton("📰 Yangiliklar"), KeyboardButton("ℹ️ Biz haqimizda")],
    ], resize_keyboard=True)

async def notify_admins(bot, text):
    if ADMIN_GROUP_ID:
        try:
            await bot.send_message(ADMIN_GROUP_ID, text, parse_mode="Markdown")
            return
        except:
            pass
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode="Markdown")
        except:
            pass


# ===== START =====
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"👋 Assalomu alaykum, *{user.first_name}*!\n\n"
        f"🍽 *{RESTAURANT_NAME}* botiga xush kelibsiz!\n\n"
        "Quyidagi tugmalardan birini tanlang:",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )


# ===== MENU =====
async def show_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    items = get_menu()
    if not items:
        await update.message.reply_text("Menyu hozircha mavjud emas.", reply_markup=main_keyboard())
        return

    cats = get_categories()
    text = f"📋 *{RESTAURANT_NAME} — Menyu*\n\n"
    for cat_key, cat_name in cats.items():
        cat_items = [i for i in items if i["category"] == cat_key and i.get("available", 1)]
        if cat_items:
            text += f"*{cat_name}*\n"
            for item in cat_items:
                text += f"  {item.get('emoji','🍽')} {item['name']} — {price_fmt(item['price'])}\n"
            text += "\n"

    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard())


# ===== ORDER FLOW =====
async def order_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    cats = get_categories()
    buttons = [[InlineKeyboardButton(name, callback_data=f"cat_{key}")] for key, name in cats.items()]
    await update.message.reply_text(
        "🛒 *Buyurtma berish*\n\nQaysi bo'limdan tanlaysiz?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return ORDER_CATEGORY


async def order_category(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat_key = query.data.replace("cat_", "")
    ctx.user_data["category"] = cat_key

    items = [i for i in get_menu(cat_key) if i.get("available", 1)]
    if not items:
        await query.edit_message_text("Bu bo'limda taomlar yo'q.")
        return ConversationHandler.END

    cats = get_categories()
    buttons = [
        [InlineKeyboardButton(f"{i.get('emoji','🍽')} {i['name']} — {price_fmt(i['price'])}", callback_data=f"item_{i['id']}")]
        for i in items
    ]
    buttons.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="back_cat")])
    await query.edit_message_text(
        f"*{cats.get(cat_key, cat_key)}* bo'limidan tanlang:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return ORDER_ITEM


async def order_item(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if query.data == "back_cat":
        await query.answer()
        cats = get_categories()
        buttons = [[InlineKeyboardButton(name, callback_data=f"cat_{key}")] for key, name in cats.items()]
        await query.edit_message_text("Qaysi bo'limdan tanlaysiz?", reply_markup=InlineKeyboardMarkup(buttons))
        return ORDER_CATEGORY

    await query.answer()
    item_id = int(query.data.replace("item_", ""))
    all_items = get_menu()
    item = next((i for i in all_items if i["id"] == item_id), None)
    if not item:
        await query.edit_message_text("Taom topilmadi.")
        return ConversationHandler.END

    ctx.user_data["item"] = item
    buttons = [
        [InlineKeyboardButton(str(q), callback_data=f"qty_{q}") for q in [1, 2, 3]],
        [InlineKeyboardButton(str(q), callback_data=f"qty_{q}") for q in [4, 5, 6]],
    ]
    await query.edit_message_text(
        f"{item.get('emoji','🍽')} *{item['name']}*\n"
        f"_{item.get('description','')}_\n\n"
        f"💰 Narxi: *{price_fmt(item['price'])}*\n\n"
        "Nechtadan buyurtma bermoqchisiz?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return ORDER_QTY


async def order_qty(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    qty = int(query.data.replace("qty_", ""))
    ctx.user_data["qty"] = qty
    item = ctx.user_data["item"]
    total = item["price"] * qty
    ctx.user_data["total"] = total
    await query.edit_message_text(
        f"✅ {item.get('emoji','🍽')} *{item['name']}* × {qty} = *{price_fmt(total)}*\n\n"
        "👤 Ismingizni kiriting:",
        parse_mode="Markdown"
    )
    return ORDER_NAME


async def order_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["name"] = update.message.text.strip()
    await update.message.reply_text("📱 Telefon raqamingizni kiriting:\n(masalan: +998901234567)")
    return ORDER_PHONE


async def order_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["phone"] = update.message.text.strip()
    d = ctx.user_data
    item = d["item"]
    text = (
        f"📋 *Buyurtmangizni tasdiqlang:*\n\n"
        f"{item.get('emoji','🍽')} *{item['name']}*\n"
        f"🔢 Miqdor: {d['qty']} dona\n"
        f"💰 Jami: *{price_fmt(d['total'])}*\n\n"
        f"👤 Ism: {d['name']}\n"
        f"📞 Telefon: {d['phone']}"
    )
    buttons = [[
        InlineKeyboardButton("✅ Tasdiqlash", callback_data="order_confirm"),
        InlineKeyboardButton("❌ Bekor", callback_data="order_cancel")
    ]]
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))
    return ORDER_CONFIRM


async def order_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    d = ctx.user_data

    if query.data == "order_cancel":
        await query.edit_message_text("❌ Buyurtma bekor qilindi.")
        return ConversationHandler.END

    item = d["item"]
    user = query.from_user

    # API ga saqlash
    save_order({
        "item_name": item["name"],
        "item_id": item["id"],
        "quantity": d["qty"],
        "total_price": d["total"],
        "customer_name": d["name"],
        "customer_phone": d["phone"],
    })

    # Adminga xabar
    await notify_admins(
        ctx.bot,
        f"🆕 *Yangi buyurtma!*\n\n"
        f"{item.get('emoji','🍽')} {item['name']} × {d['qty']}\n"
        f"💰 {price_fmt(d['total'])}\n\n"
        f"👤 {d['name']}\n"
        f"📞 {d['phone']}\n"
        f"📱 Telegram: @{user.username or 'N/A'}"
    )

    await query.edit_message_text(
        f"✅ *Buyurtmangiz qabul qilindi!*\n\n"
        f"Tez orada *{RESTAURANT_PHONE}* raqamidan siz bilan bog'lanamiz.\n\n"
        f"Rahmat! 🙏",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🏠 Bosh sahifa")]], resize_keyboard=True)
    )
    return ConversationHandler.END


# ===== RESERVATION FLOW =====
async def reserve_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text(
        "📅 *Stol bron qilish*\n\n"
        "Qaysi *sanada* kelmoqchisiz?\n"
        "Formatda yozing: *KK.OO.YYYY*\n"
        "_(masalan: 25.07.2025)_",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["🏠 Bosh sahifa"]], resize_keyboard=True)
    )
    return RESERVE_DATE


async def reserve_date(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["date"] = update.message.text.strip()
    await update.message.reply_text(
        "⏰ Qaysi *vaqtda* kelasiz?\n_(masalan: 19:00)_",
        parse_mode="Markdown"
    )
    return RESERVE_TIME


async def reserve_time(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["time"] = update.message.text.strip()
    buttons = [
        [InlineKeyboardButton("1 kishi", callback_data="g_1"), InlineKeyboardButton("2 kishi", callback_data="g_2")],
        [InlineKeyboardButton("3 kishi", callback_data="g_3"), InlineKeyboardButton("4 kishi", callback_data="g_4")],
        [InlineKeyboardButton("5 kishi", callback_data="g_5"), InlineKeyboardButton("6+ kishi", callback_data="g_6+")],
    ]
    await update.message.reply_text(
        "👥 Nechta kishi keladi?",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return RESERVE_GUESTS


async def reserve_guests(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["guests"] = query.data.replace("g_", "")
    await query.edit_message_text("👤 Ismingizni kiriting:")
    return RESERVE_NAME


async def reserve_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["name"] = update.message.text.strip()
    await update.message.reply_text("📱 Telefon raqamingizni kiriting:")
    return RESERVE_PHONE


async def reserve_phone(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["phone"] = update.message.text.strip()
    d = ctx.user_data
    text = (
        f"📋 *Bron ma'lumotlari:*\n\n"
        f"📅 Sana: *{d['date']}*\n"
        f"⏰ Vaqt: *{d['time']}*\n"
        f"👥 Mehmonlar: *{d['guests']} kishi*\n"
        f"👤 Ism: {d['name']}\n"
        f"📞 Telefon: {d['phone']}"
    )
    buttons = [[
        InlineKeyboardButton("✅ Tasdiqlash", callback_data="res_confirm"),
        InlineKeyboardButton("❌ Bekor", callback_data="res_cancel")
    ]]
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))
    return RESERVE_CONFIRM


async def reserve_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    d = ctx.user_data

    if query.data == "res_cancel":
        await query.edit_message_text("❌ Bron bekor qilindi.")
        return ConversationHandler.END

    user = query.from_user

    save_reservation({
        "customer_name": d["name"],
        "customer_phone": d["phone"],
        "date": d["date"],
        "time": d["time"],
        "guests": d["guests"],
    })

    await notify_admins(
        ctx.bot,
        f"📅 *Yangi bron!*\n\n"
        f"👤 {d['name']}\n"
        f"📞 {d['phone']}\n"
        f"📅 {d['date']} soat {d['time']}\n"
        f"👥 {d['guests']} kishi\n"
        f"📱 Telegram: @{user.username or 'N/A'}"
    )

    await query.edit_message_text(
        f"✅ *Bron tasdiqlandi!*\n\n"
        f"📅 {d['date']} kuni soat {d['time']}da\n"
        f"👥 {d['guests']} kishilik stol band qilindi.\n\n"
        f"Tez orada siz bilan bog'lanamiz. Rahmat! 🙏",
        parse_mode="Markdown"
    )
    return ConversationHandler.END


# ===== NEWS =====
async def show_news(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        res = requests.get(f"{API}/api/news?active=1", timeout=5)
        items = res.json()
    except:
        items = []

    if not items:
        await update.message.reply_text("📭 Hozircha yangiliklar yo'q.", reply_markup=main_keyboard())
        return

    for n in items[:5]:
        text = f"📢 *{n['title']}*\n\n{n.get('content','')}"
        await update.message.reply_text(text, parse_mode="Markdown")

    await update.message.reply_text("Boshqa savol bo'lsa:", reply_markup=main_keyboard())


# ===== CONTACT & ABOUT =====
async def contact(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📞 *Aloqa ma'lumotlari*\n\n"
        f"📱 Telefon: {RESTAURANT_PHONE}\n"
        f"📍 Manzil: {RESTAURANT_ADDRESS}\n"
        f"🕐 Ish vaqti: {WORKING_HOURS}\n"
        f"🌐 Sayt: http://localhost:5000",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )


async def about(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"ℹ️ *{RESTAURANT_NAME} haqida*\n\n"
        "2014-yildan buyon sifatli va mazali taomlar taqdim etib kelmoqdamiz.\n\n"
        "🍽 50+ taom turi\n"
        "⭐ 10+ yillik tajriba\n"
        "😊 1000+ mamnun mijoz\n"
        "🚗 Yetkazib berish xizmati mavjud\n\n"
        f"📞 {RESTAURANT_PHONE}",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )


# ===== ADMIN COMMANDS =====
async def admin_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    try:
        res = requests.get(f"{API}/api/stats",
                           headers={"X-Admin-Token": "admin_panel"}, timeout=5)
        d = res.json()
        await update.message.reply_text(
            f"📊 *Statistika*\n\n"
            f"🆕 Yangi buyurtmalar: {d['orders_new']}\n"
            f"📦 Jami buyurtmalar: {d['orders_total']}\n"
            f"💰 Daromad: {price_fmt(d['revenue'])}\n"
            f"📅 Bugungi bronlar: {d['reservations_today']}\n"
            f"🍽 Aktiv taomlar: {d['menu_count']}",
            parse_mode="Markdown"
        )
    except:
        await update.message.reply_text("Backend bilan ulanib bo'lmadi.")


async def admin_orders(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    try:
        res = requests.get(f"{API}/api/orders?status=new",
                           headers={"X-Admin-Token": "admin_panel"}, timeout=5)
        orders = res.json()
    except:
        await update.message.reply_text("Backend bilan ulanib bo'lmadi.")
        return

    if not orders:
        await update.message.reply_text("✅ Yangi buyurtmalar yo'q.")
        return

    text = f"🆕 *Yangi buyurtmalar ({len(orders)} ta):*\n\n"
    for o in orders[:10]:
        text += (
            f"#{o['id']} — {o['item_name']} × {o['quantity']}\n"
            f"👤 {o['customer_name']} | 📞 {o['customer_phone']}\n"
            f"💰 {price_fmt(o['total_price'])}\n\n"
        )
    await update.message.reply_text(text, parse_mode="Markdown")


# ===== HOME =====
async def home(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await start(update, ctx)
    return ConversationHandler.END


async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bekor qilindi.", reply_markup=main_keyboard())
    return ConversationHandler.END


# ===== MAIN =====
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    order_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🛒 Buyurtma berish$"), order_start)],
        states={
            ORDER_CATEGORY: [CallbackQueryHandler(order_category, pattern="^cat_")],
            ORDER_ITEM:     [CallbackQueryHandler(order_item, pattern="^(item_|back_cat)")],
            ORDER_QTY:      [CallbackQueryHandler(order_qty, pattern="^qty_")],
            ORDER_NAME:     [MessageHandler(filters.TEXT & ~filters.COMMAND, order_name)],
            ORDER_PHONE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, order_phone)],
            ORDER_CONFIRM:  [CallbackQueryHandler(order_confirm, pattern="^order_")],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.Regex("^🏠 Bosh sahifa$"), home),
        ]
    )

    reserve_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📅 Stol bron qilish$"), reserve_start)],
        states={
            RESERVE_DATE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, reserve_date)],
            RESERVE_TIME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, reserve_time)],
            RESERVE_GUESTS:  [CallbackQueryHandler(reserve_guests, pattern="^g_")],
            RESERVE_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, reserve_name)],
            RESERVE_PHONE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, reserve_phone)],
            RESERVE_CONFIRM: [CallbackQueryHandler(reserve_confirm, pattern="^res_")],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.Regex("^🏠 Bosh sahifa$"), home),
        ]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CommandHandler("orders", admin_orders))
    app.add_handler(order_conv)
    app.add_handler(reserve_conv)
    app.add_handler(MessageHandler(filters.Regex("^🍽 Menyu$"), show_menu))
    app.add_handler(MessageHandler(filters.Regex("^📞 Aloqa$"), contact))
    app.add_handler(MessageHandler(filters.Regex("^ℹ️ Biz haqimizda$"), about))
    app.add_handler(MessageHandler(filters.Regex("^📰 Yangiliklar$"), show_news))
    app.add_handler(MessageHandler(filters.Regex("^🏠 Bosh sahifa$"), start))

    logger.info(f"✅ Bot ishga tushdi: @rayyon_restoran_bot")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
