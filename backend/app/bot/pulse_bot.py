import asyncio
import json
import logging
import random

from bson import ObjectId
from bson.errors import InvalidId

from ..core import redis as core_redis
from ..modules.pulse.models import Poll, PollAnswer
from ..modules.users.models import User

log = logging.getLogger("bot")

STATE_TTL = 60 * 30
DEDUP_TTL = 86400 * 2

ALREADY = "Вы уже ответили в этом опросе."
CLOSED = "Опрос закрыт."
THANKS = "Спасибо, ответы приняты!"


def _r():
    return core_redis.get_redis()


def _state_key(vk_id: int) -> str:
    return f"pollstate:{vk_id}"


def build_keyboard(poll_id: str, idx: int) -> str:
    rows = []
    for row in ([1, 2, 3], [4, 5]):
        rows.append([
            {
                "action": {
                    "type": "text",
                    "label": str(v),
                    "payload": json.dumps({"poll": poll_id, "q": idx, "v": str(v)}),
                },
                "color": "secondary",
            }
            for v in row
        ])
    return json.dumps({"one_time": True, "buttons": rows}, ensure_ascii=False)


async def _send(vk, peer_id: int, message: str, keyboard: str | None = None):
    # random_id=0 VK не дедуплицирует — генерим случайный
    params = {"peer_id": peer_id, "random_id": random.randrange(2**31), "message": message}
    if keyboard:
        params["keyboard"] = keyboard
    await vk.call("messages.send", **params)


async def send_question(vk, peer_id: int, poll: Poll, idx: int):
    # state мог указывать за пределы вопросов (кривой/протухший state) —
    # трактуем как закрытый опрос; в боте peer_id == vk_id
    if idx >= len(poll.questions):
        await _r().delete(_state_key(peer_id))
        await _send(vk, peer_id, CLOSED)
        return
    q = poll.questions[idx]
    message = f"{poll.title}\nВопрос {idx + 1}/{len(poll.questions)}: {q.text}"
    kb = build_keyboard(str(poll.id), idx) if q.type == "scale1_5" else None
    await _send(vk, peer_id, message, kb)


async def start_poll(vk, vk_id: int, poll: Poll):
    # чужой активный сценарий гасим — кнопки не должны стартовать два сценария сразу
    await _r().delete(f"queststate:{vk_id}", f"bridgestate:{vk_id}")
    await _r().set(
        _state_key(vk_id),
        json.dumps({"poll_id": str(poll.id), "idx": 0}),
        ex=STATE_TTL,
    )
    await send_question(vk, vk_id, poll, 0)


async def on_published(payload: dict, vk):
    """poll.published → рассылка первого вопроса ученикам класса с vk_id."""
    try:
        poll = await Poll.get(ObjectId(payload.get("poll_id")))
    except (InvalidId, TypeError):
        poll = None
    if not poll or poll.status != "active" or poll.notified:
        return
    students = await User.find(
        User.role == "student", User.class_id == poll.class_id, User.vk_id != None  # noqa: E711
    ).to_list()
    for u in students:
        try:
            await start_poll(vk, u.vk_id, poll)
        except Exception:
            log.exception("рассылка опроса %s не дошла до vk_id=%s", poll.id, u.vk_id)
    poll.notified = True
    await poll.save()


async def handle_poll_command(event, vk):
    """«опрос» — активные опросы класса по запросу (могли пропустить рассылку)."""
    u = await User.find_one(User.vk_id == event["vk_user_id"])
    if not u or u.role != "student" or not u.class_id:
        await _send(vk, event["peer_id"], "Опросы доступны ученикам после привязки аккаунта.")
        return
    active = await Poll.find(Poll.class_id == u.class_id, Poll.status == "active").to_list()
    if not active:
        await _send(vk, event["peer_id"], "Активных опросов сейчас нет.")
        return
    # анонимные ответы: факт ответа живёт в redis-дедупе answered:{poll}:{vk}
    r = _r()
    pending = [p for p in active if not await r.exists(f"answered:{p.id}:{u.vk_id}")]
    if not pending:
        await _send(vk, event["peer_id"], "Ты уже ответил(а) во всех активных опросах. Спасибо!")
        return
    if len(pending) == 1:
        await start_poll(vk, event["vk_user_id"], pending[0])
        return
    await _send(vk, event["peer_id"],
                "Активные опросы:\n" + "\n".join(f"• {p.title}" for p in pending))


