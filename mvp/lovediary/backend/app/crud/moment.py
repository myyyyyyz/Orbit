from sqlalchemy.orm import Session
from ..models.moment import Moment
from .base import CRUDBase
from ..schemas.moment import MomentCreate


class CRUDMoment(CRUDBase[Moment, MomentCreate, dict]):
    def get_multi_by_user(self, db: Session, *, user_id: int, skip: int = 0, limit: int = 50) -> list[Moment]:
        return (
            db.query(Moment)
            .filter(Moment.user_id == user_id)
            .order_by(Moment.date.desc(), Moment.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )


moment = CRUDMoment(Moment)
