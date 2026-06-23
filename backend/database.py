import os
import sqlite3

DATABASE_URL = os.environ.get("DATABASE_URL")

# PostgreSQL yoki SQLite
USE_PG = bool(DATABASE_URL)

if USE_PG:
    import psycopg2
    import psycopg2.extras


def get_conn():
    if USE_PG:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    else:
        DB_PATH = os.path.join(os.path.dirname(__file__), "rayyon.db")
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn


def execute(conn, sql, params=()):
    """SQLite va PostgreSQL uchun universal execute"""
    if USE_PG:
        # PostgreSQL ? -> %s
        sql = sql.replace("?", "%s")
        sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
        sql = sql.replace("INSERT OR IGNORE", "INSERT")
        sql = sql.replace("INSERT OR REPLACE", "INSERT")
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur


def rows_to_list(cur):
    """Cursor natijasini dict listga aylantirish"""
    if USE_PG:
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    else:
        return [dict(r) for r in cur.fetchall()]


def init_db():
    conn = get_conn()
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

    # Default settings
    defaults = [
        ("restaurant_name", "Rayyon Restoran"),
        ("phone", "+998 71 123 45 67"),
        ("address", "Toshkent sh., Yunusobod tumani, Amir Temur ko'chasi 15"),
        ("working_hours", "10:00 – 23:00"),
        ("admin_password", "rayyon2024"),
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
    count = cur.fetchone()[0] if USE_PG else cur.fetchone()[0]
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

    conn.commit()
    cur.close()
    conn.close()
