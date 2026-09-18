from pydantic import BaseModel, field_validator

from .models import Quest, QuestRun
from .quest_structure import QuestStructure, validate_structure


class QuestIn(BaseModel):
    title: str
    class_id: str
    structure: QuestStructure

    @field_validator("structure")
    @classmethod
    def valid_structure(cls, s: QuestStructure) -> QuestStructure:
        errors = validate_structure(s)
        if errors:
            raise ValueError("; ".join(errors))
        return s


def quest_out(q: Quest) -> dict:
    return {"id": str(q.id), "teacher_id": q.teacher_id, "class_id": q.class_id,
            "title": q.title, "structure": q.structure, "status": q.status,
            "created_at": q.created_at}


def run_out(r: QuestRun) -> dict:
    return {"id": str(r.id), "quest_id": r.quest_id, "user_id": r.user_id,
            "finished": r.finished, "score": r.score, "trace": r.trace,
            "started_at": r.started_at, "finished_at": r.finished_at}
