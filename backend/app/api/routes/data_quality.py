from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_permission
from app.core.database import get_db
from app.models import MasterLinkIssue, User
from app.schemas.master_data import (
    MasterLinkIssuePage,
    MasterLinkIssuePublic,
    MasterLinkIssueRebuildResponse,
    MasterLinkIssueResolveRequest,
)
from app.services.audit_service import write_audit_log
from app.services.master_link_service import (
    master_link_issue_summary,
    rebuild_master_link_issues,
    resolve_master_link_issue,
)


router = APIRouter(prefix="/data-quality/master-link", tags=["data-quality-master-link"])


def _safe_limit(limit: int) -> int:
    return max(1, min(limit, 200))


def _safe_offset(offset: int) -> int:
    return max(0, offset)


@router.get("/issues", response_model=MasterLinkIssuePage)
def list_master_link_issues(
    issue_type: str | None = None,
    expected_master_kind: str | None = None,
    source_file_type: str | None = None,
    status: str = "open",
    q: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("import.view")),
) -> dict:
    safe_limit = _safe_limit(limit)
    safe_offset = _safe_offset(offset)
    stmt = select(MasterLinkIssue)
    if status:
        stmt = stmt.where(MasterLinkIssue.status == status)
    if issue_type:
        stmt = stmt.where(MasterLinkIssue.issue_type == issue_type)
    if expected_master_kind:
        stmt = stmt.where(MasterLinkIssue.expected_master_kind == expected_master_kind)
    if source_file_type:
        stmt = stmt.where(MasterLinkIssue.source_file_type == source_file_type)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            (MasterLinkIssue.reference_code.ilike(like))
            | (MasterLinkIssue.reference_name.ilike(like))
            | (MasterLinkIssue.counterpart_code.ilike(like))
            | (MasterLinkIssue.counterpart_name.ilike(like))
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        db.scalars(
            stmt.order_by(MasterLinkIssue.amount_total.desc().nullslast(), MasterLinkIssue.updated_at.desc(), MasterLinkIssue.id.desc())
            .offset(safe_offset)
            .limit(safe_limit)
        ).all()
    )
    return {
        "items": rows,
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
        "summary": master_link_issue_summary(db),
    }


@router.post("/issues/{issue_id}/resolve", response_model=MasterLinkIssuePublic)
def resolve_issue(
    issue_id: int,
    payload: MasterLinkIssueResolveRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("import.commit")),
) -> MasterLinkIssue:
    issue = resolve_master_link_issue(
        db,
        issue_id,
        user=current_user,
        resolution_type=payload.resolution_type,
        note=payload.note,
    )
    write_audit_log(
        db,
        action_type="resolve_master_link_issue",
        resource_type="master_link_issue",
        resource_id=str(issue.id),
        user=current_user,
        request=request,
        after_data=jsonable_encoder(issue),
    )
    db.commit()
    db.refresh(issue)
    return issue


@router.post("/rebuild", response_model=MasterLinkIssueRebuildResponse)
def rebuild_issues(
    request: Request,
    batch_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("import.commit")),
) -> dict[str, int]:
    result = rebuild_master_link_issues(db, batch_id=batch_id)
    from app.services.exception_center_service import enqueue_incremental_exception_scan_safely

    enqueue_incremental_exception_scan_safely(db, domains=["master_data"])
    write_audit_log(
        db,
        action_type="rebuild_master_link_issues",
        resource_type="master_link_issue",
        resource_id=str(batch_id or "all"),
        user=current_user,
        request=request,
        after_data=result,
    )
    db.commit()
    return result
