import io
import tempfile
import unittest
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.api.routes.external_api_v2_operations import _customer_item
from app.api.routes.fulfillment import download_delivery_attachment, import_orders, router as fulfillment_router, upload_delivery_attachment
from app.core.config import settings
from app.core.database import Base
from app.customer_tag_catalog import CUSTOMER_TAG_GROUPS, FORMAL_CUSTOMER_TAGS
from app.models import (
    CustomerMaster,
    CustomerTag,
    CustomerTagAssignment,
    CustomerTagCatalogVersion,
    CustomerTagChangeItem,
    CustomerTagGovernanceSettings,
    CustomerTagRecommendation,
    ImportBatch,
    SalesDetail,
    SalesOrderRequirementSnapshot,
    User,
)
from app.schemas.customer_tagging import CustomerTagChangeItemCreate, CustomerTagChangeRequestCreate
from app.schemas.fulfillment import DeliveryEventCreate, SalesOrderCreate
from app.services.customer_tagging_service import (
    activate_catalog_version,
    activate_rule_version,
    create_catalog_definition,
    create_catalog_version,
    create_rule_version,
    generate_purchase_recommendations,
    external_customer_tag_profile,
    review_change_request,
    schedule_catalog_replacement,
    submit_change_request,
    supplement_change_request,
    validate_request_items,
)
from app.services.fulfillment_service import (
    apply_delivery_event,
    cancel_order,
    confirm_order,
    create_order,
    refresh_order_requirements,
    requirement_diff,
    serialize_delivery,
    serialize_order,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class StructuredCustomerTagsFulfillmentTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.applicant = User(
            username="tag-applicant",
            password_hash="hash",
            real_name="标签提交人",
            role="salesperson",
            status="active",
            is_active=True,
        )
        self.reviewer = User(
            username="tag-reviewer",
            password_hash="hash",
            real_name="标签审核人",
            role="manager",
            status="active",
            is_active=True,
        )
        self.customer = CustomerMaster(
            customer_code="C-TAG-001",
            customer_name="结构化标签客户",
            customer_tags=["城市配送"],
            customer_type="历史分类",
            address="测试配送地址",
            status="active",
        )
        self.db.add_all([self.applicant, self.reviewer, self.customer])
        self.db.flush()
        self.settings = CustomerTagGovernanceSettings(
            settings_key="default",
            default_reviewer_user_id=self.reviewer.id,
            tag_workflow_enabled=True,
            recommendation_enabled=True,
            fulfillment_enabled=True,
        )
        self.db.add(self.settings)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _tag(
        self,
        *,
        code: str,
        name: str,
        category: str,
        group: str | None = None,
        mutex: str | None = None,
        temporary: bool = False,
    ) -> CustomerTag:
        tag = CustomerTag(
            name=name,
            normalized_name=name.casefold(),
            color_key="blue",
            is_active=True,
            stable_code=code,
            category_key=category,
            category_name={
                "classification": "客户分类",
                "product_opportunity": "产品机会",
                "purchase_characteristic": "采购特征",
                "delivery_requirement": "配送需求",
            }[category],
            group_code=group,
            group_name=group,
            sort_order=1,
            selection_rule="single" if category == "classification" else "multi",
            mutual_exclusion_key=mutex,
            applicability_json={"attribute_types": ["long_term", *(["temporary"] if temporary else [])]},
            is_formal=True,
        )
        self.db.add(tag)
        self.db.flush()
        return tag

    def test_confirmed_catalog_contains_four_categories_fifteen_groups_and_152_stable_tags(self):
        counts = Counter(str(row["category_key"]) for row in FORMAL_CUSTOMER_TAGS)
        self.assertEqual(
            counts,
            {
                "classification": 10,
                "product_opportunity": 33,
                "purchase_characteristic": 45,
                "delivery_requirement": 64,
            },
        )
        self.assertEqual(len(CUSTOMER_TAG_GROUPS), 15)
        self.assertEqual(len(FORMAL_CUSTOMER_TAGS), 152)
        self.assertEqual(len({str(row["stable_code"]) for row in FORMAL_CUSTOMER_TAGS}), 152)

    def test_catalog_version_activation_only_retires_explicit_replacements(self):
        base_version = CustomerTagCatalogVersion(
            version_code="2026.07",
            name="现行目录",
            status="active",
            activated_at=datetime.now(timezone.utc),
        )
        self.db.add(base_version)
        self.db.flush()
        replaced = self._tag(code="CLASS-OLD", name="旧分类", category="classification")
        retained = self._tag(code="DEL-KEEP", name="保留配送", category="delivery_requirement", group="delivery-time")
        replaced.catalog_version_id = base_version.id
        retained.catalog_version_id = base_version.id

        draft = create_catalog_version(
            self.db,
            version_code="2026.08",
            name="八月增量目录",
            description="替换旧分类并新增定义",
            operator=self.reviewer,
        )
        replacement = create_catalog_definition(
            self.db,
            version=draft,
            values={
                "stable_code": "CLASS-NEW",
                "name": "新分类",
                "color_key": "green",
                "category_key": "classification",
                "category_name": "客户分类",
                "group_code": None,
                "group_name": None,
                "sort_order": 1,
                "selection_rule": "single",
                "mutual_exclusion_key": None,
                "attribute_types": ["long_term"],
            },
            operator=self.reviewer,
        )
        schedule_catalog_replacement(
            self.db,
            current=replaced,
            replacement=replacement,
            operator=self.reviewer,
        )
        activate_catalog_version(self.db, version=draft, operator=self.reviewer)
        self.db.commit()
        self.assertEqual(base_version.status, "retired")
        self.assertEqual(draft.status, "active")
        self.assertFalse(replaced.is_active)
        self.assertTrue(replacement.is_active)
        self.assertTrue(retained.is_active)
        self.assertEqual(external_customer_tag_profile(self.db, self.customer)["catalog_version"], "2026.08")

    def test_request_validation_enforces_classification_primary_mutex_and_temporary_binding(self):
        class_a = self._tag(code="CLASS-A", name="分类A", category="classification")
        class_b = self._tag(code="CLASS-B", name="分类B", category="classification")
        purchase_a = self._tag(code="PUR-A", name="采购A", category="purchase_characteristic", group="purchase-cycle")
        purchase_b = self._tag(code="PUR-B", name="采购B", category="purchase_characteristic", group="purchase-cycle")
        delivery_a = self._tag(code="DEL-A", name="配送A", category="delivery_requirement", mutex="delivery-speed")
        delivery_b = self._tag(code="DEL-B", name="配送B", category="delivery_requirement", mutex="delivery-speed")
        temporary = self._tag(code="DEL-TEMP", name="加急配送", category="delivery_requirement", group="delivery-time", temporary=True)
        opportunity = self._tag(code="OPP-A", name="产品机会A", category="product_opportunity", group="product-category")

        def item(tag: CustomerTag, **changes):
            values = {"action": "add", "tag_id": tag.id, "evidence": "客户已确认"}
            if tag.category_key == "purchase_characteristic":
                values["details_json"] = {
                    "statistics_start": date.today().isoformat(),
                    "statistics_end": date.today().isoformat(),
                    "order_count": 3,
                    "average_purchase_interval_days": 7,
                    "average_order_quantity": 10,
                    "manual_result": tag.name,
                }
            values.update(changes)
            return CustomerTagChangeItemCreate(**values)

        with self.assertRaises(HTTPException) as classification_error:
            validate_request_items(self.db, self.customer.customer_code, [item(class_a), item(class_b)])
        self.assertEqual(classification_error.exception.status_code, 409)

        with self.assertRaises(HTTPException) as primary_error:
            validate_request_items(
                self.db,
                self.customer.customer_code,
                [
                    item(purchase_a, is_primary=True, review_date=date.today() + timedelta(days=30)),
                    item(purchase_b, is_primary=True, review_date=date.today() + timedelta(days=30)),
                ],
            )
        self.assertEqual(primary_error.exception.status_code, 409)

        with self.assertRaises(HTTPException) as mutex_error:
            validate_request_items(self.db, self.customer.customer_code, [item(delivery_a), item(delivery_b)])
        self.assertEqual(mutex_error.exception.status_code, 409)

        with self.assertRaises(HTTPException) as binding_error:
            validate_request_items(
                self.db,
                self.customer.customer_code,
                [item(temporary, attribute_type="temporary")],
            )
        self.assertEqual(binding_error.exception.status_code, 400)
        validate_request_items(
            self.db,
            self.customer.customer_code,
            [item(temporary, attribute_type="temporary", details_json={"order_no": "SO-001"})],
        )

        with self.assertRaises(HTTPException) as opportunity_error:
            validate_request_items(
                self.db,
                self.customer.customer_code,
                [item(opportunity, owner_user_id=self.applicant.id, review_date=date.today() + timedelta(days=30))],
            )
        self.assertEqual(opportunity_error.exception.status_code, 400)
        validate_request_items(
            self.db,
            self.customer.customer_code,
            [
                item(
                    opportunity,
                    owner_user_id=self.applicant.id,
                    review_date=date.today() + timedelta(days=30),
                    details_json={
                        "product_category": "食品",
                        "product_name": "测试商品",
                        "opportunity_note": "客户有采购意向",
                        "next_action": "寄送样品",
                        "plan_date": date.today().isoformat(),
                        "opportunity_status": "pending",
                    },
                )
            ],
        )

    def test_item_level_review_supplement_and_compatibility_cache(self):
        classification = self._tag(code="CLASS-001", name="餐饮终端客户", category="classification")
        delivery = self._tag(code="DEL-001", name="普通配送", category="delivery_requirement", group="receipt-method")
        request_row = submit_change_request(
            self.db,
            payload=CustomerTagChangeRequestCreate(
                customer_code=self.customer.customer_code,
                reason="补齐客户标签画像",
                items=[
                    {"action": "add", "tag_id": classification.id, "evidence": "客户为餐饮终端"},
                    {"action": "add", "tag_id": delivery.id, "evidence": "待补充配送依据"},
                ],
            ),
            applicant=self.applicant,
        )
        self.db.flush()
        items = list(
            self.db.scalars(
                select(CustomerTagChangeItem)
                .where(CustomerTagChangeItem.request_id == request_row.id)
                .order_by(CustomerTagChangeItem.id)
            ).all()
        )
        review_change_request(
            self.db,
            request_row=request_row,
            decisions=[
                {"item_id": items[0].id, "decision": "approved", "comment": "分类依据充足"},
                {"item_id": items[1].id, "decision": "need_supplement", "comment": "补充客户确认记录"},
            ],
            reviewer=self.reviewer,
        )
        self.db.flush()
        self.assertEqual(request_row.status, "need_supplement")
        self.assertEqual(self.customer.customer_type, classification.name)
        self.assertIn(classification.name, self.customer.customer_tags)
        self.assertNotIn(delivery.name, self.customer.customer_tags)

        supplement_change_request(
            self.db,
            request_row=request_row,
            updates=[{"item_id": items[1].id, "evidence": "客户签字确认普通配送"}],
            applicant=self.applicant,
        )
        review_change_request(
            self.db,
            request_row=request_row,
            decisions=[{"item_id": items[1].id, "decision": "approved", "comment": "依据已补齐"}],
            reviewer=self.reviewer,
        )
        self.db.commit()
        self.assertEqual(request_row.status, "completed")
        self.assertIn(delivery.name, self.customer.customer_tags)
        self.assertEqual(
            len(
                self.db.scalars(
                    select(CustomerTagAssignment).where(
                        CustomerTagAssignment.customer_code == self.customer.customer_code,
                        CustomerTagAssignment.status == "effective",
                    )
                ).all()
            ),
            2,
        )
        classification_assignment = self.db.scalar(
            select(CustomerTagAssignment).where(
                CustomerTagAssignment.customer_code == self.customer.customer_code,
                CustomerTagAssignment.tag_id == classification.id,
                CustomerTagAssignment.status == "effective",
            )
        )
        cancel_request = submit_change_request(
            self.db,
            payload=CustomerTagChangeRequestCreate(
                customer_code=self.customer.customer_code,
                reason="分类已不再适用",
                items=[
                    {
                        "action": "cancel",
                        "assignment_id": classification_assignment.id,
                        "tag_id": classification.id,
                        "evidence": "客户分类发生变化",
                    }
                ],
            ),
            applicant=self.applicant,
        )
        self.db.flush()
        cancel_item = self.db.scalar(
            select(CustomerTagChangeItem).where(CustomerTagChangeItem.request_id == cancel_request.id)
        )
        review_change_request(
            self.db,
            request_row=cancel_request,
            decisions=[{"item_id": cancel_item.id, "decision": "approved"}],
            reviewer=self.reviewer,
        )
        self.db.commit()
        self.assertNotIn(classification.name, self.customer.customer_tags)
        self.assertIsNone(self.customer.customer_type)

    def test_terminal_product_opportunity_is_history_only(self):
        opportunity = self._tag(
            code="OPP-WON",
            name="已成交产品机会",
            category="product_opportunity",
            group="product-category",
        )
        request_row = submit_change_request(
            self.db,
            payload=CustomerTagChangeRequestCreate(
                customer_code=self.customer.customer_code,
                items=[
                    {
                        "action": "add",
                        "tag_id": opportunity.id,
                        "evidence": "客户已下单",
                        "review_date": date.today() + timedelta(days=30),
                        "owner_user_id": self.applicant.id,
                        "details_json": {
                            "product_category": "食品",
                            "product_name": "测试商品",
                            "opportunity_note": "机会已转订单",
                            "next_action": "转入履约",
                            "plan_date": date.today().isoformat(),
                            "opportunity_status": "won",
                        },
                    }
                ],
            ),
            applicant=self.applicant,
        )
        self.db.flush()
        item = self.db.scalar(
            select(CustomerTagChangeItem).where(CustomerTagChangeItem.request_id == request_row.id)
        )
        review_change_request(
            self.db,
            request_row=request_row,
            decisions=[{"item_id": item.id, "decision": "approved"}],
            reviewer=self.reviewer,
        )
        self.db.commit()
        assignment = self.db.scalar(
            select(CustomerTagAssignment).where(CustomerTagAssignment.source_request_item_id == item.id)
        )
        self.assertEqual(assignment.status, "expired")
        self.assertIsNotNone(assignment.ended_at)
        self.assertNotIn(opportunity.name, self.customer.customer_tags)

    def test_order_requirement_snapshot_is_immutable_refreshable_and_drives_delivery(self):
        delivery_tag = self._tag(code="DEL-WINDOW", name="早间配送", category="delivery_requirement", group="delivery-time")
        assignment = CustomerTagAssignment(
            customer_code=self.customer.customer_code,
            tag_id=delivery_tag.id,
            attribute_type="long_term",
            source="customer_confirmed",
            evidence="客户确认早间收货",
            effective_date=date.today(),
            status="effective",
            details_json={"time_window": "08:00-10:00"},
        )
        self.db.add(assignment)
        self.db.flush()
        order = create_order(
            self.db,
            payload=SalesOrderCreate(
                customer_code=self.customer.customer_code,
                delivery_address="仓库北门",
                lines=[{"product_name": "测试商品", "quantity": Decimal("2")}],
            ),
            operator=self.applicant,
        )
        delivery = confirm_order(self.db, order=order, operator=self.applicant)
        self.db.flush()
        first_snapshot = self.db.scalar(
            select(SalesOrderRequirementSnapshot).where(
                SalesOrderRequirementSnapshot.order_id == order.id,
                SalesOrderRequirementSnapshot.snapshot_version == 1,
            )
        )
        self.assertEqual(first_snapshot.requirement_json, {"time_window": "08:00-10:00"})

        assignment.details_json = {"time_window": "09:00-11:00"}
        self.db.flush()
        diff = requirement_diff(self.db, order)
        self.assertEqual(len(diff["changed"]), 1)
        self.assertEqual(first_snapshot.requirement_json, {"time_window": "08:00-10:00"})
        refresh_order_requirements(self.db, order=order, operator=self.applicant)
        self.db.flush()
        second_snapshot = self.db.scalar(
            select(SalesOrderRequirementSnapshot).where(
                SalesOrderRequirementSnapshot.order_id == order.id,
                SalesOrderRequirementSnapshot.snapshot_version == 2,
            )
        )
        self.assertEqual(second_snapshot.requirement_json, {"time_window": "09:00-11:00"})
        self.assertEqual(first_snapshot.requirement_json, {"time_window": "08:00-10:00"})

        apply_delivery_event(
            self.db,
            delivery=delivery,
            payload=DeliveryEventCreate(event_type="dispatch", to_status="delivering"),
            operator=self.applicant,
        )
        apply_delivery_event(
            self.db,
            delivery=delivery,
            payload=DeliveryEventCreate(event_type="sign", to_status="delivered", signed_by="王经理"),
            operator=self.applicant,
        )
        self.assertEqual(delivery.status, "delivered")
        self.assertEqual(delivery.signed_by, "王经理")
        self.assertEqual(order.status, "completed")
        order_payload = serialize_order(self.db, order)
        delivery_payload = serialize_delivery(self.db, delivery)
        self.assertIsInstance(order_payload["lines"][0], dict)
        self.assertIsInstance(order_payload["requirements"][0], dict)
        self.assertIsInstance(delivery_payload["events"][0], dict)

    def test_order_can_only_be_cancelled_before_dispatch(self):
        draft = create_order(
            self.db,
            payload=SalesOrderCreate(
                customer_code=self.customer.customer_code,
                delivery_address="仓库北门",
                lines=[{"product_name": "测试商品", "quantity": Decimal("1")}],
            ),
            operator=self.applicant,
        )
        cancel_order(self.db, order=draft, operator=self.applicant, reason="客户撤销")
        self.assertEqual(draft.status, "cancelled")
        self.assertIsNotNone(draft.cancelled_at)

        confirmed = create_order(
            self.db,
            payload=SalesOrderCreate(
                customer_code=self.customer.customer_code,
                delivery_address="仓库南门",
                lines=[{"product_name": "测试商品", "quantity": Decimal("1")}],
            ),
            operator=self.applicant,
        )
        delivery = confirm_order(self.db, order=confirmed, operator=self.applicant)
        cancel_order(self.db, order=confirmed, operator=self.applicant, reason="配送前取消")
        self.assertEqual(confirmed.status, "cancelled")
        self.assertEqual(delivery.status, "cancelled")

        dispatched = create_order(
            self.db,
            payload=SalesOrderCreate(
                customer_code=self.customer.customer_code,
                delivery_address="仓库西门",
                lines=[{"product_name": "测试商品", "quantity": Decimal("1")}],
            ),
            operator=self.applicant,
        )
        active_delivery = confirm_order(self.db, order=dispatched, operator=self.applicant)
        apply_delivery_event(
            self.db,
            delivery=active_delivery,
            payload=DeliveryEventCreate(event_type="dispatch", to_status="delivering"),
            operator=self.applicant,
        )
        with self.assertRaises(HTTPException) as conflict:
            cancel_order(self.db, order=dispatched, operator=self.applicant, reason="发车后取消")
        self.assertEqual(conflict.exception.status_code, 409)

    def test_excel_import_and_delivery_attachment_round_trip(self):
        route_paths = [route.path for route in fulfillment_router.routes]
        self.assertLess(route_paths.index("/fulfillment/orders/import"), route_paths.index("/fulfillment/orders/{order_id}"))
        workbook = io.BytesIO()
        pd.DataFrame(
            [
                {"外部订单号": "EXT-IMPORT-1", "客户编号": self.customer.customer_code, "配送地址": "导入地址", "商品名称": "商品A", "数量": 2},
                {"外部订单号": "EXT-IMPORT-1", "客户编号": self.customer.customer_code, "配送地址": "导入地址", "商品名称": "商品B", "数量": 3},
            ]
        ).to_excel(workbook, index=False)
        workbook.seek(0)
        result = import_orders(
            request=None,
            file=UploadFile(file=workbook, filename="orders.xlsx"),
            db=self.db,
            current_user=self.applicant,
        )
        self.assertEqual(result.imported_orders, 1)
        self.assertEqual(result.imported_lines, 2)
        self.assertEqual(result.errors, [])

        order = create_order(
            self.db,
            payload=SalesOrderCreate(
                customer_code=self.customer.customer_code,
                delivery_address="附件测试地址",
                lines=[{"product_name": "测试商品", "quantity": Decimal("1")}],
            ),
            operator=self.applicant,
        )
        delivery = confirm_order(self.db, order=order, operator=self.applicant)
        self.db.commit()
        with tempfile.TemporaryDirectory() as upload_root, patch.object(settings, "upload_root", upload_root):
            uploaded = upload_delivery_attachment(
                delivery.id,
                file=UploadFile(file=io.BytesIO(b"delivery proof"), filename="proof.txt"),
                db=self.db,
                current_user=self.applicant,
            )
            response = download_delivery_attachment(
                delivery.id,
                uploaded.id,
                db=self.db,
                current_user=self.applicant,
            )
            self.assertEqual(Path(response.path).read_bytes(), b"delivery proof")
            self.assertEqual(response.filename, "proof.txt")
            payload = serialize_delivery(self.db, delivery)
            self.assertEqual(payload["attachments"][0]["file_name"], "proof.txt")
            self.assertIsInstance(payload["attachments"][0], dict)

    def test_temporary_requirement_conflict_and_external_profile_opt_in(self):
        long_term = self._tag(
            code="DEL-ADDRESS-LONG",
            name="单一地址配送",
            category="delivery_requirement",
            group="delivery-address",
            mutex="delivery-address-count",
        )
        temporary = self._tag(
            code="DEL-ADDRESS-TEMP",
            name="临时地址配送",
            category="delivery_requirement",
            group="delivery-address",
            mutex="delivery-address-count",
            temporary=True,
        )
        self.db.add(
            CustomerTagAssignment(
                customer_code=self.customer.customer_code,
                tag_id=long_term.id,
                attribute_type="long_term",
                source="customer_confirmed",
                evidence="常用收货地址",
                effective_date=date.today(),
                status="effective",
            )
        )
        self.db.flush()
        order = create_order(
            self.db,
            payload=SalesOrderCreate(
                customer_code=self.customer.customer_code,
                delivery_address="临时收货地",
                temporary_requirements=[
                    {"tag_id": temporary.id, "tag_name": temporary.name, "details": {"address": "临时收货地"}}
                ],
                lines=[{"product_name": "测试商品", "quantity": Decimal("1")}],
            ),
            operator=self.applicant,
        )
        with self.assertRaises(HTTPException) as conflict:
            confirm_order(self.db, order=order, operator=self.applicant)
        self.assertEqual(conflict.exception.status_code, 409)

        public_without_profile = _customer_item(
            self.db,
            self.customer,
            ["customer_code", "customer_name"],
        )
        self.assertNotIn("customer_tag_profile", public_without_profile.fields)
        public_with_profile = _customer_item(
            self.db,
            self.customer,
            ["customer_code", "customer_name", "customer_tag_profile"],
        )
        self.assertIn("customer_tag_profile", public_with_profile.fields)
        self.assertIn("delivery_requirement", public_with_profile.fields["customer_tag_profile"]["categories"])

    def test_versioned_purchase_recommendation_produces_pending_results(self):
        for code, name, group in (
            ("PUR-FREQ", "高频少量", "purchase-frequency"),
            ("PUR-CYCLE", "每日采购", "purchase-cycle"),
            ("PUR-STABLE", "采购量相对稳定", "purchase-planning"),
        ):
            self._tag(code=code, name=name, category="purchase_characteristic", group=group)
        batch = ImportBatch(
            batch_no="B-TAG-REC",
            file_name="sales.xlsx",
            file_type="sales",
            status="completed",
            total_rows=3,
            success_rows=3,
            error_rows=0,
            raw_file_path="tests/sales.xlsx",
        )
        self.db.add(batch)
        self.db.flush()
        for index, days_ago in enumerate((2, 1, 0), start=1):
            self.db.add(
                SalesDetail(
                    batch_id=batch.id,
                    row_number=index,
                    document_no=f"SO-REC-{index}",
                    document_date=date.today() - timedelta(days=days_ago),
                    customer_code=self.customer.customer_code,
                    customer_name=self.customer.customer_name,
                    product_name="商品",
                    sale_qty_base=Decimal("5"),
                )
            )
        rule = create_rule_version(
            self.db,
            rule_code="purchase_characteristic",
            name="采购特征测试规则",
            parameters={"window_days": 30, "high_frequency_days": 7, "high_quantity": 50, "stability_cv": 0.35},
            operator=self.reviewer,
        )
        activate_rule_version(self.db, rule)
        self.db.flush()
        rows = generate_purchase_recommendations(self.db, customer_code=self.customer.customer_code)
        self.db.commit()
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row.status == "pending" and row.rule_version_id == rule.id for row in rows))
        self.assertEqual(
            self.db.scalar(
                select(CustomerTagRecommendation).where(
                    CustomerTagRecommendation.customer_code == self.customer.customer_code,
                    CustomerTagRecommendation.tag_id == rows[0].tag_id,
                )
            ).statistics_end,
            date.today(),
        )


if __name__ == "__main__":
    unittest.main()
