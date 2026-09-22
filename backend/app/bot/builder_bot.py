import json
import logging
import random
from datetime import datetime, timezone

from ..core import events, redis as core_redis
from ..modules.builder import service
from ..modules.builder.models import Quest, QuestRun
from ..modules.users.models import User
from .pulse_bot import _send

log = logging.getLogger("bot")

STATE_TTL = 60 * 60  # 1 час — квест может идти дольше опроса

NO_QUESTS = "Квестов пока нет."
INTERRUPTED = "Квест прерван."
CLOSED = "Квест закрыт."
FINISHED = "Квест завершён! Баллы: {score}"


def _r():
    return core_redis.get_redis()


def _state_key(vk_id: int) -> str:
    return f"queststate:{vk_id}"


def _clear_foreign_states(vk_id: int):
    """Чужие сценарии гасим при старте своего — цифра «1» не должна
    одновременно отвечать в опрос и выбирать квест."""
    return _r().delete(f"pollstate:{vk_id}", f"bridgestate:{vk_id}")


def _kb_quest(block_id: str, options: list[str]) -> str:
    rows = []
    for i in range(0, len(options), 2):
        rows.append([
            {"action": {"type": "text", "label": opt,
                        "payload": json.dumps({"quest": "ans", "block": block_id,
                                               "value": opt})},
             "color": "secondary"}
            for opt in options[i:i + 2]
        ])
    return json.dumps({"one_time": True, "buttons": rows}, ensure_ascii=False)


def _kb_next(block_id: str) -> str:
    return json.dumps({"one_time": True, "buttons": [[
        {"action": {"type": "text", "label": "Дальше",
                    "payload": json.dumps({"quest": "next", "block": block_id})},
         "color": "primary"}]]}, ensure_ascii=False)


def _blocks(quest: Quest) -> dict:
    return service.blocks_map(quest)


def _next_block_id(quest: Quest, blocks: dict, block_id: str, last_value: str | None) -> str | None:
    """Переход из блока; branch-резолв в общем сервисе."""
    return service.resolve_next(blocks, block_id, last_value)


async def handle_quest(event, vk):
    """Команда «квест»: список published квестов класса ученика."""
    vk_id, peer = event["vk_user_id"], event["peer_id"]
    u = await User.find_one(User.vk_id == vk_id)
    if not u or not u.class_id:
        return
    await _clear_foreign_states(vk_id)
    quests = await Quest.find(Quest.status == "published",
                              Quest.class_id == str(u.class_id)).to_list()
    if not quests:
        await _send(vk, peer, NO_QUESTS)
        return
    lines = "\n".join(f"{i + 1}. {q.title}" for i, q in enumerate(quests))
    await _r().set(_state_key(vk_id),
                   json.dumps({"flow": "choose", "ids": [str(q.id) for q in quests]}),
                   ex=STATE_TTL)
    await _send(vk, peer, f"Доступные квесты:\n{lines}\n\nОтправь цифру, чтобы начать.")


def _next_block_id(quest: Quest, blocks: dict, block_id: str, last_value: str | None) -> str | None:
    """Переход из блока; branch-блоки не показываются — резолвим сразу
    (branch на branch допустим, циклы валидатор запрещает, так что loop конечен)."""
    bid = block_id
    while True:
        b = blocks[bid]
        if b["type"] == "end":
            return bid
        if b["type"] == "branch":
            bid = b["then"] if last_value == b["condition"]["answer"] else b["else"]
            continue
        return bid


