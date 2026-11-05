from __future__ import annotations

import secrets
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models import (
    ExternalApiKey,
    ImportBatch,
    ImportError,
    InventoryAnomalyCase,
    InventoryCheckBatch,
    InventoryCheckResult,
    InventoryFlowLedger,
    InventoryRemediationAction,
    InventorySnapshot,
    ProductMaster,
    PurchaseDetail,
    SalesDetail,
    SupplierMaster,
    User,
)
from app.schemas.external_api import (
    ExternalEnvelope,
    ExternalInventoryActionExecuteRequest,
    ExternalInventoryActionItem,
    ExternalInventoryActionValidateRequest,
    ExternalInventoryActionValidationData,
    ExternalInventoryAnomalyItem,
    ExternalInventoryAnomalyListData,
    ExternalInventoryDiagnosisCreate,
    ExternalInventoryEvidenceData,
)
from app.services.audit_service import write_audit_log
from app.services.external_api_service import (
    apply_external_cursor,
    audit_external_request,
    external_key_dependency,
    external_limit,
    external_meta,
    external_page,
    external_permission_enabled,
    external_request_id,
    hash_external_token,
    require_external_permission,
)
from app.services.inventory_agent_service import (
    ensure_blocked_work_item,
    remediation_blockers,
    remediation_impact,
    serialize_anomaly_case,
    serialize_remediation_action,
    sync_inventory_anomaly_cases,
    utcnow,
)
from app.services.inventory_check_service import rebuild_inventory_check_batch
from app.services.inventory_flow_service import rebuild_inventory_flow, serialize_inventory_flow
from app.services.crm_project_service import generated_code


router = APIRouter(prefix="/api/external/v2/inventory", tags=["external-agent-api-v2-inventory"])

EVIDENCE_PERMISSION_FIELDS = (
    "can_read_inventory_evidence",
    "can_read_sales_details_sensitive",
    "can_read_purchase_details_sensitive",
    "can_read_inventory_checks",
    "can_read_imports",
)


def _json_data(value: Any) -> Any:
    return jsonable_encoder(value, custom_encoder={Decimal: str})


def _case_item(case: InventoryAnomalyCase) -> ExternalInventoryAnomalyItem:
    return ExternalInventoryAnomalyItem.model_validate(serialize_anomaly_case(case))


def _action_item(action: InventoryRemediationAction) -> ExternalInventoryActionItem:
    return ExternalInventoryActionItem.model_validate(serialize_remediation_action(action))


def _get_case(db: Session, case_id: int) -> InventoryAnomalyCase:
    case = db.get(InventoryAnomalyCase, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory anomaly case not found")
    return case


def _get_action(db: Session, action_id: int) -> InventoryRemediationAction:
    action = db.get(InventoryRemediationAction, action_id)
    if action is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory remediation action not found")
    return action


def _get_action_for_update(db: Session, action_id: int) -> InventoryRemediationAction:
    action = db.scalar(
        select(InventoryRemediationAction)
        .where(InventoryRemediationAction.id == action_id)
        .with_for_update()
    )
    if action is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory remediation action not found")
    return action


def _get_case_for_update(db: Session, case_id: int) -> InventoryAnomalyCase:
    case = db.scalar(
        select(InventoryAnomalyCase)
        .where(InventoryAnomalyCase.id == case_id)
        .with_for_update()
    )
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory anomaly case not found")
    return case


def _require_inventory_evidence_permissions(
    api_key: ExternalApiKey = Depends(external_key_dependency),
) -> ExternalApiKey:
    missing = [
        permission
        for permission in EVIDENCE_PERMISSION_FIELDS
        if not external_permission_enabled(api_key, permission)
    ]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"API key lacks required evidence scopes: {', '.join(missing)}",
        )
    return api_key


def _stamp(request_id: str, resource_type: str, resource_id: int | str, values: dict[str, Any]) -> dict[str, Any]:
    return {"resource_type": resource_type, "resource_id": resource_id, "request_id": request_id, **values}


