async def test_admin_creates_user_and_login(client, db):
    from app.modules.users.service import create_user
    async with db() as s:
        admin, tmp = create_user(s, login="admin", full_name="Админ", role="admin")
        await s.commit()
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
    async with db() as s:
        _, tmp = create_user(s, login="s1", full_name="У", role="student")
        await s.commit()
    r = await client.post("/api/auth/login", json={"login": "s1", "password": tmp})
    h = {"Authorization": f"Bearer {r.json()['access']}"}
    r = await client.post("/api/users", json={"login": "u2", "full_name": "У", "role": "student"}, headers=h)
    assert r.status_code == 403

async def test_login_wrong_password(client, db):
    from app.modules.users.service import create_user
    async with db() as s:
        _, tmp = create_user(s, login="s2", full_name="У", role="student")
        await s.commit()
    r = await client.post("/api/auth/login", json={"login": "s2", "password": "nope"})
    assert r.status_code == 401
