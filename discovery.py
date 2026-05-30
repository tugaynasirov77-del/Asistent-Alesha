"""Поиск новых каналов и чатов через Telegram Search (Telethon).

Поиск по предзаданным ключевым словам, фильтрация по размеру и активности,
дедупликация против уже добавленных.
"""
from __future__ import annotations

import logging
from typing import Literal

from telethon.tl.functions.contacts import SearchRequest
from telethon.tl.types import Channel, Chat

from db import list_dynamic_chats

log = logging.getLogger(__name__)


# Поиск делаем по нишам — каждая ключевая фраза даёт пул результатов
KEYWORD_PACKS: dict[str, list[str]] = {
    "beauty": [
        "владельцы салонов",
        "бьюти бизнес",
        "салоны красоты",
        "мастера маникюра",
        "бровисты лешмейкеры",
        "барбершоп владельцы",
        "косметологи бизнес",
    ],
    "selfworkers": [
        "самозанятые",
        "частная практика",
        "мастер на себя",
    ],
    "services": [
        "репетиторы",
        "фитнес тренеры",
        "психологи практика",
        "нутрициолог практика",
        "фотографы заказы",
    ],
    "automation": [
        "yclients",
        "altegio",
        "автоматизация записи",
        "crm салон",
    ],
}


def _candidate_dict(chat, query: str) -> dict | None:
    """Превращает Channel/Chat в плоский словарь. Отбрасывает странные."""
    if not isinstance(chat, (Channel, Chat)):
        return None
    uname = getattr(chat, "username", None)
    if not uname:
        return None  # без username — не публичный, пропускаем
    title = getattr(chat, "title", "") or ""
    if not title:
        return None
    return {
        "username": uname.lower(),
        "title": title,
        "participants_count": getattr(chat, "participants_count", None) or 0,
        "is_channel": isinstance(chat, Channel) and getattr(chat, "broadcast", False),
        "is_megagroup": isinstance(chat, Channel) and getattr(chat, "megagroup", False),
        "verified": getattr(chat, "verified", False),
        "matched_query": query,
    }


def _score(c: dict) -> float:
    """Грубая оценка качества кандидата — чем выше, тем лучше."""
    p = c["participants_count"]
    if p < 200:
        return 0  # слишком мелко
    if p > 200_000:
        return 0.3  # огромное — обычно мусор / новости
    base = min(p / 5000, 5)  # шкалирование
    if c["is_megagroup"]:
        base += 1  # чаты с обсуждением — для нас приоритет
    if c["verified"]:
        base += 0.5
    return base


async def discover_candidates(
    user_client,
    pack: str,
    limit_per_query: int = 15,
    max_results: int = 12,
) -> list[dict]:
    """Главная функция: ищет каналы/чаты по пакету ключевых слов."""
    queries = KEYWORD_PACKS.get(pack)
    if not queries:
        return []

    existing = set(await list_dynamic_chats())
    # static target groups тоже знаем
    try:
        from config import TARGET_GROUPS
        existing |= {g.lower() for g in TARGET_GROUPS}
    except Exception:
        pass

    seen: dict[str, dict] = {}
    for q in queries:
        try:
            res = await user_client(SearchRequest(q=q, limit=limit_per_query))
        except Exception as e:
            log.warning("search '%s' failed: %s", q, e)
            continue
        for chat in res.chats:
            cand = _candidate_dict(chat, q)
            if not cand:
                continue
            if cand["username"] in existing:
                continue  # уже отслеживается
            sc = _score(cand)
            if sc <= 0:
                continue
            cand["score"] = sc
            # dedup по username, оставляем лучший score
            prev = seen.get(cand["username"])
            if prev is None or sc > prev["score"]:
                seen[cand["username"]] = cand

    ranked = sorted(seen.values(), key=lambda c: c["score"], reverse=True)
    return ranked[:max_results]
