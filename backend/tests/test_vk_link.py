import fakeredis.aioredis as fr
import app.core.redis as core_redis

async def test_me_vk_code(client, db, monkeypatch):
    core_redis.get_redis = lambda: fr.FakeRedis()
    from app.modules.users.service import create_user
    _, tmp = await create_user(login="m1", full_name="У", role="student")
    tok = (await client.post("/api/auth/login", json={"login": "m1", "password": tmp})).json()
    h = {"Authorization": f"Bearer {tok['access']}"}
    r = await client.post("/api/me/vk-code", headers=h)
    assert r.status_code == 200 and len(r.json()["code"]) == 6
    assert (await client.delete("/api/me/vk", headers=h)).status_code == 200
