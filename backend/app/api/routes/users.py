from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_permission
from app.core.config import settings
from app.core.database import get_db
from app.core.security import hash_password
from app.models import EmployeeProfile, Permission, Role, User, UserPermissionOverride, UserStatusHistory
from app.schemas.identity import (
    PasswordResetRequest,
    UserCreate,
    UserPublic,
    UserPermissionsPublic,
    UserPermissionsUpdate,
    UserStatusChangeRequest,
    UserStatusHistoryPublic,
    UserUpdate,
)
from app.services.audit_service import write_audit_log
from app.services.permission_service import ALLOW, DENY, VALID_EFFECTS, get_final_permission_codes, get_role_permission_codes, get_user_override_codes

router = APIRouter(prefix="/users", tags=["users"])

ACTIVE_STATUS = "active"
DISABLED_STATUS = "disabled"
CANCELLED_STATUS = "cancelled"
VALID_STATUSES = {ACTIVE_STATUS, DISABLED_STATUS, CANCELLED_STATUS}
MAX_AVATAR_BYTES = 3 * 1024 * 1024
AVATAR_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}


def ensure_role(db: Session, role_code: str) -> None:
    if db.scalar(select(Role).where(Role.role_code == role_code)) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Role not found")


def sync_active_flag(user: User) -> None:
    user.is_active = user.status == ACTIVE_STATUS


