import re

from ..core.config import settings
from ..modules.users.models import User
from ..modules.navigator.models import Building, Floor, Room
from .pulse_bot import _send

MAX_MATCHES = 5


async def handle_where(event, vk):
    query = event["match"].group(1).strip()
    if not query:
        return
    u = await User.find_one(User.vk_id == event["vk_user_id"])
    if not u or not u.school_id:
        await _send(vk, event["peer_id"],
                    "Сначала привяжи аккаунт командой «код <6 цифр>» с сайта.")
        return
    rx = re.compile(re.escape(query), re.IGNORECASE)
    rooms = await Room.find(
        {"school_id": u.school_id,
         "$or": [{"number": rx}, {"name": rx}]}).limit(MAX_MATCHES + 1).to_list()
    if not rooms:
        await _send(vk, event["peer_id"],
                    f"Кабинет «{query}» не нашла. Проверь номер на сайте.")
        return
    lines = []
    for room in rooms[:MAX_MATCHES]:
        floor = await Floor.get(room.floor_id)
        building = await Building.get(floor.building_id) if floor else None
        where = f"{building.name}, {floor.level} этаж" if building and floor else "место не указано"
        lines.append(f"{room.number} «{room.name}» - {where}")
    text = "\n".join(lines)
    if len(rooms) > MAX_MATCHES:
        text += f"\n…и ещё {len(rooms) - MAX_MATCHES}, уточни номер."
    if settings.frontend_url:
        text += f"\nПлан: {settings.frontend_url.rstrip('/')}/navigator"
    await _send(vk, event["peer_id"], text)