async def send_block(vk, peer_id: int, quest: Quest, run: QuestRun,
                     block_id: str, now: datetime | None = None):
    blocks = _blocks(quest)
    b = blocks[block_id]
    if b["type"] == "question":
        await _r().set(_state_key(peer_id),
                       json.dumps({"flow": "play", "quest_id": str(quest.id),
                                   "run_id": str(run.id), "block_id": block_id}),
                       ex=STATE_TTL)
        await _send(vk, peer_id, b["text"], _kb_quest(block_id, b["options"]))
    elif b["type"] == "hint":
        await _r().set(_state_key(peer_id),
                       json.dumps({"flow": "play", "quest_id": str(quest.id),
                                   "run_id": str(run.id), "block_id": block_id}),
                       ex=STATE_TTL)
        await _send(vk, peer_id, b["text"], _kb_next(block_id))
    else:  # end — финал
        run.finished = True
        run.score = b["score"]
        run.finished_at = now or datetime.now(timezone.utc)
        # end попадает в trace — иначе воронка статистики покажет на финале ноль
        run.trace.append({"block_id": block_id, "value": None})
        await run.save()
        await _r().delete(_state_key(peer_id))
        await _send(vk, peer_id, FINISHED.format(score=run.score))
        await events.publish("quest.finished", quest_id=str(quest.id),
                             run_id=str(run.id), score=run.score)


async def _start_run(vk, vk_id: int, peer_id: int, quest: Quest):
    u = await User.find_one(User.vk_id == vk_id)
    if not u:
        return
    run = await QuestRun(quest_id=str(quest.id), user_id=str(u.id), trace=[]).insert()
    blocks = _blocks(quest)
    first = quest.structure["blocks"][0]["id"]
    target = _next_block_id(quest, blocks, first, None)
    await send_block(vk, peer_id, quest, run, target, None)


async def handle_message(event, vk, now: datetime | None = None):
    """Кнопки и текст квест-сценария. Не наш payload/state — молча."""
    vk_id, peer = event["vk_user_id"], event["peer_id"]
    r = _r()
    state_raw = await r.get(_state_key(vk_id))
    state = None

    raw = event.get("payload")
    p = None
    if raw:
        try:
            p = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            return
        if not isinstance(p, dict) or p.get("quest") not in ("ans", "next"):
            return  # чужой/битый payload — молча
        if not state_raw:
            return

    def _load_state():
        nonlocal state
        try:
            state = json.loads(state_raw)
        except ValueError:
            state = None
        return state

    if not p:
        text = (event.get("text") or "").strip()
        if not state_raw:
            return
        if not _load_state():
            await r.delete(_state_key(vk_id))
            return
        if state.get("flow") == "play" and text == "стоп":
            await r.delete(_state_key(vk_id))
            await _send(vk, peer, INTERRUPTED)
            return
        if state.get("flow") == "choose" and text.isdigit():
            ids = state.get("ids", [])
            i = int(text) - 1
            if not (0 <= i < len(ids)):
                return
            quest = await Quest.get(ids[i])
            if not quest or quest.status != "published":
                await r.delete(_state_key(vk_id))
                await _send(vk, peer, CLOSED)
                return
            await _start_run(vk, vk_id, peer, quest)
        return

    # payload-кнопка: quest=ans / quest=next
    if not _load_state():
        await r.delete(_state_key(vk_id))
        return
    if state.get("flow") != "play":
        return
    try:
        quest = await Quest.get(state["quest_id"])
        run = await QuestRun.get(state["run_id"])
    except Exception:
        return
    if not quest or not run:
        return
    if quest.status != "published":
        await r.delete(_state_key(vk_id))
        await _send(vk, peer, CLOSED)
        return
    blocks = _blocks(quest)
    block_id = state["block_id"]
    if block_id not in blocks:
        return
    if p.get("block") != block_id:
        return  # stale-кнопка (дубль «Дальше»/ответ) от предыдущего блока
    b = blocks[block_id]
    if p["quest"] == "ans" and b["type"] != "question":
        return
    if p["quest"] == "next" and b["type"] != "hint":
        return
    value = str(p["value"]) if p["quest"] == "ans" else None
    try:
        nxt = b["next"]
    except KeyError:
        return  # кривой payload на блоке без next — молча
    run.trace.append({"block_id": block_id, "value": value})
    await run.save()
    target = _next_block_id(quest, blocks, nxt, value)
    await send_block(vk, peer, quest, run, target, now=now)
