from typing import Any, Callable

from fastapi import APIRouter, Body, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import Select, false, func, or_, select, text
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.api.routes.process_data import (
    _account_balance_base_stmt,
    _account_balance_summary,
    _count_stmt,
    _inventory_base_stmt,
    _inventory_summary,
    _purchase_base_stmt,
    _purchase_summary,
    _safe_limit,
    _sales_base_stmt,
    _sales_summary,
)
from app.core.database import get_db
from app.models import (
    AccountBalanceSnapshot,
    ApprovalInstance,
    AuditLog,
    CrmFollowup,
    CrmProject,
    CrmProjectCustomerTask,
    CustomerBusinessProduct,
    CustomerBusinessProfile,
    CustomerMaster,
    CustomerPortraitSnapshot,
    InventorySnapshot,
    PurchaseDetail,
    SalesDetail,
    User,
    WorkItem,
)
from app.schemas.crm import (
    ApprovalInstancePublic,
    CrmFollowupPublic,
    CrmProjectCustomerTaskPublic,
    CrmProjectPublic,
    WorkItemPublic,
)
from app.services.access_control_service import apply_data_scope, serialize_many_with_field_rules, serialize_with_field_rules
from app.services.crm_access_service import crm_followup_scope_filter, crm_project_scope_filter, crm_task_scope_filter, crm_work_item_scope_filter
from app.services.crm_rollup_service import latest_project_followup, project_support_item_count, project_task_summary
from app.services.permission_service import has_permission

router = APIRouter(prefix="/context", tags=["context"])
PENDING_APPROVAL_STATUSES = ("submitted", "under_review", "need_supplement")


