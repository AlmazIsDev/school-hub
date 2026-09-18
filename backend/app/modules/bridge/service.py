from datetime import datetime, timezone

from ..users import service as users_service
from .models import Ban, StopWord, TutorPair


async def check_text(text: str) -> bool:
    """True = текст чистый. Substring по стоп-словам из БД — без морфологии.
    ponytail: substring ловит «мат» в «математике» — держи список от коротких корней,
    по словам/морфологии если ложные срабатывания станут реальной проблемой."""
    low = text.lower()
    words = [w.word for w in await StopWord.find_all().to_list()]
    return not any(w in low for w in words)


async def is_banned(user_id: str) -> bool:
    now = datetime.now(timezone.utc)
    bans = await Ban.find(Ban.user_id == user_id).to_list()
    return any(b.until is None or b.until > now for b in bans)


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
