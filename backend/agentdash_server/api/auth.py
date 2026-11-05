from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from ..core.auth import COOKIE_NAME
from ..core.state import AppState
from .deps import get_state

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginBody(BaseModel):
    password: str


@router.get("/status")
async def status(request: Request, state: AppState = Depends(get_state)) -> dict:
    return {
        "auth_required": state.auth.enabled,
        "authenticated": state.auth.verify(request.cookies.get(COOKIE_NAME)),
    }


@router.post("/login")
async def login(body: LoginBody, request: Request, response: Response, state: AppState = Depends(get_state)) -> dict:
    if not state.auth.enabled:
        return {"ok": True}
    if not state.auth.check_password(body.password):
        raise HTTPException(status_code=401, detail="Falsches Passwort")
    response.set_cookie(
        COOKIE_NAME,
        state.auth.issue(),
        max_age=state.auth.session_seconds,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    return {"ok": True}


@router.post("/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}