def _snapshot_payload(row: InventorySnapshot, request_id: str) -> dict[str, Any]:
    return _stamp(
        request_id,
        "inventory_snapshot",
        row.id,
        {
            "batch_id": row.batch_id,
            "row_number": row.row_number,
            "data_date": row.data_date,
            "product_code": row.product_code,
            "product_name": row.product_name,
            "warehouse_name": row.warehouse_name,
            "warehouse_scope": row.warehouse_scope,
            "barcode": row.barcode,
            "default_supplier": row.default_supplier,
            "unit_relation": row.unit_relation,
            "stock_qty": row.stock_qty,
            "stock_base_unit": row.stock_base_unit,
            "stock_inventory_qty": row.stock_inventory_qty,
            "stock_inventory_unit": row.stock_inventory_unit,
            "locked_base_qty": row.locked_base_qty,
            "inventory_status": row.inventory_status,
            "float_qty": row.float_qty,
            "float_unit": row.float_unit,
            "average_cost": row.average_cost,
            "cost_amount": row.cost_amount,
            "auxiliary_qty": row.auxiliary_qty,
            "created_at": row.created_at,
        },
    )


@router.get("/anomalies", response_model=ExternalEnvelope[ExternalInventoryAnomalyListData])
def external_inventory_anomalies(
    request: Request,
    data_from: date | None = None,
    data_to: date | None = None,
    product_code: str | None = None,
    warehouse_name: str | None = None,
    reason_code: str | None = Query(default=None, pattern="^(negative_stock|locked_stock)$"),
    case_status: str | None = Query(default=None, alias="status", pattern="^(open|diagnosed|blocked|executing|resolved)$"),
    cursor: str | None = None,
    limit: int = 50,
    api_key: ExternalApiKey = Depends(require_external_permission("can_read_inventory_anomalies")),
    db: Session = Depends(get_db),
) -> ExternalEnvelope[ExternalInventoryAnomalyListData]:
    limit_value = external_limit(limit, maximum=100)
    latest_batch = sync_inventory_anomaly_cases(db)
    stmt = select(InventoryAnomalyCase)
    if data_from:
        stmt = stmt.where(InventoryAnomalyCase.data_date >= data_from)
    if data_to:
        stmt = stmt.where(InventoryAnomalyCase.data_date <= data_to)
    if product_code:
        stmt = stmt.where(InventoryAnomalyCase.product_code == product_code)
    if warehouse_name:
        stmt = stmt.where(InventoryAnomalyCase.warehouse_name == warehouse_name)
    if reason_code:
        stmt = stmt.where(InventoryAnomalyCase.reason_code == reason_code)
    if case_status:
        stmt = stmt.where(InventoryAnomalyCase.status == case_status)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    stmt = apply_external_cursor(stmt, InventoryAnomalyCase, cursor, dialect_name=db.get_bind().dialect.name)
    rows = list(
        db.scalars(stmt.order_by(InventoryAnomalyCase.updated_at.desc(), InventoryAnomalyCase.id.desc()).limit(limit_value + 1)).all()
    )
    page_rows, next_cursor, has_more = external_page(rows, limit_value)
    data = ExternalInventoryAnomalyListData(
        items=[_case_item(row) for row in page_rows],
        count=int(total),
        latest_batch_id=latest_batch.id if latest_batch else None,
        data_cutoff_date=latest_batch.data_date if latest_batch else None,
    )
    audit_external_request(db, request, api_key, "/inventory/anomalies", {"count": len(page_rows)})
    return ExternalEnvelope(data=data, meta=external_meta(request, next_cursor=next_cursor, has_more=has_more))


@router.get("/anomalies/{case_id}", response_model=ExternalEnvelope[ExternalInventoryAnomalyItem])
def external_inventory_anomaly_detail(
    case_id: int,
    request: Request,
    api_key: ExternalApiKey = Depends(require_external_permission("can_read_inventory_anomalies")),
    db: Session = Depends(get_db),
) -> ExternalEnvelope[ExternalInventoryAnomalyItem]:
    sync_inventory_anomaly_cases(db)
    case = _get_case(db, case_id)
    audit_external_request(db, request, api_key, f"/inventory/anomalies/{case_id}")
    return ExternalEnvelope(data=_case_item(case), meta=external_meta(request))


