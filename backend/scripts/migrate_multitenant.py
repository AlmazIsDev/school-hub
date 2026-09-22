"""Одноразовая миграция на мультиарендность: создаёт School и проставляет
school_id во всех арендных коллекциях. Идемпотентна: можно перезапускать.

Перед запуском: mongodump (обратимость). Запуск:
    python -m scripts.migrate_multitenant
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017/schoolhub")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "migrate-only-not-a-secret")

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from app.core.config import settings  # noqa: E402

# коллекции, не содержащие school_id
SKIP = {"schools", "fs.chunks", "fs.files", "system.version"}

DEFAULT_CODE = os.environ.get("MIGRATE_SCHOOL_CODE", "school1")


async def main():
    client = AsyncIOMotorClient(settings.mongo_url, tz_aware=True)
    db = client.get_default_database()

    school = await db.schools.find_one({"code": DEFAULT_CODE})
    if not school:
        from datetime import datetime, timezone
        res = await db.schools.insert_one({
            "name": "Школа", "code": DEFAULT_CODE,
            "created_at": datetime.now(timezone.utc)})
        school_id = str(res.inserted_id)
        print(f"создана школа code={DEFAULT_CODE} id={school_id}")
    else:
        school_id = str(school["_id"])
        print(f"школа уже существует id={school_id}")

    # все пользователи и админы относятся к перенесённой школе
    await db.users.update_many(
        {"school_id": {"$exists": False}},
        {"$set": {"school_id": school_id}})
    # админ из .env становится платформенным superadmin без школы
    if settings.admin_login:
        await db.users.update_many(
            {"login": settings.admin_login},
            {"$set": {"role": "superadmin"}, "$unset": {"school_id": ""}})

    collections = await db.list_collection_names()
    for name in collections:
        if name in SKIP or name.startswith("system"):
            continue
        res = await db[name].update_many(
            {"school_id": {"$exists": False}},
            {"$set": {"school_id": school_id}})
        if res.modified_count:
            print(f"{name}: проставлен school_id у {res.modified_count}")

    print("готово. Проверь: db.users.count_documents({school_id: {$exists: false}}) == 0")


if __name__ == "__main__":
    asyncio.run(main())
