import hashlib
import secrets
from datetime import datetime, timedelta
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from .config import settings
from .database import get_db
from .crud.user import user as crud_user

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_password_hash(password: str) -> str:
    salt = secrets.token_hex(16)
    return salt + ":" + hashlib.sha256((password + salt).encode()).hexdigest()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    salt, hash_value = hashed_password.split(":", 1)
    return hashlib.sha256((plain_password + salt).encode()).hexdigest() == hash_value


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无法验证凭据",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = crud_user.get_by_username(db, username=username)
    if user is None:
        raise credentials_exception
    return user
