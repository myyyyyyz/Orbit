from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from ..database import get_db
from ..schemas.moment import MomentCreate, MomentUpdate, MomentResponse
from ..crud.moment import moment as crud_moment
from ..auth import get_current_user
from ..models.user import User

router = APIRouter()


@router.get("", response_model=list[MomentResponse])
def get_moments(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    moments = crud_moment.get_multi_by_user(
        db, user_id=current_user.id, skip=skip, limit=limit
    )
    return [
        MomentResponse(
            id=m.id,
            user_id=m.user_id,
            title=m.title,
            content=m.content,
            date=m.date,
            tags=m.tags or [],
            image_url=m.image_url,
            latitude=m.latitude,
            longitude=m.longitude,
            location_name=m.location_name,
            created_at=str(m.created_at),
        )
        for m in moments
    ]


@router.post("", response_model=MomentResponse, status_code=status.HTTP_201_CREATED)
def create_moment(
    moment_in: MomentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    moment = crud_moment.create(
        db,
        obj_in=MomentCreate(
            title=moment_in.title,
            content=moment_in.content,
            date=moment_in.date,
            tags=moment_in.tags,
            latitude=moment_in.latitude,
            longitude=moment_in.longitude,
            location_name=moment_in.location_name,
        ),
    )
    # Manually set user_id since it's not in the create schema
    moment.user_id = current_user.id
    db.commit()
    db.refresh(moment)

    return MomentResponse(
        id=moment.id,
        user_id=moment.user_id,
        title=moment.title,
        content=moment.content,
        date=moment.date,
        tags=moment.tags or [],
        image_url=moment.image_url,
        latitude=moment.latitude,
        longitude=moment.longitude,
        location_name=moment.location_name,
        created_at=str(moment.created_at),
    )


@router.delete("/{moment_id}", response_model=dict)
def delete_moment(
    moment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    moment = crud_moment.get(db, id=moment_id)
    if not moment:
        raise HTTPException(status_code=404, detail="瞬间不存在")
    if moment.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权操作")

    crud_moment.remove(db, id=moment_id)
    return {"message": "删除成功"}
