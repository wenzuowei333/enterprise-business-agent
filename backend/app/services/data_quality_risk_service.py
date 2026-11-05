from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    CustomerMaster,
    InventoryCheckBatch,
    InventoryCheckResult,
    MasterLinkIssue,
    ProductMaster,
    ReceivableCheckResult,
    ReceivableSnapshot,
    SupplierMaster,
)


@dataclass
class RiskRuleDefinition:
    rule_code: str
    rule_name: str
    level: str
    category: str
    resource_type: str | None
    scope: str
    description: str
    action: str
    is_enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_code": self.rule_code,
            "rule_name": self.rule_name,
            "level": self.level,
            "category": self.category,
            "resource_type": self.resource_type,
            "scope": self.scope,
            "description": self.description,
            "action": self.action,
            "is_enabled": self.is_enabled,
        }


@dataclass
class RiskAlert:
    rule_code: str
    rule_name: str
    rule_description: str
    status: str
    status_label: str
    closure_hint: str | None
    is_actionable: bool
    level: str
    category: str
    resource_type: str | None
    code: str | None
    name: str | None
    reason: str
    action: str | None = None
    affected_rows: int = 0
    affected_documents: int = 0
    affected_amount: str | None = None
    affected_quantity: str | None = None
    first_seen_date: date | None = None
    last_seen_date: date | None = None
    source: str | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_code": self.rule_code,
            "rule_name": self.rule_name,
            "rule_description": self.rule_description,
            "status": self.status,
            "status_label": self.status_label,
            "closure_hint": self.closure_hint,
            "is_actionable": self.is_actionable,
            "level": self.level,
            "category": self.category,
            "resource_type": self.resource_type,
            "code": self.code,
            "name": self.name,
            "reason": self.reason,
            "action": self.action,
            "affected_rows": self.affected_rows,
            "affected_documents": self.affected_documents,
            "affected_amount": self.affected_amount,
            "affected_quantity": self.affected_quantity,
            "first_seen_date": self.first_seen_date,
            "last_seen_date": self.last_seen_date,
            "source": self.source,
            "metadata": self.metadata or {},
        }


