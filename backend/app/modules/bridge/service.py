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

# знаменитый bad-words список со StackOverflow (q/23505926), 406 слов с leet-вариантами.
# Вырезал gay/lesbian/hell/damn/sex/Phuc - нормальные слова и имена для школьного чата.
EN_BADWORDS = ("ahole|anus|ash0le|asles|asholes|ass|Ass Monkey|Assface|assh0le|assh0lez|asshol"
                  "e|assholes|assholz|asswipe|azzhole|bassterds|bastard|bastards|bastardz|basterd"
                  "s|basterdz|Biatch|bitch|bitches|Blow Job|boffing|butthole|buttwipe|c0ck|c0cks|"
                  "c0k|Carpet Muncher|cawk|cawks|Clit|cnts|cntz|cock|cockhead|cock-head|cocks|Coc"
                  "kSucker|cock-sucker|crap|cum|cunt|cunts|cuntz|dick|dild0|dild0s|dildo|dildos|d"
                  "illd0|dilld0s|dominatricks|dominatrics|dominatrix|dyke|enema|f u c k|f u c k e"
                  " r|fag|fag1t|faget|fagg1t|faggit|faggot|fagit|fags|fagz|faig|fart|flipping the"
                  " bird|fuck|fucker|fuckin|fucking|fucks|Fudge Packer|fuk|Fukah|Fuken|fuker|Fuki"
                  "n|Fukk|Fukkah|Fukken|Fukker|Fukkin|g00k|h00r|h0ar|h0re|hoar|hoor|hoore|jackoff"
                  "|jap|japs|jerk-off|jisim|jiss|jizm|jizz|knob|knobs|knobz|kunt|kunts|kuntz|Lezz"
                  "ian|Lipshits|Lipshitz|masochist|masokist|massterbait|masstrbait|masstrbate|mas"
                  "terbaiter|masterbate|masterbates|Motha Fucker|Motha Fuker|Motha Fukkah|Motha F"
                  "ukker|Mother Fucker|Mother Fukah|Mother Fuker|Mother Fukkah|Mother Fukker|moth"
                  "er-fucker|Mutha Fucker|Mutha Fukah|Mutha Fuker|Mutha Fukkah|Mutha Fukker|n1gr|"
                  "nastt|nigger|nigur|niiger|niigr|orafis|orgasim|orgasm|orgasum|oriface|orifice|"
                  "orifiss|packi|packie|packy|paki|pakie|paky|pecker|peeenus|peeenusss|peenus|pei"
                  "nus|pen1s|penas|penis|penis-breath|penus|penuus|Phuck|Phuk|Phuker|Phukker|pola"
                  "c|polack|polak|Poonani|pr1c|pr1ck|pr1k|pusse|pussee|pussy|puuke|puuker|queer|q"
                  "ueers|queerz|qweers|qweerz|qweir|recktum|rectum|retard|sadist|scank|schlong|sc"
                  "rewing|semen|Sh!t|sh1t|sh1ter|sh1ts|sh1tter|sh1tz|shit|shits|shitter|Shitty|Sh"
                  "ity|shitz|Shyt|Shyte|Shytty|Shyty|skanck|skank|skankee|skankey|skanks|Skanky|s"
                  "lut|sluts|Slutty|slutz|son-of-a-bitch|tit|turd|va1jina|vag1na|vagiina|vagina|v"
                  "aj1na|vajina|vullva|vulva|w0p|wh00r|wh0re|whore|xrated|xxx|b!+ch|blowjob|clit|"
                  "arschloch|b!tch|b17ch|b1tch|bi+ch|boiolas|buceta|chink|cipa|clits|dirsa|ejakul"
                  "ate|fatass|fcuk|fux0r|hoer|hore|jism|kawk|l3itch|l3i+ch|masturbate|masterbat|m"
                  "asterbat3|motherfucker|s.o.b.|mofo|nazi|nigga|nutsack|phuck|pimpis|scrotum|sh!"
                  "t|shemale|shi+|sh!+|smut|teets|tits|boobs|b00bs|teez|testical|testicle|titt|w0"
                  "0se|wank|whoar|@$$|amcik|andskota|arse|assrammer|ayir|bi7ch|bollock|breasts|bu"
                  "tt-pirate|cabron|cazzo|chraa|chuj|Cock|daygo|dego|dike|dupa|dziwka|ejackulate|"
                  "Ekrem|Ekto|enculer|faen|fanculo|fanny|feces|feg|Felcher|ficken|fitt|Flikker|fo"
                  "reskin|Fotze|Fu|futkretzn|gook|guiena|h0r|h4x0r|helvete|honkey|Huevon|hui|inju"
                  "n|kanker|kike|klootzak|kraut|knulle|kuk|kuksuger|Kurac|kurwa|kusi|kyrpa|lesbo|"
                  "mamhoon|masturbat|merd|mibun|monkleigh|mouliewop|muie|mulkku|muschi|nazis|nepe"
                  "saurio|orospu|paska|perse|picka|pierdol|pillu|pimmel|piss|pizda|poontsee|poop|"
                  "porn|p0rn|pr0n|preteen|pula|pule|puta|puto|qahbeh|queef|rautenberg|schaffer|sc"
                  "heiss|schlampe|schmuck|screw|sharmuta|sharmute|shipal|shiz|skribz|skurwysyn|sp"
                  "hencter|spic|spierdalaj|splooge|suka|b00b|twat|vittu|wetback|wichser|wop|yed").split("|")
EN_MAT_RE = re.compile(r"\b(?:" + "|".join(map(re.escape, EN_BADWORDS)) + r")\b",
                       re.IGNORECASE)

# латинские омоглифы -> кириллица (n->п из референса убрал: даёт «no»->«по» и ложные склейки)
_RU_OMO = str.maketrans({"a": "а", "e": "е", "o": "о", "p": "р", "c": "с", "x": "х", "y": "у",
                         "k": "к", "m": "м", "t": "т", "h": "н", "b": "в",
                         "0": "о", "3": "з", "6": "б", "4": "ч", "@": "а", "$": "с"})
# кириллица и leet -> латиница для английского регекса
_EN_OMO = str.maketrans({"а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y",
                         "к": "k", "м": "m", "т": "t", "в": "b", "н": "h",
                         "0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "@": "a", "$": "s"})


def _normalize(text: str, omoglyphs: dict, strip_seps: bool = True) -> str:
    s = unicodedata.normalize("NFKC", text).lower().translate(omoglyphs).replace("_", "")
    if strip_seps:
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
    # разделители не трогаем: «!» и «+» в списке - легитимный leet (b!tch, bi+ch)
    m = EN_MAT_RE.search(_normalize(text, _EN_OMO, strip_seps=False))
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
