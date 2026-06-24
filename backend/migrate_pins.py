"""
Rayyon RMS — PIN Migration Skripti
===================================
Eski sha256[:8] format bilan saqlangan PIN larni
yangi pbkdf2_hmac + salt formatiga o'tkazadi.

FOYDALANISH:
  1. Admin har bir xodimning haqiqiy PINini bilishi kerak
  2. Skriptni ishga tushiring:  python migrate_pins.py
  3. Har bir xodim uchun PIN ni kiriting (Enter — o'tkazib yuborish)

MUHIM: Bu skript faqat bir marta ishga tushirilishi kerak!
"""

import os, sys, hashlib, sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "rayyon.db")
PBKDF2_ITERATIONS = 200_000


def hash_password(password: str):
    salt = os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return h.hex(), salt.hex()


def verify_legacy(pin: str, stored: str) -> bool:
    return hashlib.sha256(str(pin).encode()).hexdigest()[:8] == stored


def main():
    if not os.path.exists(DB_PATH):
        print("❌ rayyon.db topilmadi. Backend papkasida ishga tushiring.")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # pin_salt ustuni mavjudligini tekshirish
    cur.execute("PRAGMA table_info(staff)")
    cols = [r["name"] for r in cur.fetchall()]
    if "pin_salt" not in cols:
        cur.execute("ALTER TABLE staff ADD COLUMN pin_salt TEXT")
        conn.commit()
        print("✅ pin_salt ustuni qo'shildi.")

    cur.execute("SELECT id, name, role, pin, pin_salt FROM staff WHERE active=1")
    staff_list = [dict(r) for r in cur.fetchall()]

    print(f"\n{'='*50}")
    print(f"  Rayyon PIN Migration  —  {len(staff_list)} xodim")
    print(f"{'='*50}\n")

    updated = 0
    skipped = 0

    for s in staff_list:
        if s.get("pin_salt"):
            print(f"⏭  {s['name']} ({s['role']}) — allaqachon yangi format, o'tkazildi.")
            skipped += 1
            continue

        print(f"👤 {s['name']} ({s['role']})")
        if not s.get("pin"):
            print("   ⚠  PIN yo'q, o'tkazildi.\n")
            skipped += 1
            continue

        while True:
            pin = input(f"   PIN kiriting (Enter — o'tkazib yuborish): ").strip()
            if not pin:
                print("   ⏭  O'tkazildi.\n")
                skipped += 1
                break
            if len(pin) < 4:
                print("   ❌ PIN kamida 4 raqam bo'lishi kerak.")
                continue
            if verify_legacy(pin, s["pin"]):
                new_hash, new_salt = hash_password(pin)
                cur.execute(
                    "UPDATE staff SET pin=?, pin_salt=? WHERE id=?",
                    (new_hash, new_salt, s["id"])
                )
                conn.commit()
                print(f"   ✅ Muvaffaqiyatli yangilandi.\n")
                updated += 1
                break
            else:
                print("   ❌ PIN noto'g'ri (eski tizim bilan mos kelmadi). Qayta urinib ko'ring.")

    print(f"\n{'='*50}")
    print(f"  Natija: {updated} yangilandi, {skipped} o'tkazildi")
    print(f"{'='*50}\n")
    conn.close()


if __name__ == "__main__":
    main()