RISK_RULES: dict[str, RiskRuleDefinition] = {
    "master_link.missing_customer": RiskRuleDefinition(
        "master_link.missing_customer",
        "客户档案待补",
        "warning",
        "客户档案待补",
        "customer",
        "销售明细、往来明细等过程数据引用客户时",
        "过程数据引用该客户，但客户档案不存在，会影响客户上下文、销售联动和权限范围判断。",
        "新增客户档案",
    ),
    "master_link.missing_supplier": RiskRuleDefinition(
        "master_link.missing_supplier",
        "供应商档案待补",
        "warning",
        "供应商档案待补",
        "supplier",
        "采购明细、往来明细等过程数据引用供应商时",
        "过程数据引用该供应商，但供应商档案不存在，会影响采购、往来和供应商上下文联动。",
        "新增供应商档案",
    ),
    "master_link.missing_product": RiskRuleDefinition(
        "master_link.missing_product",
        "商品档案待补",
        "warning",
        "商品档案待补",
        "product",
        "销售、采购、库存过程数据引用商品时",
        "过程数据引用该商品，但商品档案不存在，会影响销售、采购、库存联动和核验结果。",
        "新增商品档案",
    ),
    "master_link.missing_settlement_unit": RiskRuleDefinition(
        "master_link.missing_settlement_unit",
        "结算单位待匹配",
        "warning",
        "结算单位待匹配",
        "settlement_unit",
        "往来明细和应收校验涉及结算单位时",
        "往来明细中的结算单位无法匹配主档，会影响往来上下文和应收校验。",
        "补齐客户或供应商档案",
    ),
    "master_link.cross_role_customer": RiskRuleDefinition(
        "master_link.cross_role_customer",
        "客户存在于供应商档案",
        "warning",
        "客户存在于供应商档案",
        "customer",
        "销售客户只在供应商档案中存在时",
        "销售过程数据中的客户只存在于供应商档案，需要补齐客户角色后才能完成销售客户联动。",
        "从供应商复制为客户",
    ),
    "master_link.cross_role_supplier": RiskRuleDefinition(
        "master_link.cross_role_supplier",
        "供应商存在于客户档案",
        "warning",
        "供应商存在于客户档案",
        "supplier",
        "采购供应商只在客户档案中存在时",
        "采购过程数据中的供应商只存在于客户档案，需要补齐供应商角色后才能完成采购供应商联动。",
        "从客户复制为供应商",
    ),
    "master_completeness.customer": RiskRuleDefinition(
        "master_completeness.customer",
        "客户资料不完整",
        "risk",
        "客户资料不完整",
        "customer",
        "客户档案基础字段为空时",
        "客户基础资料缺少当前业务员、联系人、联系电话或地址，会影响后续联系、跟进和责任识别。",
        "补充客户基础资料",
    ),
    "master_completeness.supplier": RiskRuleDefinition(
        "master_completeness.supplier",
        "供应商资料不完整",
        "risk",
        "供应商资料不完整",
        "supplier",
        "供应商档案基础字段为空时",
        "供应商基础资料缺少联系人、联系电话或地址，会影响采购核对和供应商联络。",
        "补充供应商基础资料",
    ),
    "master_completeness.product": RiskRuleDefinition(
        "master_completeness.product",
        "商品资料不完整",
        "risk",
        "商品资料不完整",
        "product",
        "商品档案基础字段为空时",
        "商品基础资料缺少规格、单位或分类，会影响商品查询、库存分层和报表分组。",
        "补充商品基础资料",
    ),
    "check.inventory_missing_product_master": RiskRuleDefinition(
        "check.inventory_missing_product_master",
        "库存核验商品档案待补",
        "warning",
        "库存核验商品档案待补",
        "product",
        "最新一次库存核验上传后",
        "最新库存核验中发现商品不在商品档案，会影响库存核验和商品上下文联动。",
        "新增商品档案",
    ),
    "check.receivable_amount_mismatch": RiskRuleDefinition(
        "check.receivable_amount_mismatch",
        "应收金额不一致",
        "warning",
        "应收金额不一致",
        "settlement_unit",
        "最新一次应收查询表校验后",
        "最新应收校验中，应收查询金额与往来明细应收金额不一致。",
        "核对应收查询表与往来明细",
    ),
    "check.receivable_missing_in_ledger": RiskRuleDefinition(
        "check.receivable_missing_in_ledger",
        "往来明细缺结算单位",
        "warning",
        "往来明细缺结算单位",
        "settlement_unit",
        "最新一次应收查询表校验后",
        "应收查询表存在该结算单位，但往来明细没有对应应收底数。",
        "补齐往来明细底数",
    ),
    "check.receivable_missing_in_query": RiskRuleDefinition(
        "check.receivable_missing_in_query",
        "应收查询缺结算单位",
        "risk",
        "应收查询缺结算单位",
        "settlement_unit",
        "最新一次应收查询表校验后",
        "往来明细存在应收金额，但最新应收查询表没有对应结算单位。",
        "核对应收查询表",
    ),
    "check.receivable_name_mismatch": RiskRuleDefinition(
        "check.receivable_name_mismatch",
        "结算单位名称不一致",
        "risk",
        "结算单位名称不一致",
        "settlement_unit",
        "最新一次应收查询表校验后",
        "结算单位编号一致但名称不一致，可能影响人工核对。",
        "核对结算单位名称",
    ),
    "check.receivable_duplicate_unit": RiskRuleDefinition(
        "check.receivable_duplicate_unit",
        "应收查询结算单位重复",
        "risk",
        "应收查询结算单位重复",
        "settlement_unit",
        "最新一次应收查询表校验后",
        "最新应收查询表中同一结算单位重复出现，需要人工确认。",
        "合并或确认重复单位",
    ),
}

