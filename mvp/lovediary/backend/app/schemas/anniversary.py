from pydantic import BaseModel
from datetime import date, datetime


class AnniversaryCreate(BaseModel):
    name: str
    date: str  # YYYY-MM-DD
    type: str = "custom"


class AnniversaryResponse(BaseModel):
    id: int
    user_id: int
    name: str
    date: str
    type: str
    days_until: int = 0
    days_since: int = 0

    class Config:
        from_attributes = True
