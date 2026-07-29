from datetime import date, datetime
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from ..database import get_db
from ..schemas.anniversary import AnniversaryCreate, AnniversaryResponse
from ..crud.anniversary import anniversary as crud_anniversary
from ..auth import get_current_user
from ..models.user import User

router = APIRouter()


@router.get("", response_model=list[AnniversaryResponse])
def get_anniversaries(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    anniversaries = crud_anniversary.get_multi_by_user(db, user_id=current_user.id)
    today = date.today()

    result = []
    for a in anniversaries:
        anni_date = datetime.strptime(a.date, "%Y-%m-%d").date()
        # Calculate this year's anniversary
        this_year_anni = date(today.year, anni_date.month, anni_date.day)
        delta = (this_year_anni - today).days

        if delta < 0:
            # Already passed this year, calculate next year
            next_anni = date(today.year + 1, anni_date.month, anni_date.day)
            days_until = (next_anni - today).days
        else:
            days_until = delta

        # Days since original date
        days_since = (today - anni_date).days

        result.append(
            AnniversaryResponse(
                id=a.id,
                user_id=a.user_id,
                name=a.name,
                date=a.date,
                type=a.type,
                days_until=days_until,
                days_since=days_since,
            )
        )

    # Sort by days_until (closest first)
    result.sort(key=lambda x: x.days_until)
    return result


@router.post("", response_model=AnniversaryResponse, status_code=status.HTTP_201_CREATED)
def create_anniversary(
    anniversary_in: AnniversaryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    anni = crud_anniversary.create(
        db,
        obj_in=AnniversaryCreate(
            name=anniversary_in.name,
            date=anniversary_in.date,
            type=anniversary_in.type,
        ),
    )
    anni.user_id = current_user.id
    db.commit()
    db.refresh(anni)

    anni_date = datetime.strptime(anni.date, "%Y-%m-%d").date()
    today = date.today()
    this_year_anni = date(today.year, anni_date.month, anni_date.day)
    delta = (this_year_anni - today).days
    if delta < 0:
        days_until = (date(today.year + 1, anni_date.month, anni_date.day) - today).days
    else:
        days_until = delta

    return AnniversaryResponse(
        id=anni.id,
        user_id=anni.user_id,
        name=anni.name,
        date=anni.date,
        type=anni.type,
        days_until=days_until,
        days_since=(today - anni_date).days,
    )