MASTER_LINK_RULE_CODES = {
    "missing_customer": "master_link.missing_customer",
    "missing_supplier": "master_link.missing_supplier",
    "missing_product": "master_link.missing_product",
    "missing_settlement_unit": "master_link.missing_settlement_unit",
    "cross_role_customer_in_supplier": "master_link.cross_role_customer",
    "cross_role_supplier_in_customer": "master_link.cross_role_supplier",
}

INVENTORY_CHECK_RULE_CODES = {
    "missing_product_master": "check.inventory_missing_product_master",
}

RECEIVABLE_CHECK_RULE_CODES = {
    "amount_mismatch": "check.receivable_amount_mismatch",
    "missing_in_ledger": "check.receivable_missing_in_ledger",
    "missing_in_receivable_query": "check.receivable_missing_in_query",
    "unit_name_mismatch": "check.receivable_name_mismatch",
    "duplicate_unit": "check.receivable_duplicate_unit",
}


def build_data_quality_risk_alerts(
    db: Session,
    *,
    level: str | None = None,
    category: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> dict[str, Any]:
    alerts: list[RiskAlert] = []
    alerts.extend(_master_link_alerts(db))
    alerts.extend(_customer_completeness_alerts(db))
    alerts.extend(_supplier_completeness_alerts(db))
    alerts.extend(_product_completeness_alerts(db))
    alerts.extend(_latest_inventory_check_alerts(db))
    alerts.extend(_latest_receivable_check_alerts(db))

    alerts = _sort_alerts(alerts)
    summary = _summary(alerts)
    filtered = alerts
    if level:
        filtered = [item for item in filtered if item.level == level]
    if category:
        filtered = [item for item in filtered if item.category == category]

    safe_limit = max(1, min(limit, 500))
    safe_offset = max(0, offset)
    page = filtered[safe_offset : safe_offset + safe_limit]
    return {
        "items": [item.to_dict() for item in page],
        "total": len(filtered),
        "limit": safe_limit,
        "offset": safe_offset,
        "summary": summary,
    }


def list_data_quality_risk_rules(
    *,
    level: str | None = None,
    category: str | None = None,
    resource_type: str | None = None,
) -> dict[str, Any]:
    rules = list(RISK_RULES.values())
    if level:
        rules = [rule for rule in rules if rule.level == level]
    if category:
        rules = [rule for rule in rules if rule.category == category]
    if resource_type:
        rules = [rule for rule in rules if rule.resource_type == resource_type]
    rules = sorted(rules, key=lambda rule: (_level_rank(rule.level), rule.category, rule.rule_code))
    return {"items": [rule.to_dict() for rule in rules], "total": len(rules)}


def _master_link_alerts(db: Session) -> list[RiskAlert]:
    rows = list(
        db.scalars(
            select(MasterLinkIssue)
            .where(MasterLinkIssue.status == "open")
            .order_by(MasterLinkIssue.amount_total.desc().nullslast(), MasterLinkIssue.updated_at.desc(), MasterLinkIssue.id.desc())
        ).all()
    )
    grouped: dict[tuple[str, str | None, str | None], dict[str, Any]] = {}
    for row in rows:
        key = (row.issue_type, row.reference_code, row.reference_name)
        current = grouped.setdefault(
            key,
            {
                "row": row,
                "affected_rows": 0,
                "affected_documents": 0,
                "amount_total": Decimal("0"),
                "quantity_total": Decimal("0"),
                "first_seen_date": row.first_seen_date,
                "last_seen_date": row.last_seen_date,
                "issue_ids": [],
                "source_file_types": set(),
            },
        )
        current["affected_rows"] += row.affected_rows or 0
        current["affected_documents"] += row.affected_documents or 0
        current["amount_total"] += row.amount_total or Decimal("0")
        current["quantity_total"] += row.quantity_total or Decimal("0")
        current["issue_ids"].append(row.id)
        current["source_file_types"].add(row.source_file_type)
        if row.first_seen_date and (current["first_seen_date"] is None or row.first_seen_date < current["first_seen_date"]):
            current["first_seen_date"] = row.first_seen_date
        if row.last_seen_date and (current["last_seen_date"] is None or row.last_seen_date > current["last_seen_date"]):
            current["last_seen_date"] = row.last_seen_date

    alerts: list[RiskAlert] = []
    for values in grouped.values():
        row = values["row"]
        if _master_reference_exists(db, row.expected_master_kind, row.reference_code, row.reference_name):
            continue
        rule_code = MASTER_LINK_RULE_CODES.get(row.issue_type, "master_link.missing_settlement_unit")
        rule = _risk_rule(rule_code)
        alerts.append(
            RiskAlert(
                rule_code=rule.rule_code,
                rule_name=rule.rule_name,
                rule_description=rule.description,
                status="open",
                status_label="待处理",
                closure_hint="补齐对应主档后自动关闭；也可在确认不影响业务后忽略关闭。",
                is_actionable=True,
                level=rule.level,
                category=rule.category,
                resource_type=rule.resource_type,
                code=row.reference_code,
                name=row.reference_name,
                reason=rule.description,
                action=rule.action,
                affected_rows=values["affected_rows"],
                affected_documents=values["affected_documents"],
                affected_amount=_format_decimal(values["amount_total"]),
                affected_quantity=_format_decimal(values["quantity_total"]),
                first_seen_date=values["first_seen_date"],
                last_seen_date=values["last_seen_date"],
                source="master_link_issue",
                metadata={
                    "issue_ids": values["issue_ids"],
                    "issue_type": row.issue_type,
                    "source_file_types": sorted(values["source_file_types"]),
                    "counterpart_master_kind": row.counterpart_master_kind,
                    "counterpart_code": row.counterpart_code,
                    "counterpart_name": row.counterpart_name,
                },
            )
        )
    return alerts


def _customer_completeness_alerts(db: Session) -> list[RiskAlert]:
    rows = list(db.scalars(select(CustomerMaster).order_by(CustomerMaster.customer_code)).all())
    alerts: list[RiskAlert] = []
    rule = _risk_rule("master_completeness.customer")
    for row in rows:
        missing = _missing_fields(
            [
                ("当前业务员", row.salesperson_name or row.salesperson_employee_code),
                ("联系人", row.contact_name),
                ("联系电话", row.contact_phone),
                ("地址", row.address),
            ]
        )
        if not missing:
            continue
        alerts.append(
            RiskAlert(
                rule_code=rule.rule_code,
                rule_name=rule.rule_name,
                rule_description=rule.description,
                status="open",
                status_label="待补充",
                closure_hint="补齐客户基础资料后自动关闭。",
                is_actionable=True,
                level=rule.level,
                category=rule.category,
                resource_type=rule.resource_type,
                code=row.customer_code,
                name=row.customer_name,
                reason=f"客户基础资料缺少：{'、'.join(missing)}。",
                action=rule.action,
                source="customer_master",
                metadata={"missing_fields": missing, "status": row.status, "source": row.source},
            )
        )
    return alerts


def _supplier_completeness_alerts(db: Session) -> list[RiskAlert]:
    rows = list(db.scalars(select(SupplierMaster).order_by(SupplierMaster.supplier_code)).all())
    alerts: list[RiskAlert] = []
    rule = _risk_rule("master_completeness.supplier")
    for row in rows:
        missing = _missing_fields(
            [
                ("联系人", row.contact_name),
                ("联系电话", row.contact_phone),
                ("地址", row.address),
            ]
        )
        if not missing:
            continue
        alerts.append(
            RiskAlert(
                rule_code=rule.rule_code,
                rule_name=rule.rule_name,
                rule_description=rule.description,
                status="open",
                status_label="待补充",
                closure_hint="补齐供应商基础资料后自动关闭。",
                is_actionable=True,
                level=rule.level,
                category=rule.category,
                resource_type=rule.resource_type,
                code=row.supplier_code,
                name=row.supplier_name,
                reason=f"供应商基础资料缺少：{'、'.join(missing)}。",
                action=rule.action,
                source="supplier_master",
                metadata={"missing_fields": missing, "status": row.status, "source": row.source},
            )
        )
    return alerts


def _product_completeness_alerts(db: Session) -> list[RiskAlert]:
    rows = list(db.scalars(select(ProductMaster).order_by(ProductMaster.product_code)).all())
    alerts: list[RiskAlert] = []
    rule = _risk_rule("master_completeness.product")
    for row in rows:
        missing = _missing_fields(
            [
                ("规格", row.spec),
                ("单位", row.unit),
                ("分类", row.category),
            ]
        )
        if not missing:
            continue
        alerts.append(
            RiskAlert(
                rule_code=rule.rule_code,
                rule_name=rule.rule_name,
                rule_description=rule.description,
                status="open",
                status_label="待补充",
                closure_hint="补齐商品基础资料后自动关闭。",
                is_actionable=True,
                level=rule.level,
                category=rule.category,
                resource_type=rule.resource_type,
                code=row.product_code,
                name=row.product_name,
                reason=f"商品基础资料缺少：{'、'.join(missing)}。",
                action=rule.action,
                source="product_master",
                metadata={"missing_fields": missing, "status": row.status, "source": row.source},
            )
        )
    return alerts


def _latest_inventory_check_alerts(db: Session) -> list[RiskAlert]:
    latest_batch = db.scalar(select(InventoryCheckBatch).order_by(InventoryCheckBatch.id.desc()).limit(1))
    if latest_batch is None:
        return []
    rows = list(
        db.scalars(
            select(InventoryCheckResult)
            .where(
                InventoryCheckResult.batch_id == latest_batch.id,
                InventoryCheckResult.result_type.in_(INVENTORY_CHECK_RULE_CODES.keys()),
            )
            .order_by(InventoryCheckResult.result_type, InventoryCheckResult.product_code, InventoryCheckResult.id)
        ).all()
    )
    alerts: list[RiskAlert] = []
    for row in rows:
        if row.product_code and db.scalar(select(ProductMaster.id).where(ProductMaster.product_code == row.product_code).limit(1)):
            continue
        rule = _risk_rule(INVENTORY_CHECK_RULE_CODES[row.result_type])
        alerts.append(
            RiskAlert(
                rule_code=rule.rule_code,
                rule_name=rule.rule_name,
                rule_description=rule.description,
                status="open",
                status_label="待处理",
                closure_hint="新增商品档案后自动关闭；该提示只基于最新一次库存核验。",
                is_actionable=True,
                level=rule.level,
                category=rule.category,
                resource_type=rule.resource_type,
                code=row.product_code,
                name=row.product_name,
                reason=rule.description,
                action=rule.action,
                affected_rows=len(row.source_row_numbers or []) or 1,
                affected_quantity=_format_decimal(row.diff_qty),
                first_seen_date=latest_batch.data_date,
                last_seen_date=latest_batch.data_date,
                source="latest_inventory_check",
                metadata={
                    "batch_id": latest_batch.id,
                    "batch_no": latest_batch.batch_no,
                    "file_name": latest_batch.file_name,
                    "result_type": row.result_type,
                    "warehouse_name": row.warehouse_name,
                    "platform_stock_qty": _format_decimal(row.platform_stock_qty),
                    "system_stock_qty": _format_decimal(row.system_stock_qty),
                    "system_data_date": row.system_data_date.isoformat() if row.system_data_date else None,
                },
            )
        )
    return alerts


def _latest_receivable_check_alerts(db: Session) -> list[RiskAlert]:
    latest_snapshot_batch_id = db.scalar(select(ReceivableSnapshot.batch_id).order_by(ReceivableSnapshot.id.desc()).limit(1))
    if latest_snapshot_batch_id is None:
        return []
    rows = list(
        db.scalars(
            select(ReceivableCheckResult)
            .where(
                ReceivableCheckResult.batch_id == latest_snapshot_batch_id,
                ReceivableCheckResult.result_type.in_(RECEIVABLE_CHECK_RULE_CODES.keys()),
            )
            .order_by(ReceivableCheckResult.result_type, ReceivableCheckResult.customer_code, ReceivableCheckResult.id)
        ).all()
    )
    alerts: list[RiskAlert] = []
    for row in rows:
        rule = _risk_rule(RECEIVABLE_CHECK_RULE_CODES[row.result_type])
        alerts.append(
            RiskAlert(
                rule_code=rule.rule_code,
                rule_name=rule.rule_name,
                rule_description=rule.description,
                status="open",
                status_label="待核对",
                closure_hint="重新上传应收查询表或修正往来明细底数后，重新校验自动刷新状态。",
                is_actionable=True,
                level=rule.level,
                category=rule.category,
                resource_type=rule.resource_type,
                code=row.customer_code or row.matched_customer_code,
                name=row.customer_name or row.matched_customer_name,
                reason=row.message or rule.description,
                action=rule.action,
                affected_rows=1,
                affected_amount=_format_decimal(row.diff_amount),
                first_seen_date=row.data_date,
                last_seen_date=row.data_date,
                source="latest_receivable_check",
                metadata={
                    "batch_id": row.batch_id,
                    "result_type": row.result_type,
                    "severity": row.severity,
                    "receivable_ar_balance": _format_decimal(row.receivable_ar_balance),
                    "account_ar_balance": _format_decimal(row.account_ar_balance),
                },
            )
        )
    return alerts


def _summary(alerts: list[RiskAlert]) -> dict[str, Any]:
    levels = Counter(item.level for item in alerts)
    categories = Counter(item.category for item in alerts)
    rules = Counter(item.rule_code for item in alerts)
    return {
        "warning_count": int(levels.get("warning", 0)),
        "risk_count": int(levels.get("risk", 0)),
        "total": len(alerts),
        "categories": dict(categories),
        "rules": dict(rules),
    }


def _sort_alerts(alerts: list[RiskAlert]) -> list[RiskAlert]:
    source_rank = {"master_link_issue": 0, "latest_inventory_check": 1, "latest_receivable_check": 2}
    return sorted(
        alerts,
        key=lambda item: (
            _level_rank(item.level),
            source_rank.get(item.source or "", 5),
            item.category,
            item.rule_code,
            item.code or "",
            item.name or "",
        ),
    )


def _risk_rule(rule_code: str) -> RiskRuleDefinition:
    return RISK_RULES[rule_code]


def _level_rank(level: str) -> int:
    return {"warning": 0, "risk": 1}.get(level, 9)


def _missing_fields(fields: list[tuple[str, Any]]) -> list[str]:
    return [label for label, value in fields if _is_blank(value)]


def _master_reference_exists(db: Session, expected_master_kind: str, code: str | None, name: str | None) -> bool:
    if expected_master_kind == "products":
        stmt = select(ProductMaster.id)
        if code:
            stmt = stmt.where(ProductMaster.product_code == code)
        elif name:
            stmt = stmt.where(ProductMaster.product_name == name)
        else:
            return False
        return db.scalar(stmt.limit(1)) is not None
    if expected_master_kind == "customers":
        stmt = select(CustomerMaster.id)
        if code:
            stmt = stmt.where(CustomerMaster.customer_code == code)
        elif name:
            stmt = stmt.where(CustomerMaster.customer_name == name)
        else:
            return False
        return db.scalar(stmt.limit(1)) is not None
    if expected_master_kind == "suppliers":
        stmt = select(SupplierMaster.id)
        if code:
            stmt = stmt.where(SupplierMaster.supplier_code == code)
        elif name:
            stmt = stmt.where(SupplierMaster.supplier_name == name)
        else:
            return False
        return db.scalar(stmt.limit(1)) is not None
    return False


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        text = value.strip()
        return text == "" or text in {"-", "无", "未填写", "None", "null"}
    return False


def _format_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    normalized = value.normalize()
    return format(normalized, "f")
