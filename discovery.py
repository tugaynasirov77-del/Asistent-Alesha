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


# Чатные паки — где сидит ЦА для мониторинга лидов
CHAT_PACKS: dict[str, list[str]] = {
    "beauty": [
        "владельцы салонов",
        "бьюти бизнес",
        "салоны красоты чат",
        "мастера маникюра",
        "бровисты лешмейкеры",
        "барбершоп владельцы",
        "косметологи бизнес",
    ],
    "selfworkers": [
        "самозанятые чат",
        "частная практика",
        "мастер на себя",
    ],
    "services": [
        "репетиторы чат",
        "фитнес тренеры",
        "психологи практика",
        "нутрициолог",
        "фотографы заказы",
    ],
    "automation": [
        "yclients",
        "altegio",
        "автоматизация записи",
        "crm салон",
    ],
}

# Канальные паки — каналы экспертов где можно писать smart-комментарии
CHANNEL_PACKS: dict[str, list[str]] = {
    "beauty": [
        "маркетинг салона",
        "продвижение мастера",
        "бьюти консалтинг",
        "smm салон",
        "развитие салона красоты",
        "управление салоном",
        "наставник мастеров",
        "бьюти бизнес блог",
        "обучение владельцев салонов",
    ],
    "selfworkers": [
        "самозанятый кейс",
        "личный бренд эксперт",
        "монетизация эксперта",
        "канал для самозанятых",
    ],
    "services": [
        "маркетинг для тренеров",
        "продвижение фотографа",
        "smm психолога",
        "репетитор продвижение",
        "тренер бизнес",
        "психолог как продвигать",
    ],
    "automation": [
        "yclients блог",
        "altegio новости",
        "автоматизация бизнеса канал",
        "crm для салона",
        "no-code для бизнеса",
    ],
}

# Объединённый pack для обратной совместимости
KEYWORD_PACKS = CHAT_PACKS


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


def _score(c: dict, kind: str = "both") -> float:
    p = c["participants_count"]
    if p < 200:
        return 0
    if p > 200_000:
        return 0.3
    base = min(p / 5000, 5)
    # бонусы в зависимости от типа
    if kind == "chats" and c["is_megagroup"]:
        base += 1
    if kind == "channels" and c["is_channel"]:
        base += 1
    if kind == "both" and c["is_megagroup"]:
        base += 0.5
    if c["verified"]:
        base += 0.5
    return base


async def discover_candidates(
    user_client,
    pack: str,
    kind: Literal["chats", "channels", "both"] = "both",
    limit_per_query: int = 15,
    max_results: int = 12,
) -> list[dict]:
    """Ищет кандидатов по нише.

    kind:
      "chats"    — только мегагруппы (для мониторинга лидов)
      "channels" — только broadcast-каналы (для smart-комментариев)
      "both"     — оба (обратная совместимость)
    """
    if kind == "chats":
        queries = CHAT_PACKS.get(pack, [])
    elif kind == "channels":
        queries = CHANNEL_PACKS.get(pack, [])
    else:
        queries = list({*CHAT_PACKS.get(pack, []), *CHANNEL_PACKS.get(pack, [])})

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
                continue
            # фильтр по типу — каналы / чаты
            if kind == "chats" and not cand["is_megagroup"]:
                continue
            if kind == "channels" and not cand["is_channel"]:
                continue
            sc = _score(cand, kind=kind)
            if sc <= 0:
                continue
            cand["score"] = sc
            # dedup по username, оставляем лучший score
            prev = seen.get(cand["username"])
            if prev is None or sc > prev["score"]:
                seen[cand["username"]] = cand

    ranked = sorted(seen.values(), key=lambda c: c["score"], reverse=True)
    return ranked[:max_results]
