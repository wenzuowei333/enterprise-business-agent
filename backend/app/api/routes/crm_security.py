from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_crm_permission
from app.core.database import get_db
from app.models import User
from app.services.crm_access_service import CRM_PERMISSION_RESOURCES, get_crm_permission_codes

router = APIRouter(prefix="/crm/security", tags=["crm-security"])


@router.get("/capabilities")
def crm_capabilities(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, object]:
    permission_codes = get_crm_permission_codes(db, current_user)
    grouped = {resource: [] for resource in sorted(CRM_PERMISSION_RESOURCES)}
    for code in permission_codes:
        resource = code.split(".", 1)[0]
        grouped.setdefault(resource, []).append(code)
    return {
        "user_id": current_user.id,
        "role_code": current_user.role,
        "permission_codes": permission_codes,
        "grouped": grouped,
    }


@router.get("/project-access")
def crm_project_access_probe(
    current_user: User = Depends(require_crm_permission("crm_project.view")),
) -> dict[str, object]:
    return {"status": "ok", "resource": "crm_project", "user_id": current_user.id}


@router.get("/approval-access")
def crm_approval_access_probe(
    current_user: User = Depends(require_crm_permission("approval.approve")),
) -> dict[str, object]:
    return {"status": "ok", "resource": "approval", "user_id": current_user.id}
