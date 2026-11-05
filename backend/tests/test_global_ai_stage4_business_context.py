from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import Base
from app.models import (
    AccountLedgerEntry,
    ApprovalInstance,
    CustomerMaster,
    DataScopeRule,
    ExceptionCase,
    FieldPermissionRule,
    ImportBatch,
    InventorySnapshot,
    Permission,
    ProductMaster,
    PurchaseDetail,
    Role,
    RolePermission,
    SalesDetail,
    SupplierMaster,
    User,
)
from app.services.global_business_context_service import build_global_business_context_snapshot


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class TestGlobalAiStageFourBusinessContext:
    def setup_method(self) -> None:
        self.previous_flags = (
            settings.exception_ai_data_enabled,
            settings.exception_ai_finance_enabled,
        )
        settings.exception_ai_data_enabled = True
        settings.exception_ai_finance_enabled = True
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.user = User(
            username="global-context-admin",
            password_hash="hash",
            real_name="Global Context Admin",
            role="admin",
            status="active",
            is_active=True,
            employee_code="E-1",
        )
        role = Role(role_code="admin", role_name="Admin")
        permissions = [
            Permission(
                permission_code=code,
                permission_name=code,
                resource_type=code.split(".")[0],
                action_type=code.split(".")[1],
            )
            for code in self.permissions
        ]
        self.db.add_all([self.user, role, *permissions])
        self.db.flush()
        self.db.add_all(
            [RolePermission(role_id=role.id, permission_id=permission.id) for permission in permissions]
        )
        self._seed_business_data()
        self.db.commit()

    def teardown_method(self) -> None:
        self.db.close()
        self.engine.dispose()
        settings.exception_ai_data_enabled, settings.exception_ai_finance_enabled = self.previous_flags

    @property
    def permissions(self) -> list[str]:
        return [
            "crm_insight.view",
            "customer.view",
            "product.view",
            "supplier.view",
            "sales_detail.view",
            "purchase_detail.view",
            "inventory_snapshot.view",
            "account_ledger.view",
            "import.view",
            "approval.view",
            "exception_center.view",
        ]

    def _batch(self, batch_no: str, file_type: str, *, status: str = "committed", error_rows: int = 0) -> ImportBatch:
        batch = ImportBatch(
            batch_no=batch_no,
            file_name=f"{batch_no}.xlsx",
            file_type=file_type,
            data_date=date.today(),
            uploaded_by=self.user.id,
            uploaded_at=datetime.now(timezone.utc),
            status=status,
            total_rows=2,
            success_rows=2 - error_rows,
            error_rows=error_rows,
            raw_file_path=f"/private/{batch_no}.xlsx",
        )
        self.db.add(batch)
        self.db.flush()
        return batch

    def _seed_business_data(self) -> None:
        self.db.add_all(
            [
                CustomerMaster(customer_code="C-ALLOW", customer_name="授权客户", contact_phone="13800138000"),
                CustomerMaster(customer_code="C-DENY", customer_name="未授权客户", contact_phone="13900139000"),
                ProductMaster(product_code="P-1", product_name="合成商品"),
                SupplierMaster(supplier_code="S-1", supplier_name="合成供应商"),
                DataScopeRule(
                    subject_type="user",
                    subject_id=str(self.user.id),
                    resource_type="customer",
                    scope_mode="assigned",
                    scope_value=["C-ALLOW"],
                    is_active=True,
                ),
                DataScopeRule(
                    subject_type="user",
                    subject_id=str(self.user.id),
                    resource_type="sales_detail",
                    scope_mode="assigned",
                    scope_value=["C-ALLOW"],
                    is_active=True,
                ),
                FieldPermissionRule(
                    subject_type="user",
                    subject_id=str(self.user.id),
                    resource_type="sales_detail",
                    field_name="gross_profit",
                    permission_type="hidden",
                ),
                FieldPermissionRule(
                    subject_type="user",
                    subject_id=str(self.user.id),
                    resource_type="account_ledger",
                    field_name="current_balance",
                    permission_type="masked",
                    mask_rule="money",
                ),
            ]
        )
        sales_batch = self._batch("B-SALES", "sales_detail")
        purchase_batch = self._batch("B-PURCHASE", "purchase_detail")
        inventory_batch = self._batch("B-INVENTORY", "inventory_snapshot")
        account_batch = self._batch("B-ACCOUNT", "account_ledger")
        self._batch("B-FAILED", "customer_master", status="partial_error", error_rows=2)
        self.db.add_all(
            [
                SalesDetail(
                    batch_id=sales_batch.id,
                    row_number=1,
                    document_no="SO-ALLOW",
                    document_date=date.today(),
                    customer_code="C-ALLOW",
                    product_code="P-1",
                    sale_qty_base=Decimal("2"),
                    amount_tax_total=Decimal("100"),
                    gross_profit=Decimal("20"),
                ),
                SalesDetail(
                    batch_id=sales_batch.id,
                    row_number=2,
                    document_no="SO-DENY",
                    document_date=date.today(),
                    customer_code="C-DENY",
                    product_code="P-1",
                    sale_qty_base=Decimal("9"),
                    amount_tax_total=Decimal("900"),
                    gross_profit=Decimal("180"),
                ),
                PurchaseDetail(
                    batch_id=purchase_batch.id,
                    row_number=1,
                    document_no="PO-1",
                    document_date=date.today(),
                    supplier_code="S-1",
                    product_code="P-1",
                    purchase_qty_base=Decimal("3"),
                    purchase_amount=Decimal("60"),
                ),
                InventorySnapshot(
                    batch_id=inventory_batch.id,
                    row_number=1,
                    data_date=date.today(),
                    product_code="P-1",
                    warehouse_scope="specific",
                    stock_qty=Decimal("-1"),
                    stock_inventory_qty=Decimal("-1"),
                    locked_base_qty=Decimal("0"),
                    cost_amount=Decimal("10"),
                ),
                AccountLedgerEntry(
                    batch_id=account_batch.id,
                    row_number=1,
                    data_date=date.today(),
                    balance_date=date.today(),
                    settlement_unit_code="C-ALLOW",
                    row_role="closing",
                    current_balance=Decimal("88"),
                    ar_amount=Decimal("88"),
                    ap_amount=Decimal("0"),
                ),
                ApprovalInstance(
                    approval_no="AP-STAGE4-1",
                    approval_type="crm_project_create",
                    resource_type="crm_project",
                    resource_id="1",
                    title="不得进入 AI 上下文的审批标题",
                    applicant_user_id=self.user.id,
                    current_handler_user_id=self.user.id,
                    status="submitted",
                    priority="high",
                ),
                ExceptionCase(
                    case_no="EXC-STAGE4-1",
                    fingerprint="stage4-global-context-exception",
                    domain="inventory",
                    rule_code="inventory.negative_stock",
                    title="不得进入 AI 上下文的案件标题",
                    severity="high",
                    status="open",
                    occurrence_type="new",
                    resource_type="inventory_snapshot",
                    resource_id="1",
                    resource_code="P-1",
                    source_type="inventory_anomaly_case",
                    source_id="1",
                    evidence_version="stage4-v1",
                    reason="不得进入 AI 上下文的案件证据",
                ),
            ]
        )

    def _build(self, permissions: list[str] | None = None):  # noqa: ANN202
        return build_global_business_context_snapshot(
            self.db,
            self.user,
            crm_context={
                "user": {
                    "id": self.user.id,
                    "username": self.user.username,
                    "contact_phone": "13800138000",
                },
                "permission_flags": {"crm_insight.view": True},
                "summary": {"active_projects": 0},
                "projects": [],
                "risky_tasks": [{"id": 7, "status": "blocked"}],
                "open_work_items": [],
            },
            permission_codes=permissions or self.permissions,
            required_permission="crm_insight.view",
        )

    def test_context_is_scoped_redacted_and_traceable(self) -> None:
        snapshot = self._build()
        fields = snapshot.structured_fields

        assert snapshot.domain == "global_business"
        assert snapshot.context_version == "global-business-context.v1"
        assert fields["crm"]["user"]["contact_phone"] == "[REDACTED]"
        assert fields["master_data"]["counts"]["customers"] == 1
        assert fields["sales"]["rows"] == 1
        assert fields["sales"]["amount_tax_total"] == "100.00"
        assert fields["sales"]["gross_profit"] is None
        assert "gross_profit" in fields["sales"]["redacted_metrics"]
        assert fields["purchase"]["rows"] == 1
        assert fields["inventory"]["negative_rows"] == 1
        assert fields["inventory"]["attention"]["needs_attention"] == 1
        assert fields["finance"]["current_balance"] is None
        assert "current_balance" in fields["finance"]["redacted_metrics"]
        assert fields["imports"]["error_batches"] == 1
        assert fields["approvals"]["pending"][0]["id"] > 0
        assert fields["exceptions"]["total"] == 1
        assert fields["exceptions"]["active_cases"][0]["rule_code"] == "inventory.negative_stock"
        assert "crm_task:7" in snapshot.source_refs
        assert any(ref.startswith("import_batch:") for ref in snapshot.source_refs)
        assert any(ref.startswith("approval:") for ref in snapshot.source_refs)
        assert any(ref.startswith("exception_case:") for ref in snapshot.source_refs)

        serialized = str(fields)
        assert "C-DENY" not in serialized
        assert "未授权客户" not in serialized
        assert "不得进入 AI 上下文的审批标题" not in serialized
        assert "不得进入 AI 上下文的案件标题" not in serialized
        assert "不得进入 AI 上下文的案件证据" not in serialized
        assert "/private/" not in serialized
        assert ".xlsx" not in serialized

    def test_feature_flags_remove_data_and_finance_domains(self) -> None:
        settings.exception_ai_data_enabled = False
        settings.exception_ai_finance_enabled = False
        fields = self._build().structured_fields

        for domain in ("master_data", "sales", "purchase", "inventory", "imports", "finance"):
            assert domain not in fields
            assert fields["availability"][domain]["available"] is False
            assert fields["availability"][domain]["reason"].startswith("feature_disabled:")
        assert fields["crm"]["summary"]["active_projects"] == 0
        assert fields["approvals"]["total"] == 1

    def test_missing_domain_permissions_do_not_leak_context(self) -> None:
        snapshot = self._build(["crm_insight.view"])
        fields = snapshot.structured_fields

        assert fields["availability"]["sales"] == {
            "available": False,
            "reason": "missing_permission:sales_detail.view",
        }
        assert fields["availability"]["finance"] == {
            "available": False,
            "reason": "missing_permission:account_ledger.view",
        }
        assert fields["availability"]["approvals"]["available"] is False
        assert "sales" not in fields
        assert "finance" not in fields
        assert "approvals" not in fields
        assert snapshot.source_refs == ["crm_task:7"]

    def test_import_scope_and_derived_metrics_follow_security_rules(self) -> None:
        self.db.add_all(
            [
                DataScopeRule(
                    subject_type="user",
                    subject_id=str(self.user.id),
                    resource_type="import_batch",
                    scope_mode="custom",
                    scope_value={"mode": "none"},
                    is_active=True,
                ),
                FieldPermissionRule(
                    subject_type="user",
                    subject_id=str(self.user.id),
                    resource_type="inventory_snapshot",
                    field_name="stock_qty",
                    permission_type="hidden",
                ),
                FieldPermissionRule(
                    subject_type="user",
                    subject_id=str(self.user.id),
                    resource_type="account_ledger",
                    field_name="ar_amount",
                    permission_type="masked",
                    mask_rule="money",
                ),
            ]
        )
        self.db.commit()

        fields = self._build().structured_fields
        assert fields["imports"]["total"] == 0
        assert fields["imports"]["recent_failures"] == []
        assert fields["inventory"]["stock_qty"] is None
        assert fields["inventory"]["negative_rows"] is None
        assert fields["inventory"]["abnormal_rows"] is None
        assert fields["inventory"]["attention"]["needs_attention"] is None
        assert fields["finance"]["ar_amount"] is None
        assert fields["finance"]["non_zero_ar_rows"] is None
        assert fields["finance"]["attention"]["needs_attention"] is None

    def test_required_assistant_permission_is_enforced(self) -> None:
        with pytest.raises(PermissionError, match="crm_insight.view"):
            self._build(["sales_detail.view"])
