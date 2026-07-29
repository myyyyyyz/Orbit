from typing import Optional
from sqlalchemy.orm import Session
from ..models.user import User
from .base import CRUDBase
from ..schemas.user import UserCreate


class CRUDUser(CRUDBase[User, UserCreate, dict]):
    def get_by_username(self, db: Session, *, username: str) -> Optional[User]:
        return db.query(User).filter(User.username == username).first()

    def get_by_couple_code(self, db: Session, *, couple_code: str) -> list[User]:
        return db.query(User).filter(User.couple_code == couple_code).all()


user = CRUDUser(User)
