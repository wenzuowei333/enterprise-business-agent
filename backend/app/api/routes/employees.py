from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_permission
from app.core.database import get_db
from app.models import EmployeeProfile, User
from app.schemas.identity import EmployeeProfileCreate, EmployeeProfilePublic, EmployeeProfileUpdate
from app.services.audit_service import write_audit_log

router = APIRouter(prefix="/employees", tags=["employees"])

EMPLOYEE_STATUS_VALUES = {"active", "disabled"}


@router.get("", response_model=list[EmployeeProfilePublic])
def list_employees(
    q: str | None = None,
    status_value: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("employee.view")),
) -> list[EmployeeProfile]:
    stmt = select(EmployeeProfile).order_by(EmployeeProfile.employee_code)
    if q:
        like = f"%{q}%"
        stmt = stmt.where((EmployeeProfile.employee_code.ilike(like)) | (EmployeeProfile.employee_name.ilike(like)))
    if status_value:
        stmt = stmt.where(EmployeeProfile.status == status_value)
    return list(db.scalars(stmt).all())


@router.get("/page")
def list_employees_page(
    q: str | None = None,
    status_value: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("employee.view")),
) -> dict:
    safe_limit = max(1, min(limit, 50))
    safe_offset = max(0, offset)
    stmt = select(EmployeeProfile).order_by(EmployeeProfile.employee_code)
    if q:
        like = f"%{q}%"
        stmt = stmt.where((EmployeeProfile.employee_code.ilike(like)) | (EmployeeProfile.employee_name.ilike(like)))
    if status_value:
        stmt = stmt.where(EmployeeProfile.status == status_value)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = list(db.scalars(stmt.offset(safe_offset).limit(safe_limit)).all())
    return {"items": jsonable_encoder(rows), "total": total, "limit": safe_limit, "offset": safe_offset}


@router.get("/{employee_code}", response_model=EmployeeProfilePublic)
def get_employee(
    employee_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("employee.view")),
) -> EmployeeProfile:
    employee = db.scalar(select(EmployeeProfile).where(EmployeeProfile.employee_code == employee_code))
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    return employee


@router.post("", response_model=EmployeeProfilePublic, status_code=status.HTTP_201_CREATED)
def create_employee(
    payload: EmployeeProfileCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("employee.create")),
) -> EmployeeProfile:
    existing = db.scalar(select(EmployeeProfile).where(EmployeeProfile.employee_code == payload.employee_code))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Employee code already exists")
    employee = EmployeeProfile(**payload.model_dump())
    db.add(employee)
    db.flush()
    write_audit_log(
        db,
        action_type="create",
        resource_type="employee_profile",
        resource_id=employee.employee_code,
        user=current_user,
        request=request,
        after_data=payload.model_dump(),
    )
    db.commit()
    db.refresh(employee)
    return employee


@router.patch("/{employee_code}", response_model=EmployeeProfilePublic)
def update_employee(
    employee_code: str,
    payload: EmployeeProfileUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("employee.edit")),
) -> EmployeeProfile:
    employee = db.scalar(select(EmployeeProfile).where(EmployeeProfile.employee_code == employee_code))
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    changes = payload.model_dump(exclude_unset=True)
    if "employee_name" in changes and not _clean_text(changes["employee_name"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Employee name is required")
    if "status" in changes and changes["status"] not in EMPLOYEE_STATUS_VALUES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid employee status")
    before = {
        "employee_name": employee.employee_name,
        "user_id": employee.user_id,
        "department": employee.department,
        "position": employee.position,
        "role_code": employee.role_code,
        "manager_employee_code": employee.manager_employee_code,
        "status": employee.status,
        "phone": employee.phone,
    }
    for key, value in changes.items():
        setattr(employee, key, _clean_text(value) if isinstance(value, str) else value)
    write_audit_log(
        db,
        action_type="update",
        resource_type="employee_profile",
        resource_id=employee.employee_code,
        user=current_user,
        request=request,
        before_data=before,
        after_data=changes,
    )
    db.commit()
    db.refresh(employee)
    return employee


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None
