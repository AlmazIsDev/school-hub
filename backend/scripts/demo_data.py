"""Тестовые данные для демо-скринов: ответы в pulse, дежурства, квесты, медиа.

Идемпотентен - перед вставкой чистит свои документы по маркеру _demo=True.
Запуск: python -m scripts.demo_data
"""
import asyncio
import os
import random
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017/schoolhub")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "demo-only-not-a-secret")

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from app.core.config import settings  # noqa: E402

POLL_ID = "6ab7970126d692f271a9a164"
SCHOOL_ID = "6ab35be16350139015995d4c"
CLASS_ID = "6ab20da1be46f2558fafc765"
TEACHER_ID = "6ab20da6be46f2558fafc766"

NOW = datetime.now(timezone.utc)


async def pulse(db):
    """Ответы на открытый опрос: 18 учеников, шкала 3-5 + свободные тексты."""
    free_texts = [
        "Почему орбиты эллиптические, а не круглые?",
        "Не понял, откуда G берётся",
        "А это работает для чёрных дыр?",
        "Всё понятно, спасибо",
        "Можно задач на это побольше?",
        "Как Кавендиш измерил G, если сила такая маленькая?",
        "Отличный урок",
        "Чем отличается от закона Кулона?",
    ]
    answers = []
    for i in range(18):
        t = NOW - timedelta(hours=random.uniform(1, 40))
        answers.append({"school_id": SCHOOL_ID, "poll_id": POLL_ID, "question_idx": 0,
                        "value": str(random.choices([3, 4, 5], weights=[3, 7, 8])[0]),
                        "created_at": t, "_demo": True})
        if i < 8:
            answers.append({"school_id": SCHOOL_ID, "poll_id": POLL_ID, "question_idx": 1,
                            "value": free_texts[i], "created_at": t, "_demo": True})
    await db.pulse_answers.delete_many({"_demo": True, "poll_id": POLL_ID})
    await db.pulse_answers.insert_many(answers)


async def duty(db):
    """Зона дежурства + расписание на неделю + отметки за прошедшие дни."""
    zone_id = "6abde0000000000000000001"
    await db.duty_zones.delete_many({"_demo": True})
    await db.duty_schedules.delete_many({"_demo": True})
    await db.duty_completions.delete_many({"_demo": True})
    await db.duty_zones.insert_one({"_id": zone_id, "school_id": SCHOOL_ID,
                                    "name": "Столовая, 2 этаж", "created_at": NOW, "_demo": True})
    user_ids = [f"6abd000000000000000000{i:02d}" for i in range(1, 11)]
    week = [{"weekday": wd, "slot": slot, "user_id": uid, "_demo": True}
            for wd in range(1, 6)
            for slot, uid in [(2, user_ids[wd * 2 - 2]), (5, user_ids[wd * 2 - 1])]]
    await db.duty_schedules.insert_one({"school_id": SCHOOL_ID, "teacher_id": TEACHER_ID,
                                        "zone_id": zone_id, "week_pattern": week,
                                        "created_at": NOW, "_demo": True})
    monday = NOW - timedelta(days=NOW.weekday())
    completions = [{"school_id": SCHOOL_ID, "schedule_id": None, "weekday": wd, "slot": slot,
                    "user_id": uid, "date": (monday + timedelta(days=wd - 1))
                    .replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc),
                    "marked_at": NOW, "_demo": True}
                   for wd in range(1, min(NOW.weekday(), 4) + 1)  # прошедшие будни, выходных в расписании нет
                   for slot, uid in [(2, user_ids[wd * 2 - 2]), (5, user_ids[wd * 2 - 1])]]
    await db.duty_completions.insert_many(completions)