@router.get("/anomalies/{case_id}/evidence", response_model=ExternalEnvelope[ExternalInventoryEvidenceData])
def external_inventory_anomaly_evidence(
    case_id: int,
    request: Request,
    lookback_days: int = Query(default=90, ge=1, le=730),
    detail_limit: int = Query(default=200, ge=1, le=500),
    api_key: ExternalApiKey = Depends(_require_inventory_evidence_permissions),
    db: Session = Depends(get_db),
) -> ExternalEnvelope[ExternalInventoryEvidenceData]:
    sync_inventory_anomaly_cases(db)
    case = _get_case(db, case_id)
    snapshot = db.get(InventorySnapshot, case.snapshot_id) if case.snapshot_id else None
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Inventory anomaly snapshot is no longer available")
    request_id = external_request_id(request)
    date_from = case.data_date - timedelta(days=lookback_days) if case.data_date else None

    product = db.scalar(select(ProductMaster).where(ProductMaster.product_code == case.product_code)) if case.product_code else None
    supplier = None
    if snapshot.default_supplier:
        supplier = db.scalar(
            select(SupplierMaster).where(
                or_(
                    SupplierMaster.supplier_name == snapshot.default_supplier,
                    SupplierMaster.supplier_short_name == snapshot.default_supplier,
                    SupplierMaster.supplier_code == snapshot.default_supplier,
                )
            )
        )

    snapshot_stmt = select(InventorySnapshot).where(InventorySnapshot.product_code == case.product_code)
    flow_stmt = select(InventoryFlowLedger).where(InventoryFlowLedger.product_code == case.product_code)
    sales_stmt = select(SalesDetail).where(SalesDetail.product_code == case.product_code)
    purchase_stmt = select(PurchaseDetail).where(PurchaseDetail.product_code == case.product_code)
    if case.warehouse_name and case.warehouse_name not in {"-", "未识别仓库"}:
        snapshot_stmt = snapshot_stmt.where(InventorySnapshot.warehouse_name == case.warehouse_name)
        flow_stmt = flow_stmt.where(InventoryFlowLedger.warehouse_name == case.warehouse_name)
        sales_stmt = sales_stmt.where(SalesDetail.warehouse_name == case.warehouse_name)
        purchase_stmt = purchase_stmt.where(PurchaseDetail.warehouse_name == case.warehouse_name)
    if date_from:
        snapshot_stmt = snapshot_stmt.where(InventorySnapshot.data_date >= date_from)
        flow_stmt = flow_stmt.where(InventoryFlowLedger.data_date >= date_from)
        sales_stmt = sales_stmt.where(SalesDetail.data_date >= date_from)
        purchase_stmt = purchase_stmt.where(PurchaseDetail.data_date >= date_from)
    if case.data_date:
        snapshot_stmt = snapshot_stmt.where(InventorySnapshot.data_date <= case.data_date)
        flow_stmt = flow_stmt.where(InventoryFlowLedger.data_date <= case.data_date)
        sales_stmt = sales_stmt.where(SalesDetail.data_date <= case.data_date)
        purchase_stmt = purchase_stmt.where(PurchaseDetail.data_date <= case.data_date)

    historical = list(db.scalars(snapshot_stmt.order_by(InventorySnapshot.data_date.desc(), InventorySnapshot.id.desc()).limit(detail_limit)).all())
    flows = list(db.scalars(flow_stmt.order_by(InventoryFlowLedger.data_date.desc(), InventoryFlowLedger.id.desc()).limit(detail_limit)).all())
    sales = list(db.scalars(sales_stmt.order_by(SalesDetail.data_date.desc(), SalesDetail.id.desc()).limit(detail_limit)).all())
    purchases = list(db.scalars(purchase_stmt.order_by(PurchaseDetail.data_date.desc(), PurchaseDetail.id.desc()).limit(detail_limit)).all())
    checks = list(
        db.scalars(
            select(InventoryCheckResult)
            .where(InventoryCheckResult.product_code == case.product_code)
            .order_by(InventoryCheckResult.created_at.desc(), InventoryCheckResult.id.desc())
            .limit(detail_limit)
        ).all()
    )
    imports = list(
        db.scalars(
            select(ImportBatch)
            .where(ImportBatch.file_type.in_(["inventory_snapshot", "sales_detail", "purchase_detail"]))
            .order_by(ImportBatch.uploaded_at.desc(), ImportBatch.id.desc())
            .limit(30)
        ).all()
    )
    import_ids = [row.id for row in imports]
    import_errors = list(
        db.scalars(
            select(ImportError)
            .where(ImportError.batch_id.in_(import_ids))
            .order_by(ImportError.created_at.desc(), ImportError.id.desc())
            .limit(detail_limit)
        ).all()
    ) if import_ids else []

    product_data = _stamp(request_id, "product_master", product.id, {
        "product_code": product.product_code, "product_name": product.product_name, "spec": product.spec,
        "unit": product.unit, "category": product.category, "brand": product.brand, "barcode": product.barcode,
        "reference_sale_price": product.reference_sale_price, "reference_cost": product.reference_cost,
        "status": product.status, "updated_at": product.updated_at,
    }) if product else None
    supplier_data = _stamp(request_id, "supplier_master", supplier.id, {
        "supplier_code": supplier.supplier_code, "supplier_name": supplier.supplier_name,
        "supplier_short_name": supplier.supplier_short_name, "supplier_type": supplier.supplier_type,
        "region": supplier.region, "status": supplier.status, "updated_at": supplier.updated_at,
    }) if supplier else None
    flow_data = [
        _stamp(request_id, "inventory_flow_ledger", row.id, serialize_inventory_flow(row)) for row in flows
    ]
    sales_data = [
        _stamp(request_id, "sales_detail", row.id, {
            "batch_id": row.batch_id, "data_date": row.data_date, "document_no": row.document_no,
            "document_date": row.document_date, "posted_at": row.posted_at, "document_type": row.document_type,
            "branch_name": row.branch_name, "department_name": row.department_name,
            "customer_code": row.customer_code, "customer_name": row.customer_name, "employee_name": row.employee_name,
            "warehouse_name": row.warehouse_name, "product_code": row.product_code, "product_name": row.product_name,
            "sale_qty_base": row.sale_qty_base, "sale_qty_unit": row.sale_qty_unit, "sale_qty_float": row.sale_qty_float,
            "amount_after_discount": row.amount_after_discount, "amount_tax_total": row.amount_tax_total,
            "cost_unit_price": row.cost_unit_price, "cost_amount": row.cost_amount, "gross_profit": row.gross_profit,
            "gross_margin_rate": row.gross_margin_rate, "note": row.note, "summary": row.summary,
            "reconciliation_mark": row.reconciliation_mark, "created_at": row.created_at,
        }) for row in sales
    ]
    purchase_data = [
        _stamp(request_id, "purchase_detail", row.id, {
            "batch_id": row.batch_id, "data_date": row.data_date, "document_no": row.document_no,
            "document_date": row.document_date, "posted_at": row.posted_at, "document_type": row.document_type,
            "branch_name": row.branch_name, "department_name": row.department_name,
            "supplier_code": row.supplier_code, "supplier_name": row.supplier_name, "employee_name": row.employee_name,
            "warehouse_name": row.warehouse_name, "product_code": row.product_code, "product_name": row.product_name,
            "purchase_qty_base": row.purchase_qty_base, "purchase_qty_unit": row.purchase_qty_unit,
            "purchase_qty_float": row.purchase_qty_float, "unit_price": row.unit_price,
            "amount_after_discount": row.amount_after_discount, "amount_tax_total": row.amount_tax_total,
            "purchase_amount": row.purchase_amount, "prepared_note": row.prepared_note, "summary": row.summary,
            "remark": row.remark, "reconciliation_mark": row.reconciliation_mark, "created_at": row.created_at,
        }) for row in purchases
    ]
    check_data = [
        _stamp(request_id, "inventory_check_result", row.id, {
            "batch_id": row.batch_id, "result_type": row.result_type, "product_code": row.product_code,
            "product_name": row.product_name, "warehouse_name": row.warehouse_name,
            "warehouse_scope": row.warehouse_scope, "platform_stock_qty": row.platform_stock_qty,
            "system_stock_qty": row.system_stock_qty, "diff_qty": row.diff_qty,
            "system_data_date": row.system_data_date, "duplicate_in_upload": row.duplicate_in_upload,
            "source_row_numbers": row.source_row_numbers, "created_at": row.created_at,
        }) for row in checks
    ]
    import_data = [
        _stamp(request_id, "import_batch", row.id, {
            "batch_no": row.batch_no, "file_type": row.file_type, "data_date": row.data_date,
            "export_date": row.export_date, "status": row.status, "total_rows": row.total_rows,
            "success_rows": row.success_rows, "error_rows": row.error_rows,
            "uploaded_at": row.uploaded_at, "created_at": row.created_at, "updated_at": row.updated_at,
        }) for row in imports
    ]
    error_data = [
        _stamp(request_id, "import_error", row.id, {
            "batch_id": row.batch_id, "row_number": row.row_number, "error_type": row.error_type,
            "error_message": row.error_message, "created_at": row.created_at,
        }) for row in import_errors
    ]
    data = ExternalInventoryEvidenceData(
        case=_case_item(case),
        snapshot=_snapshot_payload(snapshot, request_id),
        product=product_data,
        supplier=supplier_data,
        historical_snapshots=[_snapshot_payload(row, request_id) for row in historical],
        inventory_flows=flow_data,
        sales_details=sales_data,
        purchase_details=purchase_data,
        inventory_checks=check_data,
        import_batches=import_data,
        import_errors=error_data,
        data_cutoff_date=case.data_date,
        evidence_version=case.evidence_version,
    )
    audit_external_request(db, request, api_key, f"/inventory/anomalies/{case_id}/evidence", {"count": len(historical) + len(flows) + len(sales) + len(purchases) + len(checks)})
    return ExternalEnvelope(data=data, meta=external_meta(request))


