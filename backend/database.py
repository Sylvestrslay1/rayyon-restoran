import os
import sqlite3

DATABASE_URL = os.environ.get("DATABASE_URL")

# PostgreSQL yoki SQLite
USE_PG = bool(DATABASE_URL)

if USE_PG:
    import pg8000.dbapi
    import ssl
    from urllib.parse import urlparse

    _u = urlparse(DATABASE_URL)
    _ssl = ssl.create_default_context()
    # Render.com va Railway kabi cloud provayderlar o'z sertifikatlarini ishlatadi;
    # CERT_NONE — bu muhitlarda kerak (self-signed sertifikatlar).
    _ssl.check_hostname = False
    _ssl.verify_mode = ssl.CERT_NONE
    PG_PARAMS = dict(
        host=_u.hostname,
        port=_u.port or 5432,
        database=_u.path.lstrip("/"),
        user=_u.username,
        password=_u.password,
        ssl_context=_ssl,
        timeout=10,  # 10 soniya ichida ulanmasa — xato
    )


def get_conn():
    if USE_PG:
        return pg8000.dbapi.connect(**PG_PARAMS)
    else:
        DB_PATH = os.path.join(os.path.dirname(__file__), "rayyon.db")
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn


def execute(conn, sql, params=()):
    """SQLite va PostgreSQL uchun universal execute"""
    if USE_PG:
        # PostgreSQL ? -> %s
        sql = sql.replace("?", "%s")
        sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
        # INSERT OR IGNORE -> INSERT ... ON CONFLICT DO NOTHING
        if "INSERT OR IGNORE" in sql:
            sql = sql.replace("INSERT OR IGNORE", "INSERT")
            sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
        sql = sql.replace("INSERT OR REPLACE", "INSERT")
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur


def rows_to_list(cur):
    """Cursor natijasini dict listga aylantirish"""
    if USE_PG:
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in (cur.fetchall() or [])]
    else:
        return [dict(r) for r in cur.fetchall()]


def init_db():
    conn = get_conn()
    try:
        _init_db_inner(conn)
    finally:
        conn.close()


