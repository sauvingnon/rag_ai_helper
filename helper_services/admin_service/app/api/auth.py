from datetime import datetime, timezone, timedelta

import jwt
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from app.config import ADMIN_LOGIN, ADMIN_PASSWORD, JWT_SECRET, JWT_EXPIRE_HOURS

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_NAME = "admin_token"


def make_token() -> str:
    payload = {
        "sub": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def verify_token(token: str) -> bool:
    try:
        jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return True
    except jwt.PyJWTError:
        return False


class LoginRequest(BaseModel):
    login: str
    password: str


@router.post("/login")
async def login(body: LoginRequest, response: Response):
    if body.login != ADMIN_LOGIN or body.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    response.set_cookie(
        key=COOKIE_NAME,
        value=make_token(),
        httponly=True,
        samesite="lax",
        max_age=JWT_EXPIRE_HOURS * 3600,
    )
    return {"ok": True}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, samesite="lax")
    return {"ok": True}


@router.get("/me")
async def me(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if not token or not verify_token(token):
        raise HTTPException(status_code=401, detail="Не авторизован")
    return {"ok": True}
