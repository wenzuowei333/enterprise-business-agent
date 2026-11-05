from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.core.config import settings
from app.core.security import create_access_token, verify_password
from app.models import User
from app.schemas.identity import LoginRequest, TokenResponse, UserPublic
from app.services.audit_service import write_audit_log
from app.services.permission_service import get_final_permission_codes

router = APIRouter(prefix="/auth", tags=["auth"])
WEB_TOKEN_COOKIE = "project_base_token"


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.username == payload.username))
    if user is None or not verify_password(payload.password, user.password_hash) or not user.is_active or user.status != "active":
        write_audit_log(
            db,
            action_type="login_failed",
            resource_type="auth",
            resource_id=payload.username,
            request=request,
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    token = create_access_token(user.username, {"role": user.role, "user_id": user.id})
    user.last_login_at = func.now()
    user.last_login_ip = request.client.host if request.client else None
    write_audit_log(
        db,
        action_type="login_success",
        resource_type="auth",
        resource_id=str(user.id),
        user=user,
        request=request,
    )
    db.commit()
    response.set_cookie(
        WEB_TOKEN_COOKIE,
        token,
        max_age=settings.access_token_expire_minutes * 60,
        httponly=True,
        samesite="lax",
    )
    return TokenResponse(access_token=token, user=UserPublic.model_validate(user))


@router.get("/me", response_model=UserPublic)
def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.get("/my-permissions", response_model=list[str])
def my_permissions(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[str]:
    return get_final_permission_codes(db, current_user)


@router.post("/logout")
def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(WEB_TOKEN_COOKIE)
    return {"status": "ok"}
