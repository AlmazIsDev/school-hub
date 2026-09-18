import json
import logging
import uuid
from datetime import datetime, timezone

from ..core import redis as core_redis
from ..modules.bridge import service as bridge_service
from ..modules.bridge.models import (
    Ban,
    HelpRequest,
    HelperTopic,
    PairMessage,
    Report,
    TutorPair,
)
from ..modules.users import service as users_service
from ..modules.users.models import User
from .pulse_bot import _send

log = logging.getLogger("bot")

STATE_TTL = 60 * 10
MAX_ACTIVE_PAIRS = 3  # потолок пар на одного помощника

EXPIRED = "Сценарий истёк. Начни заново."
IN_PAIR = "Ты уже в паре. Напиши «закончить», когда завершите."

ASK_TOPIC = "Какой предмет? Напиши тему одним сообщением."
CONFIRM = "Регистрируем тебя как помощника по теме «{topic}»?"
NOT_FOUND = ("Пока никого нет по теме «{topic}». Заявка висит — сообщим, "
             "как найдётся помощник.")
NO_PAIR = "Активной пары нет. Напиши «нужна помощь» или «стать помощником»."
STOP_HIT = ("Сообщение не доставлено: обнаружено запрещённое слово. "
            "Модераторы увидят репорт.")
NOT_BOUND = "Напарник не привязал VK — сообщение сохранено, но не доставлено."


def _r():
    return core_redis.get_redis()


def _state_key(vk_id: int) -> str:
    return f"bridgestate:{vk_id}"


async def _set_state(vk_id: int, state: dict):
    # чужой активный сценарий гасим — кнопки не должны стартовать два сценария сразу
    await _r().delete(f"queststate:{vk_id}", f"pollstate:{vk_id}")
    await _r().set(_state_key(vk_id), json.dumps(state, ensure_ascii=False), ex=STATE_TTL)


def _kb(payload_name: str, labels: list[list[str]]) -> str:
    return json.dumps({"one_time": True, "buttons": [
        [{"action": {"type": "text", "label": l,
                     "payload": json.dumps({"bridge": payload_name, "v": l})},
          "color": "secondary"} for l in row]
        for row in labels]}, ensure_ascii=False)


def _kb_yesno() -> str:
    return _kb("confirm", [["Да", "Нет"]])


def _kb_rate() -> str:
    return _kb("rate", [["1", "2", "3"], ["4", "5"]])


def _parse_payload(raw) -> dict | None:
    if raw is None:
        return None
    try:
        p = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return None
    return p if isinstance(p, dict) else None


async def _publish(type_: str, **data):
    try:
        await _r().publish("events", json.dumps({"type": type_, **data}))
    except Exception:
        log.warning("%s не опубликован: %s", type_, data)


async def _user_by_vk(vk_id: int) -> User | None:
    return await User.find_one(User.vk_id == vk_id)


async def _active_pair(user_id: str) -> TutorPair | None:
    return await TutorPair.find_one(
        TutorPair.status == "active",
        {"$or": [{"helper_id": user_id}, {"seeker_id": user_id}]},
    )


async def _active_ban(user_id: str) -> Ban | None:
    return await bridge_service.active_ban(user_id)


async def _guard_ban(user_id: str, vk, peer_id: int) -> bool:
    """True = юзер забанен, дальнейшую обработку прекратить."""
    b = await _active_ban(user_id)
    if not b:
        return False
    until = b.until.strftime("%d.%m.%Y %H:%M UTC") if b.until else "навсегда"
    await _send(vk, peer_id, f"Вы заблокированы до {until}.")
    return True


async def _best_helper(topic: str, exclude: str) -> str | None:
    """Кандидат по теме: не сам, не в бане, vk привязан; минимум активных пар.
    ponytail: N+1 по кандидатам (пользователь + баны + пары на каждого) —
    при школьных объёмах (десятки тем/кандидатов) норм; если станет больно,
    агрегировать пары одним запросом и кэшировать баны."""
    best, best_n = None, None
    for t in await HelperTopic.find(HelperTopic.topic == topic).to_list():
        if t.user_id == exclude:
            continue
        u = await users_service.by_id(t.user_id)
        if not u or u.vk_id is None:
            continue
        if await bridge_service.is_banned(t.user_id):
            continue
        n = len(await TutorPair.find(
            TutorPair.helper_id == t.user_id, TutorPair.status == "active").to_list())
        if n >= MAX_ACTIVE_PAIRS:
            continue
        if best is None or n < best_n:
            best, best_n = t.user_id, n
    return best


