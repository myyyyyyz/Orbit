from pydantic import BaseModel
from typing import Optional, List


class MomentCreate(BaseModel):
    title: str
    content: Optional[str] = None
    date: str
    tags: List[str] = []
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_name: Optional[str] = None


class MomentUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[List[str]] = None


class MomentResponse(BaseModel):
    id: int
    user_id: int
    title: str
    content: Optional[str] = None
    date: str
    tags: List[str] = []
    image_url: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_name: Optional[str] = None
    created_at: str

    class Config:
        from_attributes = True