QUEST_STRUCTURE = {
    "blocks": [
        {"id": "q1", "type": "question", "text": "Чему равна сила притяжения между телами при удвоении расстояния?",
         "options": ["Уменьшится в 2 раза", "Уменьшится в 4 раза", "Увеличится в 4 раза", "Не изменится"], "next": "br1"},
        {"id": "br1", "type": "branch", "condition": {"answer": "Уменьшится в 4 раза"},
         "then": "q2", "else": "h1"},
        {"id": "h1", "type": "hint", "text": "Вспомни: F ~ 1/r^2. Расстояние увеличили вдвое - сила упала вчетверо.",
         "next": "q2"},
        {"id": "q2", "type": "question", "text": "Что произойдёт с силой при удвоении одной из масс?",
         "options": ["Увеличится в 2 раза", "Уменьшится в 2 раза", "Не изменится"], "next": "end"},
        {"id": "end", "type": "end", "score": 2},
    ]
}


async def builder(db):
    """Квест по физике + прогоны учеников."""
    quest_id = "6abde0000000000000000002"
    await db.builder_quests.delete_many({"_demo": True})
    await db.builder_runs.delete_many({"_demo": True})
    await db.builder_quests.insert_one({
        "_id": quest_id, "school_id": SCHOOL_ID, "teacher_id": TEACHER_ID,
        "class_id": CLASS_ID, "title": "Квест: закон всемирного тяготения",
        "structure": QUEST_STRUCTURE, "status": "published",
        "created_at": NOW - timedelta(days=2), "_demo": True})
    runs = []
    for i in range(12):
        good = i < 8
        runs.append({"school_id": SCHOOL_ID, "quest_id": quest_id,
                     "user_id": f"6abd000000000000000000{i:02d}",
                     "finished": True, "score": 2 if good else 1,
                     "trace": [{"block_id": "q1", "value": "Уменьшится в 4 раза" if good else "Уменьшится в 2 раза"},
                               {"block_id": "q2", "value": "Увеличится в 2 раза"}],
                     "started_at": NOW - timedelta(hours=random.uniform(2, 30)),
                     "finished_at": NOW - timedelta(hours=random.uniform(1, 2)), "_demo": True})
    await db.builder_runs.insert_many(runs)


async def media(db):
    """Канбан редакции: посты по статусам + идеи от учеников."""
    await db.media_posts.delete_many({"_demo": True})
    await db.media_ideas.delete_many({"_demo": True})
    posts = [
        {"title": "Репортаж с олимпиады по физике", "body": "Команда школы взяла два призовых места.",
         "status": "published", "assignee_id": "6abd00000000000000000001",
         "publish_at": NOW - timedelta(days=1), "published_at": NOW - timedelta(days=1),
         "created_at": NOW - timedelta(days=4)},
        {"title": "Интервью с новым директором", "body": "Первые 100 дней: планы и впечатления.",
         "status": "review", "assignee_id": "6abd00000000000000000002",
         "created_at": NOW - timedelta(days=3)},
        {"title": "Как прошёл день самоуправления", "body": "Ученики вели уроки и дежурили по школе.",
         "status": "in_progress", "assignee_id": "6abd00000000000000000003",
         "created_at": NOW - timedelta(days=2)},
        {"title": "Анонс осеннего концерта", "body": "Черновик программы и список выступающих.",
         "status": "idea", "assignee_id": None, "created_at": NOW - timedelta(days=1)},
    ]
    for p in posts:
        p.update({"school_id": SCHOOL_ID, "_demo": True})
    await db.media_posts.insert_many(posts)
    ideas = [
        ("Кто-нибудь сходите взять комментарий у завуча про расписание", "new"),
        ("Сделать подборку мемов из школьных чатов", "new"),
        ("Снять видео про кружок робототехники", "accepted"),
        ("Опрос: куда ученики хотят поехать на осенние каникулы", "rejected"),
    ]
    await db.media_ideas.insert_many(
        [{"school_id": SCHOOL_ID, "author_id": f"6abd000000000000000000{i % 10 + 1:02d}",
          "text": t, "status": s, "created_at": NOW - timedelta(hours=i * 7), "_demo": True}
         for i, (t, s) in enumerate(ideas)])


async def main():
    client = AsyncIOMotorClient(settings.mongo_url, tz_aware=True)
    db = client.get_default_database()
    for step in (pulse, duty, builder, media):
        await step(db)
        print(f"ok: {step.__name__}")


if __name__ == "__main__":
    asyncio.run(main())
