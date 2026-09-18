"""Pydantic-схема структуры квеста и валидатор графа.

Структура — список блоков с переходами next/then/else. Валидатор возвращает
список ошибок (пустой список = структура валидна), чтобы отдавать их клиенту
целиком, а не по одной.
"""
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


class BranchCondition(BaseModel):
    answer: str


class QuestionBlock(BaseModel):
    id: str
    type: Literal["question"]
    text: str
    options: list[str] = Field(min_length=2, max_length=6)
    next: str


class BranchBlock(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    type: Literal["branch"]
    condition: BranchCondition
    then: str
    else_: str = Field(alias="else")


class HintBlock(BaseModel):
    id: str
    type: Literal["hint"]
    text: str
    next: str


class EndBlock(BaseModel):
    id: str
    type: Literal["end"]
    score: int


Block = Annotated[Union[QuestionBlock, BranchBlock, HintBlock, EndBlock],
                  Field(discriminator="type")]


class QuestStructure(BaseModel):
    blocks: list[Block] = Field(min_length=1)


def _edges(block) -> list[str]:
    if block.type == "branch":
        return [block.then, block.else_]
    if block.type == "end":
        return []
    return [block.next]


def validate_structure(structure: QuestStructure) -> list[str]:
    errors: list[str] = []
    blocks = structure.blocks
    ids = [b.id for b in blocks]

    for i, bid in enumerate(ids):
        if not bid.strip():
            errors.append(f"блок #{i + 1}: пустой id")
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        errors.append(f"дубли id: {', '.join(sorted(dupes))}")
    if errors:
        return errors  # дальше по id не пройдём

    by_id = {b.id: b for b in blocks}

    for b in blocks:
        for target in _edges(b):
            if target not in by_id:
                errors.append(f"блок {b.id}: переход на несуществующий {target}")
    if errors:
        return errors

    for b in blocks:
        if b.type == "branch" and b.then == b.else_:
            errors.append(f"блок {b.id}: then и else совпадают ({b.then})")

    start = blocks[0].id

    # достижимость из start (DFS), заодно циклодетект — DAG
    reachable: set[str] = set()
    on_path: set[str] = set()

    # ponytail: рекурсия — глубина графа; итеративный стек, если квесты станут огромными
    def visit(bid: str) -> None:
        if bid in on_path:
            errors.append(f"цикл через блок {bid}")
            return
        if bid in reachable:
            return
        reachable.add(bid)
        on_path.add(bid)
        for target in _edges(by_id[bid]):
            visit(target)
        on_path.discard(bid)

    visit(start)
    if errors:
        return errors

    unreachable = [i for i in ids if i not in reachable]
    if unreachable:
        errors.append(f"недостижимые блоки: {', '.join(unreachable)}")

    ends = [i for i in reachable if by_id[i].type == "end"]
    if not ends:
        errors.append("должен быть хотя бы один достижимый end")
    return errors
