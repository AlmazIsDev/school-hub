from datetime import datetime, timezone

from ..users import service as users_service
from .models import Ban, StopWord, TutorPair


async def text_hit(text: str, school_id: str | None = None) -> str | None:
    """Первое стоп-слово в тексте или None. Substring по списку из БД - без морфологии.
    ponytail: substring ловит «мат» в «математике» - держи список от коротких корней,
    по словам/морфологии если ложные срабатывания станут реальной проблемой."""
    low = text.lower()
    flt = {"school_id": school_id} if school_id else {}
    for w in await StopWord.find(flt).to_list():
        if w.word in low:
            return w.word
    return None


async def check_text(text: str, school_id: str | None = None) -> bool:
    """True = текст чистый."""
    return await text_hit(text, school_id) is None


async def active_ban(user_id: str) -> Ban | None:
    now = datetime.now(timezone.utc)
    bans = await Ban.find(Ban.user_id == user_id).to_list()
    for b in bans:
        if b.until is None:
            return b
        # mongomock в тестах теряет tzinfo - приводим наивное время к UTC
        until = b.until if b.until.tzinfo else b.until.replace(tzinfo=timezone.utc)
        if until > now:
            return b
    return None


async def is_banned(user_id: str) -> bool:
    return await active_ban(user_id) is not None


async def helper_stats(user_id: str) -> dict:
    """Рейтинг помощника: закрытые пары + средняя оценка."""
    pairs = await TutorPair.find(
        TutorPair.helper_id == user_id, TutorPair.status == "closed").to_list()
    scores = [p.helper_score for p in pairs if p.helper_score is not None]
    return {"pairs": len(pairs),
            "avg_score": round(sum(scores) / len(scores), 2) if scores else None}


async def full_name(user_id: str) -> str:
    u = await users_service.by_id(user_id)
    return u.full_name if u else user_id
