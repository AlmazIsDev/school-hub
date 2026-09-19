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


# ---------- bind: дубликат vk и «мой аккаунт» ----------

class FakeVK:
    def __init__(self):
        self.messages = []

    async def call(self, method, **params):
        self.messages.append(params.get("message", ""))


def _register():
    from app.bot.dispatcher import Dispatcher
    from app.bot import handlers
    dp = Dispatcher()
    handlers.register(dp)
    return dp


async def _dispatch(dp, text, vk, vk_user_id=421454852):
    await dp.dispatch({"text": text, "vk_user_id": vk_user_id, "peer_id": vk_user_id, "vk": vk})


async def test_bind_duplicate_vk_friendly_error(client, db, monkeypatch):
    from app.modules.users.models import User
    import fakeredis.aioredis as fr
    import app.core.redis as core_redis
    import app.bot.codes as codes
    from app.modules.users.service import create_user

    fakes = fr.FakeRedis()
    core_redis.get_redis = lambda: fakes
    monkeypatch.setattr(codes, "r", fakes)
    a, _ = await create_user(login="a1", full_name="Аня", role="student")
    a.vk_id = 421454852
    await a.save()
    b, _ = await create_user(login="b1", full_name="Боря", role="student")
    await fakes.set("vkcode:123456", str(b.id), ex=900)

    vk = FakeVK()
    await _dispatch(_register(), "код 123456", vk)
    assert any("уже привязан" in m for m in vk.messages)
    assert (await User.get(b.id)).vk_id is None  # Борю не задело


async def test_my_account_command(client, db):
    from app.modules.users.service import create_user
    u, _ = await create_user(login="vika", full_name="Вика", role="student")
    u.vk_id = 555
    await u.save()
    vk = FakeVK()
    await _dispatch(_register(), "мой аккаунт", vk, vk_user_id=555)
    assert any("vika" in m and "Вика" in m for m in vk.messages)
    # не привязанный пользователь получает подсказку
    vk2 = FakeVK()
    await _dispatch(_register(), "мой аккаунт", vk2, vk_user_id=999)
    assert any("не привязан" in m for m in vk2.messages)
