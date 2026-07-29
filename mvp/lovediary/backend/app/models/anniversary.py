from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from ..database import Base


class Anniversary(Base):
    __tablename__ = "anniversaries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    date = Column(String(10), nullable=False)  # YYYY-MM-DD
    type = Column(String(20), default="custom")  # love_start, first_date, proposal, wedding, custom
    created_at = Column(DateTime(timezone=True), server_default=func.now())
