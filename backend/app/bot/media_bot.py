import logging

from beanie.operators import In

from ..core import redis as core_redis
from ..modules.media.models import Post, PostIdea
from ..modules.users.models import User
from .pulse_bot import _send

log = logging.getLogger("bot")

IDEA_MAX = 1000
EDITORS_LIMIT = 10  # первые 10 редакторов с vk_id — чтобы не спамить при большом штате
BODY_PREVIEW = 400

NOT_BOUND = "Привяжи аккаунт на сайте, чтобы предлагать идеи."
IDEA_SENT = "Тема отправлена редакции."


def _r():
    return core_redis.get_redis()


async def handle_idea(event, vk):
    """Команда «идея <текст>»: PostIdea от автора по vk_id + уведомление редакции."""
    vk_id, peer = event["vk_user_id"], event["peer_id"]
    text = (event["match"].group(1) or "").strip()[:IDEA_MAX]
    if not text:
        return
    u = await User.find_one(User.vk_id == vk_id)
    if not u:
        await _send(vk, peer, NOT_BOUND)
        return
    await PostIdea(author_id=str(u.id), text=text).insert()
    await _send(vk, peer, IDEA_SENT)

    editors = await User.find(
        In(User.role, ["teacher", "admin"]),
        User.vk_id != None,  # noqa: E711
    ).sort("+created_at").limit(EDITORS_LIMIT).to_list()
    message = f"Новая идея от {u.full_name}: {text}"
    for e in editors:
        try:
            await _send(vk, e.vk_id, message)
        except Exception:
            log.exception("идея не доставлена редактору vk_id=%s", e.vk_id)


async def on_published(payload: dict, vk):
    """media.published → рассылка анонса всем student с vk_id."""
    from bson import ObjectId
    from bson.errors import InvalidId

    try:
        post = await Post.get(ObjectId(payload.get("post_id")))
    except (InvalidId, TypeError):
        return
    if not post or post.status != "published":
        return
    # дедуп: повторное событие (pub/sub redelivery) не рассылает анонс второй раз
    if not await _r().set(f"mediapublished:{post.id}", "1", nx=True, ex=604800):
        return
    students = await User.find(
        User.role == "student", User.vk_id != None  # noqa: E711
    ).to_list()
    message = f"Новая публикация: {post.title}\n{post.body[:BODY_PREVIEW]}\n\nПолностью — на сайте."
    for u in students:
        try:
            await _send(vk, u.vk_id, message)
        except Exception:
            log.exception("анонс %s не дошёл до vk_id=%s", post.id, u.vk_id)