def _value(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _context_page(
    *,
    db: Session,
    current_user: User,
    permission_code: str,
    resource_type: str,
    model: Any,
    stmt: Select[tuple[Any]],
    order_by: tuple[Any, ...],
    summary: Callable[[Select[tuple[Any]]], dict],
    limit: int,
) -> dict:
    if not has_permission(db, current_user, permission_code):
        return {"available": False, "reason": f"missing_permission:{permission_code}", "page": None}
    scoped_stmt = apply_data_scope(stmt, model, db, current_user, resource_type)
    safe_limit = _safe_limit(limit)
    rows = list(db.scalars(scoped_stmt.order_by(*order_by).limit(safe_limit)).all())
    return {
        "available": True,
        "reason": None,
        "page": {
            "items": serialize_many_with_field_rules(db, current_user, resource_type, rows),
            "total": _count_stmt(db, scoped_stmt),
            "limit": safe_limit,
            "offset": 0,
            "summary": summary(scoped_stmt),
        },
    }


def _pending_project_approval_count(db: Session, project: CrmProject) -> int:
    filters = [
        (ApprovalInstance.resource_type == "crm_project")
        & (ApprovalInstance.resource_id == str(project.id))
    ]
    if project.current_approval_id:
        filters.append(ApprovalInstance.id == project.current_approval_id)
    return db.scalar(
        select(func.count())
        .select_from(ApprovalInstance)
        .where(or_(*filters), ApprovalInstance.status.in_(PENDING_APPROVAL_STATUSES))
    ) or 0


def _crm_project_public(db: Session, project: CrmProject) -> CrmProjectPublic:
    task_summary = project_task_summary(db, project.id)
    latest_followup = latest_project_followup(db, project.id)
    return CrmProjectPublic.model_validate(project).model_copy(
        update={
            "task_total": task_summary.get("total", 0),
            "task_closed": task_summary.get("closed", 0),
            "task_open": task_summary.get("open", 0),
            "task_need_support": task_summary.get("need_support", 0),
            "task_blocked": task_summary.get("blocked", 0),
            "support_item_open": project_support_item_count(db, project.id),
            "pending_approval_count": _pending_project_approval_count(db, project),
            "latest_followup_at": latest_followup.created_at if latest_followup else None,
        }
    )


def _followup_approval_task_filters(task_ids: list[int]) -> list[Any]:
    filters = []
    for index, task_id in enumerate(task_ids[:50]):
        filters.append(
            text(f"(approval_instance.payload_json #>> '{{followup,task_id}}') = :crm_customer_task_id_{index}")
            .bindparams(**{f"crm_customer_task_id_{index}": str(task_id)})
        )
    return filters


def _customer_crm_stats(
    *,
    projects: list[CrmProjectPublic],
    tasks: list[CrmProjectCustomerTaskPublic],
    followups: list[CrmFollowupPublic],
    work_items: list[WorkItemPublic],
    approvals: list[ApprovalInstancePublic],
) -> dict[str, int]:
    return {
        "project_total": len(projects),
        "task_total": len(tasks),
        "task_open": sum(1 for row in tasks if not row.is_closed and row.status != "closed"),
        "task_closed": sum(1 for row in tasks if row.is_closed or row.status == "closed"),
        "task_need_support": sum(1 for row in tasks if row.need_support),
        "task_blocked": sum(1 for row in tasks if row.is_blocked),
        "followup_total": len(followups),
        "work_item_open": sum(1 for row in work_items if row.status in {"open", "processing"}),
        "approval_pending": sum(1 for row in approvals if row.status in PENDING_APPROVAL_STATUSES),
    }


@router.get("/customers/{customer_code}")
def customer_context(
    customer_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if not has_permission(db, current_user, "customer.view"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing permission: customer.view")

    customer_stmt = apply_data_scope(
        select(CustomerMaster).where(CustomerMaster.customer_code == customer_code),
        CustomerMaster,
        db,
        current_user,
        "customer",
    )
    customer = db.scalar(customer_stmt)
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

    business_profile = None
    if has_permission(db, current_user, "customer_business.view"):
        profile = db.scalar(select(CustomerBusinessProfile).where(CustomerBusinessProfile.customer_code == customer.customer_code))
        products = list(
            db.scalars(
                select(CustomerBusinessProduct)
                .where(CustomerBusinessProduct.customer_code == customer.customer_code)
                .order_by(CustomerBusinessProduct.sort_order, CustomerBusinessProduct.id)
            ).all()
        )
        business_profile = {
            "profile": jsonable_encoder(profile) if profile else None,
            "products": jsonable_encoder(products),
        }

    portrait = None
    if has_permission(db, current_user, "customer_portrait.view"):
        snapshot = db.scalar(
            select(CustomerPortraitSnapshot)
            .where(CustomerPortraitSnapshot.customer_code == customer.customer_code)
            .order_by(CustomerPortraitSnapshot.generated_at.desc(), CustomerPortraitSnapshot.id.desc())
            .limit(1)
        )
        portrait = jsonable_encoder(snapshot) if snapshot else None

    project_rows: list[CrmProject] = []
    task_rows: list[CrmProjectCustomerTask] = []
    followup_rows: list[CrmFollowup] = []
    work_item_rows: list[WorkItem] = []
    approval_rows: list[ApprovalInstance] = []

    if has_permission(db, current_user, "crm_task.view"):
        task_stmt = crm_task_scope_filter(
            select(CrmProjectCustomerTask).where(CrmProjectCustomerTask.customer_code == customer.customer_code),
            db,
            current_user,
        )
        task_rows = list(db.scalars(task_stmt.order_by(CrmProjectCustomerTask.id.desc()).limit(50)).all())

    if has_permission(db, current_user, "crm_project.view"):
        project_stmt = crm_project_scope_filter(
            select(CrmProject)
            .join(CrmProjectCustomerTask, CrmProjectCustomerTask.project_id == CrmProject.id)
            .where(CrmProjectCustomerTask.customer_code == customer.customer_code),
            db,
            current_user,
        )
        project_rows = list(db.scalars(project_stmt.distinct().order_by(CrmProject.id.desc()).limit(20)).all())

    project_ids = [row.id for row in project_rows]
    task_ids = [row.id for row in task_rows]

    if has_permission(db, current_user, "crm_followup.view"):
        followup_stmt = crm_followup_scope_filter(
            select(CrmFollowup).where(CrmFollowup.customer_code == customer.customer_code),
            db,
            current_user,
        )
        followup_rows = list(db.scalars(followup_stmt.order_by(CrmFollowup.created_at.desc(), CrmFollowup.id.desc()).limit(50)).all())

    if has_permission(db, current_user, "crm_issue.view"):
        item_stmt = crm_work_item_scope_filter(
            select(WorkItem).where(WorkItem.customer_code == customer.customer_code),
            db,
            current_user,
        )
        work_item_rows = list(
            db.scalars(
                item_stmt.order_by(WorkItem.id.desc()).limit(20)
            ).all()
        )

    if has_permission(db, current_user, "approval.view"):
        approval_filters: list[Any] = []
        if project_ids:
            approval_filters.append(
                (ApprovalInstance.resource_type == "crm_project")
                & ApprovalInstance.resource_id.in_([str(project_id) for project_id in project_ids])
            )
        followup_filters = _followup_approval_task_filters(task_ids)
        if followup_filters:
            approval_filters.append((ApprovalInstance.approval_type == "crm_followup_submit") & or_(*followup_filters))
        if approval_filters:
            approval_rows = list(
                db.scalars(
                    select(ApprovalInstance)
                    .where(or_(*approval_filters))
                    .order_by(ApprovalInstance.id.desc())
                    .limit(20)
                ).all()
            )

    projects = [_crm_project_public(db, project) for project in project_rows]
    tasks = [CrmProjectCustomerTaskPublic.model_validate(task) for task in task_rows]
    followups = [CrmFollowupPublic.model_validate(followup) for followup in followup_rows]
    work_items = [WorkItemPublic.model_validate(item) for item in work_item_rows]
    approvals = [ApprovalInstancePublic.model_validate(approval) for approval in approval_rows]

    audit_rows = []
    if has_permission(db, current_user, "audit.view"):
        audit_rows = list(
            db.scalars(
                select(AuditLog)
                .where(
                    AuditLog.resource_id == customer.customer_code,
                    AuditLog.resource_type.in_(["customer", "customer_master", "customer_business_profile", "crm_project_task", "crm_followup", "work_item"]),
                )
                .order_by(AuditLog.id.desc())
                .limit(20)
            ).all()
        )

    return {
        "customer": serialize_with_field_rules(db, current_user, "customer", customer),
        "business_profile": business_profile,
        "portrait": portrait,
        "crm": {
            "available": any(
                has_permission(db, current_user, code)
                for code in ["crm_project.view", "crm_task.view", "crm_followup.view", "crm_issue.view", "approval.view"]
            ),
            "projects": jsonable_encoder(projects),
            "tasks": jsonable_encoder(tasks),
            "followups": jsonable_encoder(followups),
            "work_items": jsonable_encoder(work_items),
            "approvals": jsonable_encoder(approvals),
            "stats": _customer_crm_stats(projects=projects, tasks=tasks, followups=followups, work_items=work_items, approvals=approvals),
        },
        "audit": jsonable_encoder(audit_rows),
    }


@router.post("/process-detail")
def process_detail_context(
    payload: dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    kind = _value(payload, "kind") or ""
    limit = int(payload.get("limit") or 4)
    customer_code = _value(payload, "customerCode", "customer_code")
    customer_name = _value(payload, "customerName", "customer_name")
    supplier_code = _value(payload, "supplierCode", "supplier_code")
    supplier_name = _value(payload, "supplierName", "supplier_name", "defaultSupplier", "default_supplier")
    product_code = _value(payload, "productCode", "product_code")
    product_name = _value(payload, "productName", "product_name")
    settlement_code = _value(payload, "settlementCode", "settlement_code", "settlementUnitCode", "settlement_unit_code") or customer_code or supplier_code
    settlement_name = _value(payload, "settlementName", "settlement_name", "settlementUnitName", "settlement_unit_name") or customer_name or supplier_name
    unit_code = _value(payload, "unitCode", "unit_code") or settlement_code
    unit_name = _value(payload, "unitName", "unit_name") or settlement_name

    sales_stmt = _sales_base_stmt(q=None, date_from=None, date_to=None, customer_code=None, product_code=None, warehouse_name=None, employee_name=None).where(false())
    purchase_stmt = _purchase_base_stmt(q=None, date_from=None, date_to=None, supplier_code=None, product_code=None, warehouse_name=None, employee_name=None).where(false())
    inventory_stmt = _inventory_base_stmt(q=None, date_from=None, date_to=None, product_code=None, default_supplier=None, inventory_status=None).where(false())
    balance_stmt = _account_balance_base_stmt(q=None, date_from=None, date_to=None, settlement_unit_code=None, settlement_unit_name=None, balance_type=None).where(false())

    if kind == "sales":
        sales_stmt = _sales_base_stmt(
            q=None if customer_code else customer_name,
            date_from=None,
            date_to=None,
            customer_code=customer_code,
            product_code=None,
            warehouse_name=None,
            employee_name=None,
        )
        inventory_stmt = _inventory_base_stmt(
            q=None if product_code else product_name,
            date_from=None,
            date_to=None,
            product_code=product_code,
            default_supplier=None,
            inventory_status=None,
        )
        if product_code or product_name:
            purchase_stmt = _purchase_base_stmt(
                q=None if product_code else product_name,
                date_from=None,
                date_to=None,
                supplier_code=None,
                product_code=product_code,
                warehouse_name=None,
                employee_name=None,
            )
        balance_stmt = _account_balance_base_stmt(
            q=None,
            date_from=None,
            date_to=None,
            settlement_unit_code=settlement_code,
            settlement_unit_name=settlement_name,
            balance_type=None,
        )
    elif kind == "purchase":
        purchase_stmt = _purchase_base_stmt(
            q=None if supplier_code else supplier_name,
            date_from=None,
            date_to=None,
            supplier_code=supplier_code,
            product_code=None,
            warehouse_name=None,
            employee_name=None,
        )
        inventory_stmt = _inventory_base_stmt(
            q=None if product_code else product_name,
            date_from=None,
            date_to=None,
            product_code=product_code,
            default_supplier=None,
            inventory_status=None,
        )
        if product_code or product_name:
            sales_stmt = _sales_base_stmt(
                q=None if product_code else product_name,
                date_from=None,
                date_to=None,
                customer_code=None,
                product_code=product_code,
                warehouse_name=None,
                employee_name=None,
            )
        balance_stmt = _account_balance_base_stmt(
            q=None,
            date_from=None,
            date_to=None,
            settlement_unit_code=settlement_code,
            settlement_unit_name=settlement_name,
            balance_type=None,
        )
    elif kind == "inventory":
        if product_code or product_name:
            sales_stmt = _sales_base_stmt(q=None if product_code else product_name, date_from=None, date_to=None, customer_code=None, product_code=product_code, warehouse_name=None, employee_name=None)
            purchase_stmt = _purchase_base_stmt(q=None if product_code else product_name, date_from=None, date_to=None, supplier_code=None, product_code=product_code, warehouse_name=None, employee_name=None)
        if supplier_name:
            inventory_stmt = _inventory_base_stmt(q=None, date_from=None, date_to=None, product_code=None, default_supplier=supplier_name, inventory_status=None)
        if supplier_name:
            balance_stmt = _account_balance_base_stmt(q=None, date_from=None, date_to=None, settlement_unit_code=None, settlement_unit_name=supplier_name, balance_type=None)
    elif kind == "account":
        lookup = unit_name or unit_code
        if lookup:
            sales_stmt = _sales_base_stmt(q=lookup, date_from=None, date_to=None, customer_code=None, product_code=None, warehouse_name=None, employee_name=None)
            purchase_stmt = _purchase_base_stmt(q=lookup, date_from=None, date_to=None, supplier_code=None, product_code=None, warehouse_name=None, employee_name=None)
        if unit_name:
            inventory_stmt = _inventory_base_stmt(q=None, date_from=None, date_to=None, product_code=None, default_supplier=unit_name, inventory_status=None)
        balance_stmt = _account_balance_base_stmt(q=None, date_from=None, date_to=None, settlement_unit_code=unit_code, settlement_unit_name=unit_name, balance_type=None)

    return {
        "kind": kind,
        "limit": _safe_limit(limit),
        "sales": _context_page(
            db=db,
            current_user=current_user,
            permission_code="sales_detail.view",
            resource_type="sales_detail",
            model=SalesDetail,
            stmt=sales_stmt,
            order_by=(SalesDetail.document_date.desc().nullslast(), SalesDetail.id.desc()),
            summary=lambda stmt: _sales_summary(db, current_user, stmt),
            limit=limit,
        ),
        "purchase": _context_page(
            db=db,
            current_user=current_user,
            permission_code="purchase_detail.view",
            resource_type="purchase_detail",
            model=PurchaseDetail,
            stmt=purchase_stmt,
            order_by=(PurchaseDetail.document_date.desc().nullslast(), PurchaseDetail.id.desc()),
            summary=lambda stmt: _purchase_summary(db, stmt),
            limit=limit,
        ),
        "inventory": _context_page(
            db=db,
            current_user=current_user,
            permission_code="inventory_snapshot.view",
            resource_type="inventory_snapshot",
            model=InventorySnapshot,
            stmt=inventory_stmt,
            order_by=(InventorySnapshot.data_date.desc().nullslast(), InventorySnapshot.product_code, InventorySnapshot.id),
            summary=lambda stmt: _inventory_summary(db, stmt),
            limit=limit,
        ),
        "account": _context_page(
            db=db,
            current_user=current_user,
            permission_code="account_balance.view",
            resource_type="account_balance",
            model=AccountBalanceSnapshot,
            stmt=balance_stmt,
            order_by=(AccountBalanceSnapshot.data_date.desc().nullslast(), AccountBalanceSnapshot.settlement_unit_code, AccountBalanceSnapshot.id),
            summary=lambda stmt: _account_balance_summary(db, stmt),
            limit=limit,
        ),
    }
