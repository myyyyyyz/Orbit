from sqlalchemy.orm import Session
from ..models.anniversary import Anniversary
from .base import CRUDBase
from ..schemas.anniversary import AnniversaryCreate


class CRUDAnniversary(CRUDBase[Anniversary, AnniversaryCreate, dict]):
    def get_multi_by_user(self, db: Session, *, user_id: int) -> list[Anniversary]:
        return (
            db.query(Anniversary)
            .filter(Anniversary.user_id == user_id)
            .order_by(Anniversary.date.asc())
            .all()
        )


anniversary = CRUDAnniversary(Anniversary)
