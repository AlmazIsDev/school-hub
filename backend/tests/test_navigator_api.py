import pytest_asyncio
from mongomock_motor import AsyncMongoMockClient
from beanie import init_beanie
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.modules.users.models import SchoolClass, User
from app.modules.pulse.models import Poll, PollAnswer
from app.modules.bridge.models import (Ban, HelpRequest, HelperTopic, PairMessage,
                                       Report, StopWord, TutorPair)
from app.modules.duty.models import DutyCompletion, DutySchedule, DutyZone
from app.modules.navigator.models import Building, Floor, Room

ALL_MODELS = [User, SchoolClass, Poll, PollAnswer,
              HelperTopic, HelpRequest, TutorPair, PairMessage, Report, Ban, StopWord,
              DutyZone, DutySchedule, DutyCompletion,
              Building, Floor, Room]


@pytest_asyncio.fixture
async def db():
    client = AsyncMongoMockClient()
    await init_beanie(client.get_database("test"), document_models=ALL_MODELS)
    yield


@pytest_asyncio.fixture
async def client(db):
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _mk_user(login: str, role: str) -> str:
    from app.modules.users.service import create_user
    from app.core.auth import make_tokens
    u, _ = await create_user(login=login, full_name="У", role=role)
    return make_tokens(u.id, u.role)["access"]


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def tokens(db):
    return {"teacher": await _mk_user("t1", "teacher"),
            "admin": await _mk_user("a1", "admin"),
            "student": await _mk_user("s1", "student")}


POLY = {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [0, 0]]]}


@pytest_asyncio.fixture
async def building(client, tokens):
    r = await client.post("/api/nav/buildings", json={"name": "Основное", "address": "Ленина 1"},
                          headers=_h(tokens["admin"]))
    assert r.status_code == 200
    return r.json()["id"]


@pytest_asyncio.fixture
async def floor(client, tokens, building):
    r = await client.post("/api/nav/floors", json={"building_id": building, "level": 2},
                          headers=_h(tokens["admin"]))
    assert r.status_code == 200
    return r.json()["id"]


# ---------- buildings ----------

async def test_buildings_rights(client, tokens):
    r = await client.post("/api/nav/buildings", json={"name": "X", "address": "Y"},
                          headers=_h(tokens["student"]))
    assert r.status_code == 403
    r = await client.post("/api/nav/buildings", json={"name": "X", "address": "Y"},
                          headers=_h(tokens["teacher"]))
    assert r.status_code == 403
    r = await client.get("/api/nav/buildings", headers=_h(tokens["student"]))
    assert r.status_code == 200


async def test_delete_building_cascades(client, tokens, building, floor):
    r = await client.post("/api/nav/rooms", json={"floor_id": floor, "number": "215",
                                                  "name": "Кабинет", "geometry": POLY},
                          headers=_h(tokens["admin"]))
    assert r.status_code == 200
    r = await client.delete(f"/api/nav/buildings/{building}", headers=_h(tokens["admin"]))
    assert r.status_code == 200
    assert (await client.get("/api/nav/buildings", headers=_h(tokens["admin"]))).json() == []
    r = await client.get(f"/api/nav/floors?building_id={building}", headers=_h(tokens["admin"]))
    assert r.status_code == 404


# ---------- floors ----------

async def test_floor_delete_with_rooms_409(client, tokens, building, floor):
    r = await client.post("/api/nav/rooms", json={"floor_id": floor, "number": "1",
                                                  "name": "N", "geometry": POLY},
                          headers=_h(tokens["admin"]))
    assert r.status_code == 200
    room_id = r.json()["id"]
    r = await client.delete(f"/api/nav/floors/{floor}", headers=_h(tokens["admin"]))
    assert r.status_code == 409
    r = await client.delete(f"/api/nav/rooms/{room_id}", headers=_h(tokens["admin"]))
    assert r.status_code == 200
    r = await client.delete(f"/api/nav/floors/{floor}", headers=_h(tokens["admin"]))
    assert r.status_code == 200


async def test_floor_requires_existing_building(client, tokens):
    r = await client.post("/api/nav/floors", json={"building_id": "0" * 24, "level": 1},
                          headers=_h(tokens["admin"]))
    assert r.status_code == 404
    r = await client.post("/api/nav/floors", json={"building_id": "0" * 24, "level": 1},
                          headers=_h(tokens["student"]))
    assert r.status_code == 403


