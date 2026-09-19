"""Механика прохождения квеста — общая для бота и веб-плеера."""
from bson import ObjectId
from fastapi import HTTPException

from ..users.models import User
from .models import Quest


def blocks_map(quest: Quest) -> dict:
    return {b["id"]: b for b in quest.structure["blocks"]}


def resolve_next(blocks: dict, block_id: str, last_value: str | None) -> str:
    """Переход из блока; branch-блоки резолвим сразу
    (branch на branch допустим, циклы валидатор запрещает, так что loop конечен)."""
    bid = block_id
    while True:
        b = blocks[bid]
        if b["type"] == "end":
            return bid
        if b["type"] == "branch":
            bid = b["then"] if last_value == b["condition"]["answer"] else b["else"]
            continue
        return bid


def sanitized_blocks(quest: Quest) -> list[dict]:
    """Ученик не должен видеть score/condition."""
    return [{k: v for k, v in b.items() if k not in ("score", "condition")}
            for b in quest.structure["blocks"]]


async def check_class_access(quest: Quest, user: dict) -> None:
    """Ученик играет только в квест своего класса; учителю/админу можно всё."""
    if user["role"] != "student":
        return
    me = await User.get(ObjectId(user["id"]))
    if not me or quest.class_id != me.class_id:
        raise HTTPException(403, "Квест другого класса")


def expected_block_id(quest: Quest, trace: list[dict]) -> str | None:
    """Блок, на котором прохождение должно стоять по trace. None — trace битый."""
    blocks = blocks_map(quest)
    bid = resolve_next(blocks, quest.structure["blocks"][0]["id"], None)
    for step in trace:
        if bid != step.get("block_id"):
            return None
        b = blocks[bid]
        if b["type"] == "end":
            return bid
        if "next" not in b:
            return None
        bid = resolve_next(blocks, b["next"], step.get("value"))
    return bid