@router.post("/anomalies/{case_id}/diagnoses", response_model=ExternalEnvelope[ExternalInventoryAnomalyItem])
def external_inventory_diagnosis(
    case_id: int,
    payload: ExternalInventoryDiagnosisCreate,
    request: Request,
    api_key: ExternalApiKey = Depends(require_external_permission("can_write_inventory_diagnoses")),
    db: Session = Depends(get_db),
) -> ExternalEnvelope[ExternalInventoryAnomalyItem]:
    sync_inventory_anomaly_cases(db)
    case = _get_case(db, case_id)
    if case.status == "resolved":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Resolved inventory anomaly cannot be diagnosed")
    before = _json_data(serialize_anomaly_case(case))
    case.root_cause = payload.root_cause
    case.confidence = payload.confidence
    case.diagnosis_json = payload.model_dump(mode="json")
    case.recommended_action = payload.recommended_action
    case.expected_result = payload.expected_result
    case.diagnosed_at = utcnow()
    blockers = []
    if payload.root_cause == "insufficient_evidence":
        blockers.append("insufficient_evidence")
    if payload.confidence < Decimal("0.95"):
        blockers.append("confidence_below_0_95")
    case.status = "blocked" if blockers else "diagnosed"
    if blockers:
        ensure_blocked_work_item(db, case, blockers)
    db.flush()
    write_audit_log(
        db,
        action_type="external_inventory_diagnosis",
        resource_type="inventory_anomaly_case",
        resource_id=str(case.id),
        before_data=before,
        after_data=_json_data({**serialize_anomaly_case(case), "api_key_id": api_key.key_id}),
    )
    audit_external_request(db, request, api_key, f"/inventory/anomalies/{case_id}/diagnoses", action_type="external_api_write")
    return ExternalEnvelope(data=_case_item(case), meta=external_meta(request))


