from datetime import datetime, timedelta, timezone

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException

from ...core.security import require_role
from . import schemas, service
from .models import Ban, HelperTopic, Report, StopWord

router = APIRouter(prefix="/api/bridge", tags=["bridge"])


def _get(doc_id: str):
    try:
        return ObjectId(doc_id)
    except (InvalidId, TypeError):
        raise HTTPException(404, "Не найдено")


@router.get("/reports")
async def list_reports(status: str = "open",
                       user: dict = Depends(require_role("teacher", "admin"))):
    if status not in ("open", "resolved"):
        raise HTTPException(422, "status: open|resolved")
    rows = await Report.find(Report.status == status).to_list()
    out = []
    for r in rows:
        out.append({"id": str(r.id), "reporter_id": r.reporter_id,
                    "reported_user_id": r.reported_user_id,
                    "reported_full_name": await service.full_name(r.reported_user_id),
                    "message_id": r.message_id, "reason": r.reason, "status": r.status,
                    "created_at": r.created_at})
    return out


@router.post("/reports/{report_id}/resolve")
async def resolve_report(report_id: str, body: schemas.ResolveIn,
                         user: dict = Depends(require_role("teacher", "admin"))):
    report = await Report.get(_get(report_id))
    if not report:
        raise HTTPException(404, "Жалоба не найдена")
    if report.status == "resolved":
        raise HTTPException(409, "Жалоба уже разобрана")

    if body.action in ("ban_days", "ban_forever"):
        if body.action == "ban_days":
            if body.days is None:
                raise HTTPException(422, "Нужен days для ban_days")
            until = datetime.now(timezone.utc) + timedelta(days=body.days)
        else:
            until = None
        await Ban(user_id=report.reported_user_id, until=until,
                  reason=f"жалоба {report.id}").insert()
    report.status = "resolved"
    await report.save()
    return {"id": str(report.id), "status": report.status}


@router.get("/bans")
async def list_bans(user: dict = Depends(require_role("teacher", "admin"))):
    rows = await Ban.find_all().to_list()
    return [{"id": str(b.id), "user_id": b.user_id,
             "full_name": await service.full_name(b.user_id),
             "until": b.until, "reason": b.reason, "created_at": b.created_at}
            for b in rows]


@router.delete("/bans/{ban_id}")
async def delete_ban(ban_id: str, user: dict = Depends(require_role("teacher", "admin"))):
    ban = await Ban.get(_get(ban_id))
    if not ban:
        raise HTTPException(404, "Бан не найден")
    await ban.delete()
    return {"ok": True}


@router.get("/stop-words")
async def list_stop_words(user: dict = Depends(require_role("admin"))):
    return [{"id": str(w.id), "word": w.word} for w in await StopWord.find_all().to_list()]


@router.post("/stop-words")
async def add_stop_word(body: schemas.StopWordIn,
                        user: dict = Depends(require_role("admin"))):
    word = body.word.strip().lower()
    if not word:
        raise HTTPException(422, "Пустое слово")
    if await StopWord.find_one(StopWord.word == word):
        raise HTTPException(409, "Такое стоп-слово уже есть")
    w = StopWord(word=word)
    await w.insert()
    return {"id": str(w.id), "word": w.word}


@router.delete("/stop-words/{word_id}")
async def delete_stop_word(word_id: str, user: dict = Depends(require_role("admin"))):
    w = await StopWord.get(_get(word_id))
    if not w:
        raise HTTPException(404, "Стоп-слово не найдено")
    await w.delete()
    return {"ok": True}


@router.get("/helpers")
async def helpers_rating(user: dict = Depends(require_role("teacher", "admin"))):
    topics = await HelperTopic.find_all().to_list()
    by_user: dict[str, list[str]] = {}
    for t in topics:
        by_user.setdefault(t.user_id, []).append(t.topic)
    out = []
    for uid, tps in by_user.items():
        stats = await service.helper_stats(uid)
        out.append({"user_id": uid, "full_name": await service.full_name(uid),
                    "topics": sorted(set(tps)), **stats})
    # навсегда без оценок — вниз, с оценками — по убыванию средней
    out.sort(key=lambda x: (x["avg_score"] is None, -(x["avg_score"] or 0)))
    return out
