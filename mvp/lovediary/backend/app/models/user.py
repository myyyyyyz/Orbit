from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func
from ..database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    couple_code = Column(String(20), index=True, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