async def _create_pair(topic: str, request: HelpRequest, helper_id: str, vk) -> TutorPair | None:
    # никто из участников не должен быть в другой активной паре
    if await _active_pair(helper_id) or await _active_pair(request.user_id):
        return None
    pair = await TutorPair(
        request_id=str(request.id), helper_id=helper_id, seeker_id=request.user_id,
        chat_key=uuid.uuid4().hex,
    ).insert()
    request.status = "paired"
    await request.save()
    helper = await users_service.by_id(helper_id)
    seeker = await users_service.by_id(request.user_id)
    hint = "\nПиши сюда обычными сообщениями — пересллю напарнику. Код чата: %s" % pair.chat_key
    if helper and helper.vk_id:
        await _send(vk, helper.vk_id,
                    f"Новая пара по теме «{topic}»: {seeker.full_name if seeker else 'ученик'}.{hint}")
    if seeker and seeker.vk_id:
        await _send(vk, seeker.vk_id,
                    f"Нашёлся помощник по теме «{topic}»: {helper.full_name if helper else helper_id}.{hint}")
    await _publish("bridge.pair_created", pair_id=str(pair.id),
                   helper_id=helper_id, seeker_id=request.user_id, topic=topic)
    return pair


async def try_match(topic: str, vk) -> int:
    """Waiting-заявки по теме → пары. Вызывается после «нужна помощь»
    и после регистрации помощника. Возвращает число созданных пар."""
    created = 0
    for req in await HelpRequest.find(
            HelpRequest.topic == topic, HelpRequest.status == "waiting"
    ).sort("+created_at").to_list():
        if await _active_ban(req.user_id):
            continue
        helper_id = await _best_helper(topic, exclude=req.user_id)
        if not helper_id:
            continue
        if not await _create_pair(topic, req, helper_id, vk):
            continue
        created += 1
    return created


async def start_become_helper(event, vk):
    vk_id, peer = event["vk_user_id"], event["peer_id"]
    u = await _user_by_vk(vk_id)
    if not u:
        return
    if await _guard_ban(str(u.id), vk, peer):
        return
    await _set_state(vk_id, {"flow": "become_helper", "step": "topic"})
    await _send(vk, peer, ASK_TOPIC)


async def start_need_help(event, vk):
    vk_id, peer = event["vk_user_id"], event["peer_id"]
    u = await _user_by_vk(vk_id)
    if not u:
        return
    if await _guard_ban(str(u.id), vk, peer):
        return
    if await _active_pair(str(u.id)):
        await _send(vk, peer, IN_PAIR)
        return
    await _set_state(vk_id, {"flow": "need_help", "step": "topic"})
    await _send(vk, peer, ASK_TOPIC)


async def start_report(event, vk):
    vk_id, peer = event["vk_user_id"], event["peer_id"]
    u = await _user_by_vk(vk_id)
    if not u:
        return
    if await _guard_ban(str(u.id), vk, peer):
        return
    pair = await _active_pair(str(u.id))
    if not pair:
        await _send(vk, peer, NO_PAIR)
        return
    other = pair.seeker_id if str(pair.helper_id) == str(u.id) else pair.helper_id
    await _set_state(vk_id, {"flow": "report", "reporter": str(u.id), "reported": other})
    await _send(vk, peer, "Опиши проблему одним сообщением — жалоба уйдёт модераторам.")


async def finish_pair(event, vk):
    vk_id, peer = event["vk_user_id"], event["peer_id"]
    u = await _user_by_vk(vk_id)
    if not u:
        return
    pair = await _active_pair(str(u.id))
    if not pair:
        await _send(vk, peer, NO_PAIR)
        return
    pair.status = "closed"
    pair.closed_at = datetime.now(timezone.utc)
    await pair.save()
    if pair.request_id:
        req = await HelpRequest.get(pair.request_id)
        if req and req.status == "paired":
            req.status = "closed"
            await req.save()
    await _publish("bridge.pair_closed", pair_id=str(pair.id),
                   helper_score=pair.helper_score, seeker_score=pair.seeker_score)
    my_role = "helper" if str(pair.helper_id) == str(u.id) else "seeker"
    other_id = pair.seeker_id if my_role == "helper" else pair.helper_id
    for member_id, role in ((str(u.id), my_role), (other_id, "seeker" if my_role == "helper" else "helper")):
        member = await users_service.by_id(member_id)
        if not member or member.vk_id is None:
            continue
        await _set_state(member.vk_id, {"flow": "rate", "pair_id": str(pair.id), "role": role})
        await _send(vk, member.vk_id, "Пара закрыта. Оцените помощь от 1 до 5:", _kb_rate())