async def catch_up_unnotified(vk):
    """Догонялка при старте бота: события poll.published, потерянные
    пока бот был выключен (pub/sub без персистентности)."""
    polls = await Poll.find(Poll.status == "active", Poll.notified == False).to_list()  # noqa: E712
    for poll in polls:
        await on_published({"poll_id": str(poll.id)}, vk)


async def listen_events(vk):
    """Подписка на pub/sub канал events, переживает недоступный redis."""
    while True:
        try:
            pubsub = _r().pubsub()
            await pubsub.subscribe("events")
            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                try:
                    data = json.loads(msg["data"])
                except (ValueError, TypeError):
                    continue
                if data.get("type") == "poll.published":
                    await on_published(data, vk)
                elif data.get("type") == "media.published":
                    # локальный импорт: media_bot использует _send отсюда
                    from . import media_bot
                    await media_bot.on_published(data, vk)
        except Exception:
            log.exception("events listener crashed, reconnect in 5s")
            await asyncio.sleep(5)


async def handle_message(event: dict, vk):
    """Последний обработчик диспетчера: кнопки опроса и свободные ответы.

    Если сценарий опроса не наш (нет payload и нет state) — молча выходим,
    другие хендлеры уже отработали до нас.
    """
    vk_id = event["vk_user_id"]
    r = _r()
    state_raw = await r.get(_state_key(vk_id))

    raw_payload = event.get("payload")
    if raw_payload:
        try:
            p = json.loads(raw_payload) if isinstance(raw_payload, str) else raw_payload
        except ValueError:
            return
        if not isinstance(p, dict) or "poll" not in p:
            return
        if not state_raw:
            # state истёк/потерян — если уже отвечал, вежливо скажем
            if await r.exists(f"answered:{p['poll']}:{vk_id}"):
                await _send(vk, event["peer_id"], ALREADY)
            return
        state = json.loads(state_raw)
        if state.get("poll_id") != p["poll"] or state.get("idx") != p["q"]:
            return  # stale-кнопка от старого вопроса — молча игнор
        try:
            poll_id, idx, value = p["poll"], int(p["q"]), str(p["v"])
        except (KeyError, TypeError, ValueError):
            return  # кривой payload — молча игнор
    else:
        if not state_raw:
            return
        state = json.loads(state_raw)
        poll_id, idx = state["poll_id"], state["idx"]
        value = (event.get("text") or "").strip()
        if not value:
            return

    try:
        poll = await Poll.get(ObjectId(poll_id))
    except (InvalidId, TypeError):
        poll = None
    if not poll or poll.status != "active" or idx >= len(poll.questions):
        await r.delete(_state_key(vk_id))
        await _send(vk, event["peer_id"], CLOSED)
        return

    # Дедуп — один раз на опрос, при ответе на первый вопрос. Дальше идём по
    # state (индекс в нём гарантирует, что вопрос уже отвечен или ещё не начат).
    # ВАЖНО для аналитики (T4): state мог истечь на середине — частичные ответы
    # попадут в базу. Полнота ответа определяется наличием ответа на последний
    # вопрос — учесть при агрегации.
    if idx == 0 and not await r.set(f"answered:{poll_id}:{vk_id}", "1", nx=True, ex=DEDUP_TTL):
        await r.delete(_state_key(vk_id))
        await _send(vk, event["peer_id"], ALREADY)
        return

    try:
        await PollAnswer(poll_id=poll_id, question_idx=idx, value=value).insert()
    except Exception:
        # иначе дедуп-ключ уже съел ответ: откатываем, чтобы юзер мог повторить
        log.exception("не сохранили ответ poll=%s vk=%s", poll_id, vk_id)
        await r.delete(f"answered:{poll_id}:{vk_id}", _state_key(vk_id))
        await _send(vk, event["peer_id"], "Ошибка, попробуйте ещё раз.")
        return

    nidx = idx + 1
    if nidx >= len(poll.questions):
        await r.delete(_state_key(vk_id))
        await _send(vk, event["peer_id"], THANKS)
    else:
        await r.set(
            _state_key(vk_id),
            json.dumps({"poll_id": poll_id, "idx": nidx}),
            ex=STATE_TTL,
        )
        await send_question(vk, event["peer_id"], poll, nidx)
