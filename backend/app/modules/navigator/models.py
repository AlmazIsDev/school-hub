from datetime import datetime, timezone

from beanie import Document
from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


class GeoPolygon(BaseModel):
    """GeoJSON-полигон из Leaflet Draw. Кольца не проверяем на замкнутость (T4 сам дорисует)."""
    type: str  # только "Polygon", проверяется валидатором в schemas
    coordinates: list[list[list[float]]]


class Building(Document):
    name: str
    address: str
    created_at: datetime = Field(default_factory=_now)

    class Settings:
        name = "nav_buildings"


class Floor(Document):
    building_id: str
    level: int
    plan_id: str | None = None  # появится в T2

    class Settings:
        name = "nav_floors"


class Room(Document):
    floor_id: str
    number: str
    name: str
    geometry: GeoPolygon

    class Settings:
        name = "nav_rooms"
