import json
import logging

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException

from ...core import redis as core_redis
from ...core.security import get_current_user, require_role
from . import schemas
from .models import Post, PostIdea

router = APIRouter(prefix="/api/media", tags=["media"])
log = logging.getLogger("api")

STATUS_CHAIN = ["idea", "in_progress", "review", "published"]


def _oid(doc_id: str) -> ObjectId:
    try:
        return ObjectId(doc_id)
    except (InvalidId, TypeError):
        raise HTTPException(404, "Не найдено")


def _post_out(p: Post) -> dict:
    return {"id": str(p.id), "title": p.title, "body": p.body, "status": p.status,
            "assignee_id": p.assignee_id, "publish_at": p.publish_at,
            "created_at": p.created_at}


def _idea_out(i: PostIdea) -> dict:
    return {"id": str(i.id), "author_id": i.author_id, "text": i.text,
            "status": i.status, "created_at": i.created_at}


@router.post("/posts")
async def create_post(body: schemas.PostIn, user: dict = Depends(require_role("teacher", "admin"))):
    post = Post(title=body.title.strip(), body=body.body)
    if not post.title:
        raise HTTPException(422, "Пустой заголовок")
    await post.insert()
    return _post_out(post)


@router.get("/posts")
async def list_posts(status: str | None = None, user: dict = Depends(get_current_user)):
    # ученикам доступна только опубликованная лента, редакция — весь канбан
    if user["role"] not in ("teacher", "admin"):
        return [_post_out(p) for p in await Post.find(Post.status == "published").to_list()]
    query = Post.find(Post.status == status) if status else Post.find_all()
    return [_post_out(p) for p in await query.to_list()]


@router.patch("/posts/{post_id}")
async def patch_post(post_id: str, body: schemas.PostPatch,
                     user: dict = Depends(require_role("teacher", "admin"))):
    post = await Post.get(_oid(post_id))
    if not post:
        raise HTTPException(404, "Пост не найден")

    if body.status is not None and body.status != post.status:
        cur = STATUS_CHAIN.index(post.status)
        nxt = STATUS_CHAIN.index(body.status)
        if nxt != cur + 1:
            raise HTTPException(409, f"Статус меняется только вперёд по цепочке "
                                     f"{' -> '.join(STATUS_CHAIN)}")

    for field, value in body.model_dump(exclude_unset=True, exclude={"status"}).items():
        if field == "title":
            value = value.strip()
            if not value:
                raise HTTPException(422, "Пустой заголовок")
        setattr(post, field, value)
    published_now = False
    if body.status is not None:
        published_now = body.status == "published" and post.status != "published"
        post.status = body.status
    await post.save()
    if published_now:
        try:
            await core_redis.get_redis().publish(
                "events", json.dumps({"type": "media.published", "post_id": str(post.id)}))
        except Exception:
            # падение pub/sub не должно отменять саму публикацию
            log.exception("не опубликовали media.published post=%s", post.id)
    return _post_out(post)


@router.post("/ideas")
async def create_idea(body: schemas.IdeaIn, user: dict = Depends(get_current_user)):
    idea = PostIdea(author_id=user["id"], text=body.text.strip())
    if not idea.text:
        raise HTTPException(422, "Пустая идея")
    await idea.insert()
    return _idea_out(idea)


@router.get("/ideas")
async def list_ideas(status: str | None = None,
                     user: dict = Depends(require_role("teacher", "admin"))):
    query = PostIdea.find(PostIdea.status == status) if status else PostIdea.find_all()
    return [_idea_out(i) for i in await query.to_list()]


async def _resolve_idea(idea_id: str) -> PostIdea:
    # ponytail: check-then-save — параллельные accept дадут два поста; лечится
    # find_one_and_update с условием status=new, на демо-объёмах не нужно
    idea = await PostIdea.get(_oid(idea_id))
    if not idea:
        raise HTTPException(404, "Идея не найдена")
    if idea.status != "new":
        raise HTTPException(409, "Идея уже обработана")
    return idea


@router.post("/ideas/{idea_id}/accept")
async def accept_idea(idea_id: str, user: dict = Depends(require_role("teacher", "admin"))):
    idea = await _resolve_idea(idea_id)
    idea.status = "accepted"
    await idea.save()
    post = Post(title=idea.text[:60], body=idea.text)
    await post.insert()
    return {"idea": _idea_out(idea), "post": _post_out(post)}


@router.post("/ideas/{idea_id}/reject")
async def reject_idea(idea_id: str, user: dict = Depends(require_role("teacher", "admin"))):
    idea = await _resolve_idea(idea_id)
    idea.status = "rejected"
    await idea.save()
    return _idea_out(idea)
