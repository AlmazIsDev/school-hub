import re
import unicodedata
from datetime import datetime, timezone

from ..users import service as users_service
from .models import Ban, StopWord, TutorPair


# ---------- антемат: регексы поверх настраиваемого БД-списка ----------

RU_MAT_RE = re.compile(
    r"(?<!\w)(?:(?:вы|за|до|на|об|от|по|пере|при|про|раз|съ|у|из|под|не|вз|воз|низ|пред|со|ото|обез)?[её]б(?!о[рй]|рач)\w*"
    r"|(?:н[иеа]|ра[зс]|[зд]?[ао](?:т|дн[оа])?|с(?:м[еи])?|а[пб]ч|в[зы]|про|по|у|за|вы|об|от|пере|под|над|пред|не|ни)?-?ху(?:[яйиеёю]|л+и(?!ган))\w*"
    r"|(?:вы)?бл(?:[эя]|еа?)(?:[дт][ьъ]?)?"
    r"|(?:вы|за|до|на|об|от|по|пере|при|про|раз|съ|у|из|под|не|вз|воз|низ|пред|со|ото|обез)?п[иеё]зд\w*"
    r"|(?:п[иеё]д[ао]?р|педик)\w*"
    r"|(?:о[тб]?|про|на|вы|за|по|пере|при|у|из|под|не)?манд(?:[ауеыи](?:л(?:и[сзщ])?[ауеиы])?|ой|[ао]в\w*|юк(?:ов|[ауи])?|е[нт]ь|ища)\w*"
    r"|(?:о[тб]?|про|на|вы|за|по|пере|при|у|из|под|не)?муд(?:[яаиое]\w*|е?н(?:[ьюия]|ей)|ак|ил|озвон)\w*"
    r"|м[ао]л[ао]ф[ьъ](?:[яиюе]|[еёо]й)\w*"
    r"|елд[ауые]\w*"
    r"|ля[тд]ь\w*"
    r"|(?:[нз]а|по|на|в|у|о[тб])х(?:уй|уя|ую|уё|уе|уи|ер|рен)\w*"
    r"|залуп\w*"
    r"|жоп\w*"
    r"|сук(?:[аиуеой]|ин|чк)\w*"
    r"|(?:за|вы|под|на|об|по|пере|при|про|раз|с|у|из)?трах\w*"
    r"|дроч\w*"
    r"|шлюх\w*"
    r"|(?:гандон|гондон)\w*"
    r"|анус\w*"
    r"|(?:мразь|мрази|твар(?:ь|и|ью))\w*)"
    r"(?!\w)",
    re.IGNORECASE,
)

EN_MAT_RE = re.compile(
    r"\b(?:"
    r"m+o+t+h+e?r+f+u+c?k+(?:ing|ers?)?"
    r"|f+u+c?k+(?:ing|in|ed|ers?|s|off)?"
    r"|s+h+i+t+(?:s|ty|head|hole)?"
    r"|b+i+t+c+h+(?:es)?"
    r"|c+u+n+t+s?"
    r"|d+i+c+k+(?:s|head)?"
    r"|c+o+c+k+(?:s|sucker)?"
    r"|a+s+s+h+o+l+e+s?"
    r"|b+a+s+t+e?r+d+s?"
    r"|w+h+o+r+e+s?"
    r"|s+l+u+t+s?"
    r"|n+i+g+g+(?:e?r|a)s?"
    r"|c+u+m+"
    r"|j+i+z+z"
    r"|d+i+l+d+o+s?"
    r"|p+r+i+c+k+s?"
    r"|t+w+a+t+s?"
    r"|b+o+l+l+o+c+k+s"
    r"|w+a+n+k+(?:ers?)?"
    r"|g+a+n+g+b+a+n+g"
    r")\b",
    re.IGNORECASE,
)

# латинские омоглифы -> кириллица (n->п из референса убрал: даёт «no»->«по» и ложные склейки)
_RU_OMO = str.maketrans({"a": "а", "e": "е", "o": "о", "p": "р", "c": "с", "x": "х", "y": "у",
                         "k": "к", "m": "м", "t": "т", "h": "н", "b": "в",
                         "0": "о", "3": "з", "6": "б", "4": "ч", "@": "а", "$": "с"})
# кириллица и leet -> латиница для английского регекса
_EN_OMO = str.maketrans({"а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y",
                         "к": "k", "м": "m", "т": "t", "в": "b", "н": "h",
                         "0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "@": "a", "$": "s"})


def _normalize(text: str, omoglyphs: dict) -> str:
    s = unicodedata.normalize("NFKC", text).lower().translate(omoglyphs).replace("_", "")
    s = re.sub(r"(?<=\w)[^\w\s]+(?=\w)", "", s)   # х.у.й -> хуй
    s = re.sub(r"(?<=\b\w)\s+(?=\w\b)", "", s)    # п и з д е ц -> пиздец, но «иди в школу» не трогаем
    s = re.sub(r"([^\W\d_])\1{2,}", r"\1\1", s)   # хуууй -> хууй
    return s


async def text_hit(text: str, school_id: str | None = None) -> str | None:
    """Первое совпадение или None. Сначала substring по стоп-словам школы из БД,
    потом регексы мата по нормализованному тексту (ловит х_у_й, xyй, f u c k)."""
    low = text.lower()
    flt = {"school_id": school_id} if school_id else {}
    for w in await StopWord.find(flt).to_list():
        if w.word in low:
            return w.word
    m = RU_MAT_RE.search(_normalize(text, _RU_OMO))
    if m:
        return m.group(0)
    m = EN_MAT_RE.search(_normalize(text, _EN_OMO))
    if m:
        return m.group(0)
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