async def _on_confirm(payload: dict, state: dict, event, vk):
    vk_id, peer = event["vk_user_id"], event["peer_id"]
    await _r().delete(_state_key(vk_id))
    if payload.get("v") != "Да":
        await _send(vk, peer, "Регистрацию помощника отменили.")
        return
    topic = state.get("topic", "")
    u = await _user_by_vk(vk_id)
    if u and not await HelperTopic.find_one(
            HelperTopic.user_id == str(u.id), HelperTopic.topic == topic):
        await HelperTopic(user_id=str(u.id), topic=topic).insert()
    await _send(vk, peer, f"Готово! Ты в списке помощников по теме «{topic}».")
    n = await try_match(topic, vk)
    if n:
        await _send(vk, peer, f"Сразу подобрал ожидающие заявки: создано пар — {n}.")


async def _on_rate(payload: dict, state: dict, event, vk):
    vk_id, peer = event["vk_user_id"], event["peer_id"]
    await _r().delete(_state_key(vk_id))
    try:
        score = int(payload.get("v"))
    except (TypeError, ValueError):
        return
    if not 1 <= score <= 5 or state.get("flow") != "rate":
        return
    pair = await TutorPair.get(state["pair_id"])
    if not pair:
        return
    if state["role"] == "helper":
        pair.helper_score = score
    else:
        pair.seeker_score = score
    await pair.save()
    await _send(vk, peer, "Спасибо за оценку!")


async def _on_state_text(state: dict, text: str, event, vk):
    vk_id, peer = event["vk_user_id"], event["peer_id"]
    flow = state.get("flow")
    if flow == "become_helper" and state.get("step") == "topic":
        state.update(step="confirm", topic=text)
        await _set_state(vk_id, state)
        await _send(vk, peer, CONFIRM.format(topic=text), _kb_yesno())
    elif flow == "need_help" and state.get("step") == "topic":
        await _r().delete(_state_key(vk_id))
        u = await _user_by_vk(vk_id)
        if not u:
            return
        req = await HelpRequest(user_id=str(u.id), topic=text).insert()
        await try_match(text, vk)
        fresh = await HelpRequest.get(req.id)
        if fresh.status == "waiting":
            await _send(vk, peer, NOT_FOUND.format(topic=text))
    elif flow == "report":
        await _r().delete(_state_key(vk_id))
        await Report(reporter_id=state.get("reporter", ""), reported_user_id=state["reported"],
                     reason=text).insert()
        await _send(vk, peer, "Жалоба отправлена модераторам.")


async def _forward_if_paired(event, vk):
    vk_id, peer = event["vk_user_id"], event["peer_id"]
    text = (event.get("text") or "").strip()
    u = await _user_by_vk(vk_id)
    if not u:
        return
    if await _guard_ban(str(u.id), vk, peer):
        return
    pair = await _active_pair(str(u.id))
    if not pair:
        return
    msg = await PairMessage(pair_id=str(pair.id), sender_id=str(u.id), text=text).insert()
    hit = await bridge_service.text_hit(text)
    if hit:
        # авто-репорт: не доставляем, автор — нарушитель
        await Report(reporter_id="system", reported_user_id=str(u.id),
                     message_id=str(msg.id), reason=f"авто: стоп-слово «{hit}»").insert()
        await _send(vk, peer, STOP_HIT)
        return
    other_id = pair.seeker_id if str(pair.helper_id) == str(u.id) else pair.helper_id
    other = await users_service.by_id(other_id)
    if other and other.vk_id:
        await _send(vk, other.vk_id, f"Собеседник: {text}")
    else:
        await _send(vk, peer, NOT_BOUND)


async def handle_message(event, vk):
    """Вызывается после pulse-обработки: кнопки bridge-сценариев, текст
    активных state-машин и пересылка в паре."""
    vk_id = event["vk_user_id"]
    r = _r()
    if await r.exists(f"pollstate:{vk_id}"):
        return  # активен сценарий опроса — не мешаем
    state_raw = await r.get(_state_key(vk_id))
    payload = _parse_payload(event.get("payload"))
    if payload:
        kind = payload.get("bridge")
        if kind not in ("confirm", "rate"):
            return
        state = json.loads(state_raw) if state_raw else None
        # flow-гвард: stale-кнопка чужого сценария не должна срабатывать
        if state and state.get("flow") == ("become_helper" if kind == "confirm" else "rate"):
            if kind == "confirm":
                await _on_confirm(payload, state, event, vk)
            else:
                await _on_rate(payload, state, event, vk)
        else:
            await _send(vk, event["peer_id"], EXPIRED)
        return
    text = (event.get("text") or "").strip()
    if not text:
        return
    if state_raw:
        await _on_state_text(json.loads(state_raw), text, event, vk)
        return
    await _forward_if_paired(event, vk)
