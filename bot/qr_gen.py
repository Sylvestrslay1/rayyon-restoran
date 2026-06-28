"""Stol QR kodlari uchun Telegram deep-link URL generator.

Ishlatish:
  python bot/qr_gen.py

Har bir stol uchun link chiqaradi:
  Stol 1: https://t.me/YourBotUsername?start=t1
  Stol 2: https://t.me/YourBotUsername?start=t2
  ...

Bu URL larni qo'lda QR generator saytiga (qr.io, qrcode-monkey.com va h.k.) joylang.
"""
import os

BOT_USERNAME = os.environ.get("BOT_USERNAME", "rayyon_restoran_bot")
TABLES = range(1, 11)  # Stol 1 dan 10 gacha

if __name__ == "__main__":
    print(f"\n{'='*50}")
    print(f"Stol QR Deep-Link URLlari")
    print(f"Bot: @{BOT_USERNAME}")
    print(f"{'='*50}\n")
    for n in TABLES:
        url = f"https://t.me/{BOT_USERNAME}?start=t{n}"
        print(f"Stol {n:2d}: {url}")
    print(f"\n{'='*50}")
    print("Bu URLlarni QR generator saytiga joylashtiring.")
    print("Masalan: https://qr.io yoki https://qrcode-monkey.com")
    print(f"{'='*50}\n")
