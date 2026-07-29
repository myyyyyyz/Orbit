from sqlalchemy import Column, Integer, String, Float, Text, DateTime, ForeignKey, JSON
from sqlalchemy.sql import func
from ..database import Base


class Moment(Base):
    __tablename__ = "moments"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(100), nullable=False)
    content = Column(Text, nullable=True)
    date = Column(String(10), nullable=False)  # YYYY-MM-DD
    tags = Column(JSON, default=[])
    image_url = Column(String(500), nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    location_name = Column(String(200), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