def upload_root() -> Path:
    root = Path(settings.upload_root)
    if not root.is_absolute():
        root = (Path(__file__).resolve().parents[3] / root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def detect_avatar_extension(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def remove_avatar_file(object_key: str | None) -> None:
    if not object_key:
        return
    root = upload_root()
    target = (root / object_key).resolve()
    if not target.is_relative_to(root):
        return
    if target.exists() and target.is_file():
        target.unlink()


async def persist_avatar_file(user_id: int, file: UploadFile) -> tuple[str, str]:
    if file.content_type not in AVATAR_CONTENT_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only jpg, png, and webp avatars are supported")
    data = await file.read(MAX_AVATAR_BYTES + 1)
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Avatar file is empty")
    if len(data) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Avatar file must be 3MB or smaller")
    extension = detect_avatar_extension(data)
    if extension is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid avatar image content")

    object_key = f"avatars/user_{user_id}_{uuid4().hex}{extension}"
    target = upload_root() / object_key
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return object_key, f"/uploads/{object_key}"


def add_status_history(
    db: Session,
    *,
    user: User,
    old_status: str | None,
    new_status: str,
    reason: str | None,
    operator: User,
) -> None:
    db.add(
        UserStatusHistory(
            user_id=user.id,
            old_status=old_status,
            new_status=new_status,
            reason=reason,
            changed_by=operator.id,
        )
    )


@router.get("", response_model=list[UserPublic])
def list_users(
    q: str | None = None,
    status_value: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("user.view")),
) -> list[User]:
    stmt = select(User).order_by(User.id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where((User.username.ilike(like)) | (User.real_name.ilike(like)) | (User.employee_code.ilike(like)))
    if status_value:
        stmt = stmt.where(User.status == status_value)
    return list(db.scalars(stmt).all())


@router.post("", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("user.create")),
) -> User:
    if payload.status not in VALID_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user status")
    if db.scalar(select(User).where(User.username == payload.username)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")
    ensure_role(db, payload.role)
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        real_name=payload.real_name,
        employee_code=payload.employee_code,
        role=payload.role,
        status=payload.status,
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    sync_active_flag(user)
    db.add(user)
    db.flush()
    add_status_history(db, user=user, old_status=None, new_status=user.status, reason="账号创建", operator=current_user)
    if payload.employee_code:
        employee = db.scalar(select(EmployeeProfile).where(EmployeeProfile.employee_code == payload.employee_code))
        if employee and employee.user_id is None:
            employee.user_id = user.id
            employee.role_code = payload.role
    write_audit_log(
        db,
        action_type="create",
        resource_type="user",
        resource_id=str(user.id),
        user=current_user,
        request=request,
        after_data={"username": user.username, "role": user.role, "status": user.status},
    )
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserPublic)
def update_user(
    user_id: int,
    payload: UserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("user.edit")),
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.status == CANCELLED_STATUS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cancelled user cannot be edited")
    data = payload.model_dump(exclude_unset=True)
    if "role" in data and data["role"]:
        ensure_role(db, data["role"])
    before = {"real_name": user.real_name, "employee_code": user.employee_code, "role": user.role}
    for key, value in data.items():
        setattr(user, key, value)
    user.updated_by = current_user.id
    write_audit_log(
        db,
        action_type="update",
        resource_type="user",
        resource_id=str(user.id),
        user=current_user,
        request=request,
        before_data=before,
        after_data=data,
    )
    db.commit()
    db.refresh(user)
    return user


@router.post("/me/avatar", response_model=UserPublic)
async def upload_my_avatar(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    old_object_key = current_user.avatar_object_key
    old_avatar_url = current_user.avatar_url
    object_key, avatar_url = await persist_avatar_file(current_user.id, file)
    current_user.avatar_object_key = object_key
    current_user.avatar_url = avatar_url
    current_user.avatar_updated_at = datetime.now(timezone.utc)
    current_user.updated_by = current_user.id
    write_audit_log(
        db,
        action_type="avatar_replace" if old_avatar_url else "avatar_upload",
        resource_type="user",
        resource_id=str(current_user.id),
        user=current_user,
        request=request,
        before_data={"avatar_url": old_avatar_url},
        after_data={"avatar_url": avatar_url},
    )
    db.commit()
    remove_avatar_file(old_object_key)
    db.refresh(current_user)
    return current_user


@router.delete("/me/avatar", response_model=UserPublic)
def delete_my_avatar(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    old_object_key = current_user.avatar_object_key
    old_avatar_url = current_user.avatar_url
    current_user.avatar_object_key = None
    current_user.avatar_url = None
    current_user.avatar_updated_at = datetime.now(timezone.utc)
    current_user.updated_by = current_user.id
    write_audit_log(
        db,
        action_type="avatar_delete",
        resource_type="user",
        resource_id=str(current_user.id),
        user=current_user,
        request=request,
        before_data={"avatar_url": old_avatar_url},
        after_data={"avatar_url": None},
    )
    db.commit()
    remove_avatar_file(old_object_key)
    db.refresh(current_user)
    return current_user


@router.post("/{user_id}/avatar", response_model=UserPublic)
async def upload_user_avatar(
    user_id: int,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("user.edit")),
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.status == CANCELLED_STATUS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cancelled user cannot be edited")
    old_object_key = user.avatar_object_key
    old_avatar_url = user.avatar_url
    object_key, avatar_url = await persist_avatar_file(user.id, file)
    user.avatar_object_key = object_key
    user.avatar_url = avatar_url
    user.avatar_updated_at = datetime.now(timezone.utc)
    user.updated_by = current_user.id
    write_audit_log(
        db,
        action_type="avatar_replace" if old_avatar_url else "avatar_upload",
        resource_type="user",
        resource_id=str(user.id),
        user=current_user,
        request=request,
        before_data={"avatar_url": old_avatar_url},
        after_data={"avatar_url": avatar_url},
    )
    db.commit()
    remove_avatar_file(old_object_key)
    db.refresh(user)
    return user


@router.delete("/{user_id}/avatar", response_model=UserPublic)
def delete_user_avatar(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("user.edit")),
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.status == CANCELLED_STATUS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cancelled user cannot be edited")
    old_object_key = user.avatar_object_key
    old_avatar_url = user.avatar_url
    user.avatar_object_key = None
    user.avatar_url = None
    user.avatar_updated_at = datetime.now(timezone.utc)
    user.updated_by = current_user.id
    write_audit_log(
        db,
        action_type="avatar_delete",
        resource_type="user",
        resource_id=str(user.id),
        user=current_user,
        request=request,
        before_data={"avatar_url": old_avatar_url},
        after_data={"avatar_url": None},
    )
    db.commit()
    remove_avatar_file(old_object_key)
    db.refresh(user)
    return user


@router.post("/{user_id}/reset-password", response_model=UserPublic)
def reset_password(
    user_id: int,
    payload: PasswordResetRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("user.reset_password")),
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.status == CANCELLED_STATUS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cancelled user cannot reset password")
    user.password_hash = hash_password(payload.password)
    user.password_updated_at = datetime.now(timezone.utc)
    user.updated_by = current_user.id
    write_audit_log(
        db,
        action_type="reset_password",
        resource_type="user",
        resource_id=str(user.id),
        user=current_user,
        request=request,
    )
    db.commit()
    db.refresh(user)
    return user


@router.post("/{user_id}/disable", response_model=UserPublic)
def disable_user(
    user_id: int,
    payload: UserStatusChangeRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("user.disable")),
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot disable current user")
    if user.status == CANCELLED_STATUS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cancelled user cannot be disabled")
    old_status = user.status
    user.status = DISABLED_STATUS
    user.disabled_reason = payload.reason
    user.updated_by = current_user.id
    sync_active_flag(user)
    add_status_history(db, user=user, old_status=old_status, new_status=user.status, reason=payload.reason, operator=current_user)
    write_audit_log(
        db,
        action_type="disable",
        resource_type="user",
        resource_id=str(user.id),
        user=current_user,
        request=request,
        before_data={"status": old_status},
        after_data={"status": user.status, "reason": payload.reason},
    )
    db.commit()
    db.refresh(user)
    return user


@router.post("/{user_id}/restore", response_model=UserPublic)
def restore_user(
    user_id: int,
    payload: UserStatusChangeRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("user.restore")),
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.status == CANCELLED_STATUS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cancelled user cannot be restored")
    old_status = user.status
    user.status = ACTIVE_STATUS
    user.disabled_reason = None
    user.updated_by = current_user.id
    sync_active_flag(user)
    add_status_history(db, user=user, old_status=old_status, new_status=user.status, reason=payload.reason, operator=current_user)
    write_audit_log(
        db,
        action_type="restore",
        resource_type="user",
        resource_id=str(user.id),
        user=current_user,
        request=request,
        before_data={"status": old_status},
        after_data={"status": user.status, "reason": payload.reason},
    )
    db.commit()
    db.refresh(user)
    return user


@router.post("/{user_id}/cancel", response_model=UserPublic)
def cancel_user(
    user_id: int,
    payload: UserStatusChangeRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("user.cancel")),
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot cancel current user")
    old_status = user.status
    user.status = CANCELLED_STATUS
    user.cancelled_reason = payload.reason
    user.cancelled_by = current_user.id
    user.cancelled_at = datetime.now(timezone.utc)
    user.updated_by = current_user.id
    sync_active_flag(user)
    add_status_history(db, user=user, old_status=old_status, new_status=user.status, reason=payload.reason, operator=current_user)
    write_audit_log(
        db,
        action_type="cancel",
        resource_type="user",
        resource_id=str(user.id),
        user=current_user,
        request=request,
        before_data={"status": old_status},
        after_data={"status": user.status, "reason": payload.reason},
    )
    db.commit()
    db.refresh(user)
    return user


@router.get("/{user_id}/status-history", response_model=list[UserStatusHistoryPublic])
def list_user_status_history(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("user.view")),
) -> list[UserStatusHistory]:
    if db.get(User, user_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    stmt = select(UserStatusHistory).where(UserStatusHistory.user_id == user_id).order_by(UserStatusHistory.id.desc())
    return list(db.scalars(stmt).all())


@router.get("/{user_id}/permissions", response_model=UserPermissionsPublic)
def get_user_permissions(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("user.permission_config")),
) -> UserPermissionsPublic:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    allow_codes, deny_codes = get_user_override_codes(db, user.id)
    return UserPermissionsPublic(
        user=UserPublic.model_validate(user),
        role_permission_codes=get_role_permission_codes(db, user.role),
        allow_permission_codes=allow_codes,
        deny_permission_codes=deny_codes,
        final_permission_codes=get_final_permission_codes(db, user),
    )


@router.put("/{user_id}/permissions", response_model=UserPermissionsPublic)
def update_user_permissions(
    user_id: int,
    payload: UserPermissionsUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("user.permission_config")),
) -> UserPermissionsPublic:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.status == CANCELLED_STATUS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cancelled user cannot configure permissions")

    requested: dict[str, str] = {}
    for item in payload.overrides:
        if item.effect not in VALID_EFFECTS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid override effect")
        requested[item.permission_code] = item.effect

    permissions = list(db.scalars(select(Permission).where(Permission.permission_code.in_(requested.keys()))).all())
    found_codes = {permission.permission_code for permission in permissions}
    missing_codes = sorted(set(requested.keys()) - found_codes)
    if missing_codes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown permissions: {', '.join(missing_codes)}")

    before_allow, before_deny = get_user_override_codes(db, user.id)
    db.query(UserPermissionOverride).filter(UserPermissionOverride.user_id == user.id).delete(synchronize_session=False)
    for permission in permissions:
        db.add(
            UserPermissionOverride(
                user_id=user.id,
                permission_id=permission.id,
                effect=requested[permission.permission_code],
                created_by=current_user.id,
                updated_by=current_user.id,
            )
        )

    write_audit_log(
        db,
        action_type="update_user_permissions",
        resource_type="user_permission",
        resource_id=str(user.id),
        user=current_user,
        request=request,
        before_data={"allow": before_allow, "deny": before_deny},
        after_data={
            "allow": sorted(code for code, effect in requested.items() if effect == ALLOW),
            "deny": sorted(code for code, effect in requested.items() if effect == DENY),
        },
    )
    db.commit()
    return get_user_permissions(user_id, db, current_user)


@router.post("/{user_id}/permissions/reset-to-role", response_model=UserPermissionsPublic)
def reset_user_permissions_to_role(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("user.permission_config")),
) -> UserPermissionsPublic:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    before_allow, before_deny = get_user_override_codes(db, user.id)
    db.query(UserPermissionOverride).filter(UserPermissionOverride.user_id == user.id).delete(synchronize_session=False)
    write_audit_log(
        db,
        action_type="reset_user_permissions",
        resource_type="user_permission",
        resource_id=str(user.id),
        user=current_user,
        request=request,
        before_data={"allow": before_allow, "deny": before_deny},
        after_data={"allow": [], "deny": []},
    )
    db.commit()
    return get_user_permissions(user_id, db, current_user)
