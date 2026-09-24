from conftest import ensure_school
async def test_admin_creates_user_and_login(client, db):
    from app.modules.users.service import create_user
    _, tmp = await create_user(school_id=await ensure_school(), login="admin", full_name="Админ", role="admin")
    r = await client.post("/api/auth/login", json={"school_code": "s1", "login": "admin", "password": tmp})
    assert r.status_code == 200 and r.json()["must_change_password"] is True
    tok = r.json()
    h = {"Authorization": f"Bearer {tok['access']}"}
    r = await client.post("/api/auth/first-password", json={"new_password": "NewPass1"}, headers=h)
    assert r.status_code == 200
    r = await client.post("/api/auth/login", json={"school_code": "s1", "login": "admin", "password": "NewPass1"})
    assert r.json()["must_change_password"] is False
    r = await client.post("/api/users", json={"login": "u1", "full_name": "Ученик", "role": "student"}, headers=h)
    assert r.status_code == 200 and "temp_password" in r.json()

async def test_student_cannot_create_user(client, db):
    from app.modules.users.service import create_user
    _, tmp = await create_user(school_id=await ensure_school(), login="s1", full_name="У", role="student")
    r = await client.post("/api/auth/login", json={"school_code": "s1", "login": "s1", "password": tmp})
    h = {"Authorization": f"Bearer {r.json()['access']}"}
    r = await client.post("/api/users", json={"login": "u2", "full_name": "У", "role": "student"}, headers=h)
    assert r.status_code == 403

async def test_login_wrong_password(client, db):
    from app.modules.users.service import create_user
    _, tmp = await create_user(school_id=await ensure_school(), login="s2", full_name="У", role="student")
    r = await client.post("/api/auth/login", json={"school_code": "s1", "login": "s2", "password": "nope"})
    assert r.status_code == 401

async def test_refresh_invalid_tokens(client, db):
    from app.modules.users.service import create_user
    _, tmp = await create_user(school_id=await ensure_school(), login="s3", full_name="У", role="student")
    r = await client.post("/api/auth/login", json={"school_code": "s1", "login": "s3", "password": tmp})
    access = r.json()["access"]
    for bad in ("garbage", access):
        r = await client.post("/api/auth/refresh", json={"refresh": bad})
        assert r.status_code == 401

async def test_verify_password_bad_hash():
    from app.core.auth import verify_password
    assert verify_password("pw", "not-an-argon2-hash") is False

async def test_first_password_deleted_user_401(client, db):
    from app.core.auth import make_tokens
    tok = make_tokens(9999, "student", "s1")["access"]
    h = {"Authorization": f"Bearer {tok}"}
    r = await client.post("/api/auth/first-password", json={"new_password": "NewPass1"}, headers=h)
    assert r.status_code == 401

async def test_vk_unlink_deleted_user_401(client, db):
    from app.core.auth import make_tokens
    tok = make_tokens(9999, "student", "s1")["access"]
    h = {"Authorization": f"Bearer {tok}"}
    r = await client.delete("/api/me/vk", headers=h)
    assert r.status_code == 401

async def test_create_student_with_class(client, db):
    """Регресс: class_id в UserCreateIn был int - ученик с классом не создавался."""
    from app.modules.users.models import SchoolClass, User
    from app.modules.users.service import create_user
    cls = SchoolClass(school_id=await ensure_school(), grade=7, letter="Б")
    await cls.insert()
    _, tmp = await create_user(school_id=await ensure_school(), login="admin", full_name="Админ", role="admin")
    h = {"Authorization": f"Bearer {(await client.post('/api/auth/login', json={'school_code': 's1', 'login': 'admin', 'password': tmp})).json()['access']}"}
    r = await client.post("/api/users",
                          json={"login": "s9", "full_name": "Ученик", "role": "student",
                                "class_id": str(cls.id)},
                          headers=h)
    assert r.status_code == 200
    u = await User.find_one(User.login == "s9")
    assert u is not None and u.class_id == str(cls.id)
