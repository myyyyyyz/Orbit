from pydantic import BaseModel
from typing import Optional


class UserCreate(BaseModel):
    username: str
    password: str
    couple_code: Optional[str] = None


class UserLogin(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    couple_code: Optional[str] = None

    class Config:
        from_attributes = True
