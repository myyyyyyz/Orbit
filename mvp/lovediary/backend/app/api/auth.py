from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from ..database import get_db
from ..schemas.user import UserCreate, UserLogin, UserResponse
from ..schemas.common import TokenResponse
from ..crud.user import user as crud_user
from ..models.user import User
from ..auth import verify_password, get_password_hash, create_access_token

router = APIRouter()


@router.post("/register", response_model=TokenResponse)
def register(user_in: UserCreate, db: Session = Depends(get_db)):
    existing = crud_user.get_by_username(db, username=user_in.username)
    if existing:
        raise HTTPException(status_code=400, detail="用户名已存在")

    user = User(
        username=user_in.username,
        password_hash=get_password_hash(user_in.password),
        couple_code=user_in.couple_code,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(data={"sub": user.username, "user_id": user.id})
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
def login(user_in: UserLogin, db: Session = Depends(get_db)):
    user = crud_user.get_by_username(db, username=user_in.username)
    if not user or not verify_password(user_in.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = create_access_token(data={"sub": user.username, "user_id": user.id})
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
def get_me(db: Session = Depends(get_db)):
    # This is just a placeholder — actual auth is done in moments/api.py
    pass