@router.post("/actions/validate", response_model=ExternalEnvelope[ExternalInventoryActionValidationData])
def external_inventory_action_validate(
    payload: ExternalInventoryActionValidateRequest,
    request: Request,
    api_key: ExternalApiKey = Depends(require_external_permission("can_validate_inventory_actions")),
    db: Session = Depends(get_db),
) -> ExternalEnvelope[ExternalInventoryActionValidationData]:
    sync_inventory_anomaly_cases(db)
    case = _get_case(db, payload.case_id)
    parameters = payload.parameters
    blockers = remediation_blockers(db, case, payload.action_type, parameters)
    allowed = not blockers
    token = secrets.token_urlsafe(36) if allowed else None
    expires_at = utcnow() + timedelta(seconds=max(30, settings.inventory_agent_validation_ttl_seconds)) if allowed else None
    impact = remediation_impact(case, payload.action_type, parameters)
    action = InventoryRemediationAction(
        action_no=generated_code("INVACT"),
        case_id=case.id,
        requested_by_key_id=api_key.key_id,
        action_type=payload.action_type,
        status="validated" if allowed else "blocked",
        allowed=allowed,
        blockers_json=blockers,
        parameters_json=parameters,
        impact_json=impact,
        evidence_version=case.evidence_version,
        validation_token_hash=hash_external_token(token) if token else None,
        validation_expires_at=expires_at,
        before_data=_json_data(serialize_anomaly_case(case)),
    )
    db.add(action)
    if blockers:
        case.status = "blocked"
        ensure_blocked_work_item(db, case, blockers)
    db.flush()
    write_audit_log(
        db,
        action_type="external_inventory_action_validate",
        resource_type="inventory_remediation_action",
        resource_id=str(action.id),
        after_data={"action_no": action.action_no, "allowed": allowed, "blockers": blockers, "api_key_id": api_key.key_id},
    )
    audit_external_request(db, request, api_key, "/inventory/actions/validate", action_type="external_api_write")
    data = ExternalInventoryActionValidationData(
        action_id=action.id,
        action_no=action.action_no,
        allowed=allowed,
        blockers=blockers,
        impact=impact,
        validation_token=token,
        validation_expires_at=expires_at,
        evidence_version=case.evidence_version,
    )
    return ExternalEnvelope(data=data, meta=external_meta(request))


