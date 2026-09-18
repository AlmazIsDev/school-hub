from pydantic import BaseModel, field_validator

from .models import GeoPolygon


class BuildingIn(BaseModel):
    name: str
    address: str

    @field_validator("name", "address")
    @classmethod
    def not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("не может быть пустым")
        return v


class FloorIn(BaseModel):
    building_id: str
    level: int


class RoomIn(BaseModel):
    floor_id: str
    number: str
    name: str
    geometry: GeoPolygon

    @field_validator("number")
    @classmethod
    def number_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("number не может быть пустым")
        return v

    @field_validator("geometry")
    @classmethod
    def valid_polygon(cls, g: GeoPolygon) -> GeoPolygon:
        if g.type != "Polygon":
            raise ValueError("geometry.type должен быть Polygon")
        if not g.coordinates:
            raise ValueError("geometry.coordinates пуст")
        ring = g.coordinates[0]
        if len(ring) < 3:
            raise ValueError("в первом кольце минимум 3 точки")
        for p in ring:
            if len(p) != 2:
                raise ValueError("точка должна быть [x, y]")
        return g
