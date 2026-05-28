"""Удалённая авторизация Telethon.
Phone берётся из env LOGIN_PHONE. Код и 2FA-пароль читаются из файлов:
  code.txt — код подтверждения из Telegram
  password.txt — облачный пароль (2FA), если включён
Скрипт сам удаляет файлы после прочтения.
"""
import asyncio
import os

from telethon import TelegramClient
from config import SESSION_NAME, TELEGRAM_API_ID, TELEGRAM_API_HASH

PHONE = os.getenv("LOGIN_PHONE", "+79529534403")
CODE_FILE = "code.txt"
PASSWORD_FILE = "password.txt"


async def _wait_for_file(path: str, label: str) -> str:
    print(f"[WAITING] Жду {label} в файле {path} ...", flush=True)
    while not os.path.exists(path):
        await asyncio.sleep(2)
    with open(path, "r", encoding="utf-8") as f:
        val = f.read().strip()
    try:
        os.remove(path)
    except OSError:
        pass
    print(f"[OK] Получил {label} из {path}", flush=True)
    return val


async def code_callback() -> str:
    return await _wait_for_file(CODE_FILE, "код подтверждения")


async def password_callback() -> str:
    return await _wait_for_file(PASSWORD_FILE, "2FA пароль")


async def main():
    print(f"[START] Логин под номером {PHONE}", flush=True)
    client = TelegramClient(SESSION_NAME, TELEGRAM_API_ID, TELEGRAM_API_HASH)
    await client.start(
        phone=lambda: PHONE,
        code_callback=code_callback,
        password=password_callback,
    )
    me = await client.get_me()
    print(
        f"\n✓ Залогинен: {me.first_name} (@{me.username}) id={me.id}",
        flush=True,
    )
    print("✓ Сессия userbot.session сохранена. Теперь можно: python main.py", flush=True)
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