def _init_db_inner(conn):
    cur = conn.cursor()

    if USE_PG:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS menu (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT,
                price INTEGER NOT NULL,
                emoji TEXT DEFAULT '🍽',
                image TEXT,
                available INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                item_name TEXT NOT NULL,
                item_id INTEGER,
                quantity INTEGER DEFAULT 1,
                total_price INTEGER NOT NULL,
                customer_name TEXT NOT NULL,
                customer_phone TEXT NOT NULL,
                status TEXT DEFAULT 'new',
                note TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS reservations (
                id SERIAL PRIMARY KEY,
                customer_name TEXT NOT NULL,
                customer_phone TEXT NOT NULL,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                guests INTEGER DEFAULT 2,
                note TEXT,
                status TEXT DEFAULT 'new',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS news (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT,
                image TEXT,
                active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
    else:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS menu (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT,
                price INTEGER NOT NULL,
                emoji TEXT DEFAULT '🍽',
                image TEXT,
                available INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_name TEXT NOT NULL,
                item_id INTEGER,
                quantity INTEGER DEFAULT 1,
                total_price INTEGER NOT NULL,
                customer_name TEXT NOT NULL,
                customer_phone TEXT NOT NULL,
                status TEXT DEFAULT 'new',
                note TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS reservations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_name TEXT NOT NULL,
                customer_phone TEXT NOT NULL,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                guests INTEGER DEFAULT 2,
                note TEXT,
                status TEXT DEFAULT 'new',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT,
                image TEXT,
                active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

    # ===== RMS CORE JADVALLAR =====
    if USE_PG:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tables (
                id SERIAL PRIMARY KEY,
                number INTEGER NOT NULL UNIQUE,
                name TEXT,
                capacity INTEGER DEFAULT 4,
                status TEXT DEFAULT 'free',
                current_session_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id SERIAL PRIMARY KEY,
                table_id INTEGER NOT NULL,
                table_number INTEGER,
                token TEXT UNIQUE NOT NULL,
                waiter_id INTEGER,
                waiter_name TEXT,
                status TEXT DEFAULT 'active',
                service_charge REAL DEFAULT 0,
                discount REAL DEFAULT 0,
                total_amount INTEGER DEFAULT 0,
                notes TEXT,
                opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                closed_at TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS order_items (
                id SERIAL PRIMARY KEY,
                session_id INTEGER NOT NULL,
                table_number INTEGER,
                menu_item_id INTEGER,
                item_name TEXT NOT NULL,
                item_emoji TEXT DEFAULT '🍽',
                item_price INTEGER NOT NULL,
                quantity INTEGER DEFAULT 1,
                total_price INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                comment TEXT,
                course INTEGER DEFAULT 1,
                category TEXT,
                waiter_id INTEGER,
                waiter_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id SERIAL PRIMARY KEY,
                session_id INTEGER NOT NULL,
                table_number INTEGER,
                amount INTEGER NOT NULL,
                method TEXT DEFAULT 'cash',
                notes TEXT,
                cashier_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS staff (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                role TEXT NOT NULL,
                pin TEXT,
                pin_salt TEXT,
                phone TEXT,
                salary_type TEXT DEFAULT 'monthly',
                salary_amount INTEGER DEFAULT 0,
                active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS attendance (
                id SERIAL PRIMARY KEY,
                staff_id INTEGER NOT NULL,
                staff_name TEXT,
                check_in TIMESTAMP,
                check_out TIMESTAMP,
                date TEXT,
                hours_worked REAL,
                notes TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS recipes (
                id SERIAL PRIMARY KEY,
                menu_item_id INTEGER NOT NULL,
                inventory_id INTEGER NOT NULL,
                quantity REAL NOT NULL,
                unit TEXT DEFAULT 'g'
            )
        """)
    else:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tables (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                number INTEGER NOT NULL UNIQUE,
                name TEXT,
                capacity INTEGER DEFAULT 4,
                status TEXT DEFAULT 'free',
                current_session_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                table_id INTEGER NOT NULL,
                table_number INTEGER,
                token TEXT UNIQUE NOT NULL,
                waiter_id INTEGER,
                waiter_name TEXT,
                status TEXT DEFAULT 'active',
                service_charge REAL DEFAULT 0,
                discount REAL DEFAULT 0,
                total_amount INTEGER DEFAULT 0,
                notes TEXT,
                opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                closed_at TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                table_number INTEGER,
                menu_item_id INTEGER,
                item_name TEXT NOT NULL,
                item_emoji TEXT DEFAULT '🍽',
                item_price INTEGER NOT NULL,
                quantity INTEGER DEFAULT 1,
                total_price INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                comment TEXT,
                course INTEGER DEFAULT 1,
                category TEXT,
                waiter_id INTEGER,
                waiter_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                table_number INTEGER,
                amount INTEGER NOT NULL,
                method TEXT DEFAULT 'cash',
                notes TEXT,
                cashier_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS staff (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                role TEXT NOT NULL,
                pin TEXT,
                pin_salt TEXT,
                phone TEXT,
                salary_type TEXT DEFAULT 'monthly',
                salary_amount INTEGER DEFAULT 0,
                active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                staff_id INTEGER NOT NULL,
                staff_name TEXT,
                check_in TIMESTAMP,
                check_out TIMESTAMP,
                date TEXT,
                hours_worked REAL,
                notes TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS recipes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                menu_item_id INTEGER NOT NULL,
                inventory_id INTEGER NOT NULL,
                quantity REAL NOT NULL,
                unit TEXT DEFAULT 'g'
            )
        """)

    # Default stollar
    cur.execute("SELECT COUNT(*) FROM tables")
    if (cur.fetchone()[0]) == 0:
        for i in range(1, 11):
            if USE_PG:
                cur.execute("INSERT INTO tables (number, name, capacity) VALUES (%s,%s,%s)", (i, f"Stol {i}", 4))
            else:
                cur.execute("INSERT INTO tables (number, name, capacity) VALUES (?,?,?)", (i, f"Stol {i}", 4))

    # Galereya va aksiyalar jadvallari
    if USE_PG:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS gallery (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                emoji TEXT DEFAULT '🖼',
                image TEXT,
                sort_order INTEGER DEFAULT 0,
                active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS promotions (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                badge TEXT,
                emoji TEXT DEFAULT '🎁',
                time_info TEXT,
                active INTEGER DEFAULT 1,
                sort_order INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    else:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS gallery (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                emoji TEXT DEFAULT '🖼',
                image TEXT,
                sort_order INTEGER DEFAULT 0,
                active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS promotions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                badge TEXT,
                emoji TEXT DEFAULT '🎁',
                time_info TEXT,
                active INTEGER DEFAULT 1,
                sort_order INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

    # Default galereya
    cur.execute("SELECT COUNT(*) FROM gallery")
    if (cur.fetchone()[0]) == 0:
        gallery_defaults = [
            ("Asosiy zal", "🏛", 1), ("Milliy taomlar", "🍚", 2),
            ("Grill bo'limi", "🔥", 3), ("VIP xona", "👑", 4),
            ("Tashqi makon", "🌙", 5), ("Shirinliklar", "🍰", 6),
        ]
        for title, emoji, order in gallery_defaults:
            if USE_PG:
                cur.execute("INSERT INTO gallery (title, emoji, sort_order) VALUES (%s,%s,%s)", (title, emoji, order))
            else:
                cur.execute("INSERT INTO gallery (title, emoji, sort_order) VALUES (?,?,?)", (title, emoji, order))

    # Default aksiyalar
    cur.execute("SELECT COUNT(*) FROM promotions")
    if (cur.fetchone()[0]) == 0:
        promo_defaults = [
            ("Ertalabki chegirma", "Har kuni 10:00–13:00 oralig'ida barcha taomlardan 20% chegirma", "-20%", "🌅", "Har kuni · 10:00–13:00", 1),
            ("Oilaviy set", "4 kishilik to'plam: 2 palov + 1 sho'rva + 4 somsa", "SET", "👨‍👩‍👧‍👦", "Juma – Yakshanba", 2),
            ("Tug'ilgan kun", "Tug'ilgan kuningizda keling — tort va sovg'a biz tarafdan", "🎂", "🎉", "Oldindan bron qiling", 3),
        ]
        for title, desc, badge, emoji, time_info, order in promo_defaults:
            if USE_PG:
                cur.execute("INSERT INTO promotions (title, description, badge, emoji, time_info, sort_order) VALUES (%s,%s,%s,%s,%s,%s)", (title, desc, badge, emoji, time_info, order))
            else:
                cur.execute("INSERT INTO promotions (title, description, badge, emoji, time_info, sort_order) VALUES (?,?,?,?,?,?)", (title, desc, badge, emoji, time_info, order))

    # Buxgalteriya jadvallari
    if USE_PG:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id SERIAL PRIMARY KEY,
                category TEXT NOT NULL,
                description TEXT,
                amount INTEGER NOT NULL,
                date TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                unit TEXT DEFAULT 'kg',
                quantity REAL DEFAULT 0,
                min_quantity REAL DEFAULT 0,
                price_per_unit INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS inventory_log (
                id SERIAL PRIMARY KEY,
                item_id INTEGER,
                item_name TEXT,
                type TEXT,
                quantity REAL,
                note TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    else:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                description TEXT,
                amount INTEGER NOT NULL,
                date TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                unit TEXT DEFAULT 'kg',
                quantity REAL DEFAULT 0,
                min_quantity REAL DEFAULT 0,
                price_per_unit INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS inventory_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER,
                item_name TEXT,
                type TEXT,
                quantity REAL,
                note TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

    # Default settings
    defaults = [
        ("restaurant_name", "Rayyon Restoran"),
        ("phone", "+998 71 123 45 67"),
        ("address", "Toshkent sh., Yunusobod tumani, Amir Temur ko'chasi 15"),
        ("working_hours", "10:00 – 23:00"),
        ("app_version", "2.0"),
        ("telegram_bot", "@rayyon_restoran_bot"),
    ]
    for key, val in defaults:
        if USE_PG:
            cur.execute(
                "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
                (key, val)
            )
        else:
            cur.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, val)
            )

    # Default menu
    menu_defaults = [
        ("Palov", "milliy", "An'anaviy o'zbek palovi, qo'zi go'shti bilan", 35000, "🍚"),
        ("Somsa (2 dona)", "milliy", "Tandirda pishirilgan, go'shtli somsa", 18000, "🥟"),
        ("Lag'mon", "milliy", "Qo'lda tortilgan lag'mon, sabzavotlar bilan", 28000, "🍜"),
        ("Manti (5 dona)", "milliy", "Bug'da pishirilgan manti", 32000, "🥠"),
        ("Shurva", "milliy", "Qo'zichoq qovurg'asi bilan shurva", 30000, "🍲"),
        ("Grill tovuq", "grill", "Butun tovuq, marinadlangan va grillda pishirilgan", 75000, "🍗"),
        ("Kebab", "grill", "Mol go'shti kebabi, sabzavot garniri bilan", 55000, "🍢"),
        ("Grill sabzavot", "grill", "Aralash grill sabzavotlar", 22000, "🥦"),
        ("Toshkent salat", "salad", "Go'sht, pomidor, piyoz va o'tlar bilan", 20000, "🥗"),
        ("Meva salati", "salad", "Mavsumiy mevalar va asal bilan", 18000, "🍓"),
        ("Cezar salat", "salad", "Tovuq, kruton, parmezan bilan", 25000, "🥙"),
        ("Kompot (1L)", "drink", "Tabiiy mevali kompot", 12000, "🥤"),
        ("Choy (dam)", "drink", "Ko'k yoki qora choy, non bilan", 8000, "🍵"),
        ("Limonad", "drink", "Toza siqilgan limon sharbati", 15000, "🍋"),
    ]
    # Jadval bo'sh bo'lsagina default taomlarni qo'shamiz
    cur.execute("SELECT COUNT(*) FROM menu")
    count = cur.fetchone()[0]
    if count == 0:
        for item in menu_defaults:
            if USE_PG:
                cur.execute(
                    "INSERT INTO menu (name, category, description, price, emoji) VALUES (%s,%s,%s,%s,%s)",
                    item
                )
            else:
                cur.execute(
                    "INSERT INTO menu (name, category, description, price, emoji) VALUES (?,?,?,?,?)",
                    item
                )

    # ===== LOYALTY MIJOZLAR =====
    if USE_PG:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id SERIAL PRIMARY KEY,
                name TEXT,
                phone TEXT UNIQUE NOT NULL,
                total_spent INTEGER DEFAULT 0,
                visits INTEGER DEFAULT 0,
                discount_pct REAL DEFAULT 0,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    else:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                phone TEXT UNIQUE NOT NULL,
                total_spent INTEGER DEFAULT 0,
                visits INTEGER DEFAULT 0,
                discount_pct REAL DEFAULT 0,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

    # loyalty_points ustunini migration orqali qo'shish
    try:
        if USE_PG:
            cur.execute("ALTER TABLE customers ADD COLUMN IF NOT EXISTS loyalty_points INTEGER DEFAULT 0")
        else:
            cur.execute("ALTER TABLE customers ADD COLUMN loyalty_points INTEGER DEFAULT 0")
    except Exception:
        pass  # Ustun allaqachon mavjud

    # ===== KASSIR SMENALARI =====
    if USE_PG:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS shifts (
                id SERIAL PRIMARY KEY,
                cashier_id INTEGER NOT NULL,
                cashier_name TEXT NOT NULL,
                status TEXT DEFAULT 'open',
                total_collected INTEGER DEFAULT 0,
                sessions_count INTEGER DEFAULT 0,
                notes TEXT,
                opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                closed_at TIMESTAMP
            )
        """)
    else:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS shifts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cashier_id INTEGER NOT NULL,
                cashier_name TEXT NOT NULL,
                status TEXT DEFAULT 'open',
                total_collected INTEGER DEFAULT 0,
                sessions_count INTEGER DEFAULT 0,
                notes TEXT,
                opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                closed_at TIMESTAMP
            )
        """)

    # ===== PUSH NOTIFICATIONS =====
    if USE_PG:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS push_subscriptions (
                id SERIAL PRIMARY KEY,
                endpoint TEXT UNIQUE NOT NULL,
                p256dh TEXT NOT NULL,
                auth TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id SERIAL PRIMARY KEY,
                action TEXT NOT NULL,
                entity TEXT,
                entity_id INTEGER,
                user_name TEXT,
                user_ip TEXT,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    else:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS push_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                endpoint TEXT UNIQUE NOT NULL,
                p256dh TEXT NOT NULL,
                auth TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                entity TEXT,
                entity_id INTEGER,
                user_name TEXT,
                user_ip TEXT,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

    # ===== MIGRATION: mavjud jadvalga yangi ustunlar qo'shish =====
    migrations = [
        "ALTER TABLE staff ADD COLUMN pin_salt TEXT",
        "ALTER TABLE order_items ADD COLUMN void_by TEXT",
        "ALTER TABLE order_items ADD COLUMN void_reason TEXT",
        "ALTER TABLE order_items ADD COLUMN voided_at TIMESTAMP",
        "ALTER TABLE payments ADD COLUMN cashier_name TEXT",
        "ALTER TABLE payments ADD COLUMN cashier_id INTEGER",
        "ALTER TABLE payments ADD COLUMN verified INTEGER DEFAULT 0",
        "ALTER TABLE payments ADD COLUMN shift_id INTEGER",
        "ALTER TABLE payments ADD COLUMN refunded INTEGER DEFAULT 0",
        "ALTER TABLE payments ADD COLUMN refund_amount INTEGER DEFAULT 0",
        "ALTER TABLE sessions ADD COLUMN cashier_name TEXT",
        "ALTER TABLE sessions ADD COLUMN cashier_id INTEGER",
        "ALTER TABLE sessions ADD COLUMN customer_id INTEGER",
        "ALTER TABLE sessions ADD COLUMN customer_phone TEXT",
        "ALTER TABLE sessions ADD COLUMN customer_name TEXT",
        "ALTER TABLE sessions ADD COLUMN shift_id INTEGER",
        "ALTER TABLE shifts ADD COLUMN opening_cash INTEGER DEFAULT 0",
        "ALTER TABLE shifts ADD COLUMN total_revenue INTEGER DEFAULT 0",
    ]
    for migration_sql in migrations:
        try:
            if USE_PG:
                # "ALTER TABLE <tbl> ADD COLUMN <col> <TYPE> [DEFAULT x]"
                # col_def = "<col> <TYPE> [DEFAULT x]" — to'liq tip saqlanadi
                col_def = migration_sql.split("ADD COLUMN")[1].strip()
                tbl     = migration_sql.split("ALTER TABLE")[1].strip().split()[0]
                cur.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS {col_def}")
            else:
                cur.execute(migration_sql)
        except Exception as _me:
            err_str = str(_me).lower()
            # "duplicate column" yoki "already exists" — kutilgan xato, o'tamiz
            if "duplicate" not in err_str and "already exist" not in err_str and "duplicate_column" not in err_str:
                import logging as _lg
                _lg.getLogger(__name__).warning("Migration ogohlantirish: %s | SQL: %s", _me, migration_sql)

    # ===== PERFORMANCE INDEXES =====
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_order_items_session ON order_items(session_id)",
        "CREATE INDEX IF NOT EXISTS idx_order_items_status  ON order_items(status)",
        "CREATE INDEX IF NOT EXISTS idx_payments_session    ON payments(session_id)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_status     ON sessions(status)",
        "CREATE INDEX IF NOT EXISTS idx_attendance_staff    ON attendance(staff_id)",
        "CREATE INDEX IF NOT EXISTS idx_attendance_date     ON attendance(date)",
        "CREATE INDEX IF NOT EXISTS idx_inv_log_item        ON inventory_log(item_id)",
        "CREATE INDEX IF NOT EXISTS idx_inv_log_created     ON inventory_log(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_orders_status       ON orders(status)",
        "CREATE INDEX IF NOT EXISTS idx_reservations_date   ON reservations(date)",
        "CREATE INDEX IF NOT EXISTS idx_audit_action        ON audit_log(action)",
        "CREATE INDEX IF NOT EXISTS idx_audit_created       ON audit_log(created_at)",
    ]
    for idx_sql in indexes:
        try:
            if USE_PG:
                cur.execute(idx_sql.replace("?", "%s"))
            else:
                cur.execute(idx_sql)
        except Exception:
            pass

    conn.commit()
    cur.close()
