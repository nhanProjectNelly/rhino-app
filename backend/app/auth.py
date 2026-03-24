import bcrypt
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Annotated
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

# Rate limit: 10 requests per hour for non-admin (predict)
_RATE_WINDOW_SEC = 3600
_RATE_MAX_PER_HOUR = 10
_rate_store: dict[int, list[float]] = defaultdict(list)

# Bcrypt limit is 72 bytes
_MAX_BCRYPT_BYTES = 72


def _to_bcrypt_input(password: str) -> bytes:
    pwd_bytes = password.encode("utf-8")
    return pwd_bytes[: _MAX_BCRYPT_BYTES] if len(pwd_bytes) > _MAX_BCRYPT_BYTES else pwd_bytes


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(_to_bcrypt_input(plain), hashed.encode("utf-8") if isinstance(hashed, str) else hashed)


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(_to_bcrypt_input(password), bcrypt.gensalt()).decode("utf-8")


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return user


def require_admin(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    if getattr(current_user, "role", "user") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return current_user


def check_predict_rate_limit(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    if getattr(current_user, "role", "user") == "admin":
        return current_user
    now = time.time()
    key = current_user.id
    _rate_store[key] = [t for t in _rate_store[key] if now - t < _RATE_WINDOW_SEC]
    if len(_rate_store[key]) >= _RATE_MAX_PER_HOUR:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit: max {_RATE_MAX_PER_HOUR} predict queries per hour",
        )
    _rate_store[key].append(now)
    return current_user
