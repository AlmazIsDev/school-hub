from pydantic import BaseModel

class LoginIn(BaseModel):
    login: str
    password: str

class TokensOut(BaseModel):
    access: str
    refresh: str
    must_change_password: bool

class RefreshIn(BaseModel):
    refresh: str

class FirstPasswordIn(BaseModel):
    new_password: str

class UserCreateIn(BaseModel):
    login: str
    full_name: str
    role: str  # валидируется в service (Literal["student","teacher","admin"] надёжнее)
    class_id: int | None = None

class ClassIn(BaseModel):
    grade: int
    letter: str
