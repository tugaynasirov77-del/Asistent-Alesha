"""Разовая авторизация Telethon userbot.
Запусти один раз: python login.py
Введи телефон → код из Telegram → 2FA если есть.
Создастся файл userbot.session — больше логин не нужен.
"""
import asyncio
from telethon import TelegramClient
from config import SESSION_NAME, TELEGRAM_API_ID, TELEGRAM_API_HASH


async def main():
    client = TelegramClient(SESSION_NAME, TELEGRAM_API_ID, TELEGRAM_API_HASH)
    await client.start()
    me = await client.get_me()
    print(f"\n✓ Залогинен как: {me.first_name} (@{me.username}) id={me.id}")
    print("✓ Сессия сохранена. Запускай: python main.py")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
