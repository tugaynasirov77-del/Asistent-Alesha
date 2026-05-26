"""Разовый скрипт для первой авторизации userbot.
Запусти один раз: python login.py
Введи номер телефона и код из Telegram — создастся userbot.session.
"""
from pyrogram import Client
from config import SESSION_NAME, TELEGRAM_API_ID, TELEGRAM_API_HASH


def main():
    app = Client(SESSION_NAME, api_id=TELEGRAM_API_ID, api_hash=TELEGRAM_API_HASH)
    with app:
        me = app.get_me()
        print(f"\n✓ Залогинен как: {me.first_name} (@{me.username}) id={me.id}")
        print("✓ Сессия сохранена. Теперь можно запускать: python main.py")


if __name__ == "__main__":
    main()