def _require_execute_permission(api_key: ExternalApiKey, action_type: str) -> None:
    permission = "can_execute_inventory_upstream" if action_type in {
        "reimport_latest_snapshot", "create_upstream_adjustment", "reverse_or_repost_document"
    } else "can_execute_inventory_rebuild"
    if not external_permission_enabled(api_key, permission):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"API key lacks required execution scope for {action_type}")


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


@router.post("/actions", response_model=ExternalEnvelope[ExternalInventoryActionItem])
def external_inventory_action_execute(
    payload: ExternalInventoryActionExecuteRequest,
    request: Request,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=160),
    api_key: ExternalApiKey = Depends(external_key_dependency),
    db: Session = Depends(get_db),
) -> ExternalEnvelope[ExternalInventoryActionItem]:
    existing = db.scalar(select(InventoryRemediationAction).where(InventoryRemediationAction.idempotency_key == idempotency_key))
    if existing is not None:
        if existing.id != payload.action_id or existing.requested_by_key_id != api_key.key_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency key is already used by another action")
        return ExternalEnvelope(data=_action_item(existing), meta=external_meta(request))
    action = _get_action_for_update(db, payload.action_id)
    if action.requested_by_key_id != api_key.key_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory remediation action not found")
    _require_execute_permission(api_key, action.action_type)
    if not action.allowed or action.status != "validated":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Inventory remediation action is not executable")
    if action.validation_expires_at is None or _aware(action.validation_expires_at) <= utcnow():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Inventory remediation validation has expired")
    if not action.validation_token_hash or not secrets.compare_digest(action.validation_token_hash, hash_external_token(payload.validation_token)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid inventory remediation validation token")
    case = _get_case_for_update(db, action.case_id)
    if case.evidence_version != action.evidence_version:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Inventory evidence changed; validate the action again")
    runtime_blockers = remediation_blockers(db, case, action.action_type, action.parameters_json or {})
    if runtime_blockers:
        action.allowed = False
        action.status = "blocked"
        action.blockers_json = runtime_blockers
        action.validation_token_hash = None
        case.status = "blocked"
        ensure_blocked_work_item(db, case, runtime_blockers)
        db.flush()
        write_audit_log(
            db,
            action_type="external_inventory_action_runtime_blocked",
            resource_type="inventory_remediation_action",
            resource_id=str(action.id),
            after_data={"action_no": action.action_no, "blockers": runtime_blockers, "api_key_id": api_key.key_id},
        )
        audit_external_request(db, request, api_key, "/inventory/actions", action_type="external_api_write")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Inventory remediation policy changed; validate the action again")

    action.idempotency_key = idempotency_key
    action.validation_token_hash = None
    action.status = "executing"
    action.started_at = utcnow()
    case.status = "executing"
    db.commit()
    try:
        if action.action_type == "rebuild_inventory_flow":
            result = rebuild_inventory_flow(db, trigger_batch_id=case.batch_id)
        elif action.action_type == "rerun_inventory_check":
            check = db.scalar(
                select(InventoryCheckBatch).order_by(InventoryCheckBatch.created_at.desc(), InventoryCheckBatch.id.desc()).limit(1)
            )
            operator = db.get(User, check.uploaded_by) if check and check.uploaded_by else None
            if check is None or operator is None:
                raise ValueError("Inventory check batch or operator is unavailable")
            rebuild_inventory_check_batch(db, batch=check, user=operator)
            result = {"batch_id": check.id, "batch_no": check.batch_no, "difference_rows": check.difference_rows}
        else:
            raise ValueError("Upstream inventory connector is not configured")
        db.commit()
        sync_inventory_anomaly_cases(db)
        action = _get_action(db, payload.action_id)
        case = _get_case(db, action.case_id)
        resolved = case.status == "resolved"
        action.status = "completed"
        action.result_json = _json_data(result)
        action.verification_json = {
            "resolved": resolved,
            "case_status": case.status,
            "stock_qty": str(case.stock_qty) if case.stock_qty is not None else None,
            "checked_at": utcnow().isoformat(),
        }
        action.compensation_json = {
            "status": "not_required",
            "reason": "The action rebuilds derived data from immutable source records.",
        }
        action.completed_at = utcnow()
        if not resolved:
            case.status = "diagnosed" if case.root_cause else "open"
            ensure_blocked_work_item(db, case, ["verification_not_resolved"])
        db.flush()
        write_audit_log(
            db,
            action_type="external_inventory_action_execute",
            resource_type="inventory_remediation_action",
            resource_id=str(action.id),
            before_data=action.before_data,
            after_data=_json_data({**serialize_remediation_action(action), "api_key_id": api_key.key_id}),
        )
        audit_external_request(db, request, api_key, "/inventory/actions", action_type="external_api_write")
    except Exception as exc:
        db.rollback()
        action = _get_action(db, payload.action_id)
        case = _get_case(db, action.case_id)
        action.status = "failed"
        action.error_message = str(exc)[:2000]
        action.compensation_json = {
            "status": "transaction_rolled_back",
            "reason": "Execution failed before a verified result was committed.",
        }
        action.completed_at = utcnow()
        case.status = "blocked"
        ensure_blocked_work_item(db, case, ["execution_failed"])
        db.flush()
        write_audit_log(
            db,
            action_type="external_inventory_action_failed",
            resource_type="inventory_remediation_action",
            resource_id=str(action.id),
            after_data={"action_no": action.action_no, "error": action.error_message, "api_key_id": api_key.key_id},
        )
        audit_external_request(db, request, api_key, "/inventory/actions", action_type="external_api_write")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Inventory remediation action failed") from exc
    return ExternalEnvelope(data=_action_item(action), meta=external_meta(request))


@router.get("/actions/{action_id}", response_model=ExternalEnvelope[ExternalInventoryActionItem])
def external_inventory_action_detail(
    action_id: int,
    request: Request,
    api_key: ExternalApiKey = Depends(require_external_permission("can_read_inventory_action_status")),
    db: Session = Depends(get_db),
) -> ExternalEnvelope[ExternalInventoryActionItem]:
    action = _get_action(db, action_id)
    if action.requested_by_key_id != api_key.key_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory remediation action not found")
    audit_external_request(db, request, api_key, f"/inventory/actions/{action_id}")
    return ExternalEnvelope(data=_action_item(action), meta=external_meta(request))
