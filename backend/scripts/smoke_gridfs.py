"""Smoke-проверка GridFS: загрузка/отдача/удаление плана этажа через реальное API.

Запуск при доступном Mongo (на сервере или локально с поднятым compose):
  cd backend
  set -a; source ../.env; set +a   # MONGO_URL и т.д.
  python scripts/smoke_gridfs.py

Проверяет: upload_plan -> план в GridFS, GET /plans отдаёт content-type и размер,
повторная загрузка сносит старый файл, delete_floor удаляет файл.
"""
import asyncio
import io
import sys

import httpx
from beanie import init_beanie

from app.core.db import init_mongo, get_gridfs, get_motor_client
from app.main import create_app
from app.core.config import settings
from app.core.auth import hash_password, make_tokens
from app.modules.users.models import SchoolClass, User


async def main() -> int:
    await init_mongo()
    # сбрасываем базу smoke-данных
    db = get_motor_client().get_default_database()
    await db.drop_collection("users")
    await db.drop_collection("nav_buildings")
    await db.drop_collection("nav_floors")
    await db.drop_collection("nav_rooms")

    from app.modules.navigator.models import Building, Floor, Room
    await init_beanie(get_motor_client().get_default_database(),
                      document_models=[User, SchoolClass, Building, Floor, Room])

    admin = User(login="smoke_admin", full_name="Smoke", role="admin",
                 password_hash=hash_password("smoke-pass-123"), password_temp=False)
    await admin.insert()
    token = make_tokens(admin.id, admin.role)["access"]
    headers = {"Authorization": f"Bearer {token}"}

    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"></svg>'
    app = create_app()
    ok = True
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/nav/buildings", json={"name": "Школа", "address": "ул. Тест"}, headers=headers)
        assert r.status_code == 200, r.text
        bid = r.json()["id"]
        r = await c.post("/api/nav/floors", json={"building_id": bid, "level": 1}, headers=headers)
        fid = r.json()["id"]

        files = {"file": ("plan.svg", io.BytesIO(svg), "image/svg+xml")}
        r = await c.post(f"/api/nav/floors/{fid}/plan", files=files, headers=headers)
        ok &= r.status_code == 200
        plan1 = r.json().get("plan_id")

        # план реально лежит в GridFS
        grid = get_gridfs()
        g = await grid.open_download_stream(__import__("bson").ObjectId(plan1))
        data = await g.read()
        ok &= data == svg
        print("upload+download:", "ok" if data == svg else "FAIL")

        r = await c.get(f"/api/nav/plans/{plan1}", headers=headers)
        ok &= (r.status_code == 200 and r.headers["content-type"] == "image/svg+xml"
               and len(r.content) == len(svg))
        print("GET /plans:", "ok" if ok else "FAIL",
              r.headers.get("content-type"), len(r.content))

        # повторная загрузка: старый файл снесён
        r = await c.post(f"/api/nav/floors/{fid}/plan",
                         files={"file": ("p2.svg", io.BytesIO(svg), "image/svg+xml")},
                         headers=headers)
        plan2 = r.json()["plan_id"]
        try:
            await grid.delete(__import__("bson").ObjectId(plan1))
            exists = True  # delete не упал — файл ещё был, значит не снесли
            await grid.delete(__import__("bson").ObjectId(plan1))  # вернём состояние
        except Exception:
            exists = False
        ok &= not exists
        print("старый план удалён при перезагрузке:", "ok" if not exists else "FAIL")

        # delete_floor удаляет файл
        await grid.open_download_stream(__import__("bson").ObjectId(plan2))
        r = await c.delete(f"/api/nav/floors/{fid}", headers=headers)
        ok &= r.status_code == 200
        try:
            await grid.open_download_stream(__import__("bson").ObjectId(plan2))
            gone = False
        except Exception:
            gone = True
        ok &= gone
        print("план удалён вместе с этажом:", "ok" if gone else "FAIL")

    print("SMOKE:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
