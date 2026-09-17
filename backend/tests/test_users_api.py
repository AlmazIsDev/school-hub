async def test_admin_creates_user_and_login(client, db):
    from app.modules.users.service import create_user
    _, tmp = await create_user(login="admin", full_name="Админ", role="admin")
    r = await client.post("/api/auth/login", json={"login": "admin", "password": tmp})
    assert r.status_code == 200 and r.json()["must_change_password"] is True
    tok = r.json()
    h = {"Authorization": f"Bearer {tok['access']}"}
    r = await client.post("/api/auth/first-password", json={"new_password": "NewPass1"}, headers=h)
    assert r.status_code == 200
    r = await client.post("/api/auth/login", json={"login": "admin", "password": "NewPass1"})
    assert r.json()["must_change_password"] is False
    r = await client.post("/api/users", json={"login": "u1", "full_name": "Ученик", "role": "student"}, headers=h)
    assert r.status_code == 200 and "temp_password" in r.json()

async def test_student_cannot_create_user(client, db):
    from app.modules.users.service import create_user
    _, tmp = await create_user(login="s1", full_name="У", role="student")
    r = await client.post("/api/auth/login", json={"login": "s1", "password": tmp})
    h = {"Authorization": f"Bearer {r.json()['access']}"}
    r = await client.post("/api/users", json={"login": "u2", "full_name": "У", "role": "student"}, headers=h)
    assert r.status_code == 403

async def test_login_wrong_password(client, db):
    from app.modules.users.service import create_user
    _, tmp = await create_user(login="s2", full_name="У", role="student")
    r = await client.post("/api/auth/login", json={"login": "s2", "password": "nope"})
    assert r.status_code == 401

async def test_refresh_invalid_tokens(client, db):
    from app.modules.users.service import create_user
    _, tmp = await create_user(login="s3", full_name="У", role="student")
    r = await client.post("/api/auth/login", json={"login": "s3", "password": tmp})
    access = r.json()["access"]
    for bad in ("garbage", access):
        r = await client.post("/api/auth/refresh", json={"refresh": bad})
        assert r.status_code == 401

async def test_verify_password_bad_hash():
    from app.core.auth import verify_password
    assert verify_password("pw", "not-an-argon2-hash") is False

async def test_first_password_deleted_user_401(client, db):
    from app.core.auth import make_tokens
    tok = make_tokens(9999, "student")["access"]
    h = {"Authorization": f"Bearer {tok}"}
    r = await client.post("/api/auth/first-password", json={"new_password": "NewPass1"}, headers=h)
    assert r.status_code == 401

async def test_vk_unlink_deleted_user_401(client, db):
    from app.core.auth import make_tokens
    tok = make_tokens(9999, "student")["access"]
    h = {"Authorization": f"Bearer {tok}"}
    r = await client.delete("/api/me/vk", headers=h)
    assert r.status_code == 401
