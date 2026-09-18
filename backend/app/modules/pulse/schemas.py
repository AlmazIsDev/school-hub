from pydantic import BaseModel, Field


class QuestionIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    type: str  # валидируется в router (scale1_5|free_text)


class PollCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    topic: str = Field(min_length=1, max_length=100)
    class_id: str
    questions: list[QuestionIn] = Field(min_length=1, max_length=5)