# ---------- rooms / geometry ----------

async def test_geometry_validation(client, tokens, floor):
    hdr = _h(tokens["admin"])
    bad = [
        {"type": "Point", "coordinates": [[[0, 0]]]},                # не Polygon
        {"type": "Polygon", "coordinates": [[[0, 0], [0, 1]]]},      # 2 точки
        {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, "a"]]]},  # не число
        {"type": "Polygon", "coordinates": [[[0], [0, 1], [1, 1]]]},  # точка не [x, y]
        {"type": "Polygon", "coordinates": []},
    ]
    for g in bad:
        r = await client.post("/api/nav/rooms", json={"floor_id": floor, "number": "1",
                                                      "name": "N", "geometry": g}, headers=hdr)
        assert r.status_code == 422, g
    r = await client.post("/api/nav/rooms", json={"floor_id": floor, "number": "1",
                                                  "name": "N", "geometry": POLY}, headers=hdr)
    assert r.status_code == 200


async def test_room_update(client, tokens, floor, building):
    hdr = _h(tokens["admin"])
    r = await client.post("/api/nav/rooms", json={"floor_id": floor, "number": "215",
                                                  "name": "Информатика", "geometry": POLY},
                          headers=hdr)
    room_id = r.json()["id"]
    r = await client.put(f"/api/nav/rooms/{room_id}",
                         json={"floor_id": floor, "number": "216", "name": "Физика",
                               "geometry": POLY}, headers=hdr)
    assert r.status_code == 200
    assert r.json()["number"] == "216"
    # несуществующий этаж при переносе
    r = await client.put(f"/api/nav/rooms/{room_id}",
                         json={"floor_id": "0" * 24, "number": "216", "name": "Ф",
                               "geometry": POLY}, headers=hdr)
    assert r.status_code == 404
    r = await client.put(f"/api/nav/rooms/{room_id}", json={"floor_id": floor, "number": "216",
                                                            "name": "Ф", "geometry": POLY},
                         headers=_h(tokens["student"]))
    assert r.status_code == 403


# ---------- search ----------

async def test_search(client, tokens, floor, building):
    hdr = _h(tokens["admin"])
    for number in ["215", "215a", "216", "315"]:
        r = await client.post("/api/nav/rooms", json={"floor_id": floor, "number": number,
                                                      "name": f"Кабинет {number}",
                                                      "geometry": POLY}, headers=hdr)
        assert r.status_code == 200

    async def do(q):
        return await client.get(f"/api/nav/search?q={q}", headers=_h(tokens["student"]))

    r = await do("215")
    assert r.status_code == 200
    data = r.json()
    assert {x["number"] for x in data} == {"215", "215a"}
    assert data[0]["floor_id"] == floor
    assert data[0]["building_id"] == building

    # регистр неважен
    r = await do("215A")
    assert {x["number"] for x in r.json()} == {"215a"}

    r = await do("нет")
    assert r.json() == []


async def test_search_limit_and_empty(client, tokens, floor):
    hdr = _h(tokens["admin"])
    for i in range(25):
        r = await client.post("/api/nav/rooms", json={"floor_id": floor, "number": f"2{i:02d}",
                                                      "name": "N", "geometry": POLY}, headers=hdr)
        assert r.status_code == 200
    r = await client.get("/api/nav/search?q=2", headers=_h(tokens["student"]))
    assert len(r.json()) == 20
    r = await client.get("/api/nav/search?q=", headers=_h(tokens["student"]))
    assert r.status_code == 422


async def test_room_requires_admin(client, db):
    st = _h(await _mk_user("s2", "student"))
    for method, url in (("post", "/api/nav/rooms"), ("put", "/api/nav/rooms/x"),
                        ("delete", "/api/nav/rooms/x")):
        r = await getattr(client, method)(url, headers=st)
        assert r.status_code == 403, f"{method} {url} -> {r.status_code}"


async def test_duplicate_floor_level_409(client, db):
    ad = _h(await _mk_user("a2", "admin"))
    b = (await client.post("/api/nav/buildings", json={"name": "Ш", "address": "У"},
                           headers=ad)).json()["id"]
    body = {"building_id": b, "level": 1}
    assert (await client.post("/api/nav/floors", json=body, headers=ad)).status_code == 200
    r = await client.post("/api/nav/floors", json=body, headers=ad)
    assert r.status_code == 409
