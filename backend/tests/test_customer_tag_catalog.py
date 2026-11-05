import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.api.routes.external_api import (
    ExternalApiKeyCustomerFields,
    update_external_api_key_customer_fields,
)
from app.api.routes.master_data import list_customers_page
from app.core.database import Base
from app.models import (
    AuditLog,
    CustomerMaster,
    CustomerTag,
    ExternalApiKey,
    Permission,
    Role,
    RolePermission,
    User,
)
from app.services.customer_tag_service import (
    canonicalize_customer_tags,
    create_customer_tag,
    update_customer_tag,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class CustomerTagCatalogTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        role = Role(role_code="admin", role_name="管理员")
        permission = Permission(
            permission_code="customer.view",
            permission_name="查看客户",
            resource_type="customer",
            action_type="view",
        )
        self.user = User(
            username="tag-admin",
            password_hash="hash",
            real_name="标签管理员",
            role="admin",
            status="active",
            is_active=True,
        )
        self.db.add_all([role, permission, self.user])
        self.db.flush()
        self.db.add(RolePermission(role_id=role.id, permission_id=permission.id))
        self.db.add_all(
            [
                CustomerMaster(customer_code="C001", customer_name="客户一", customer_tags=["重点", "餐饮"]),
                CustomerMaster(customer_code="C002", customer_name="客户二", customer_tags=["重点"]),
                CustomerMaster(customer_code="C003", customer_name="客户三", customer_tags=["餐饮"]),
            ]
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_unknown_tags_are_registered_and_unicode_duplicates_use_canonical_name(self):
        first = canonicalize_customer_tags(self.db, ["  ＶＩＰ  ", "新 客户"], created_by_user_id=self.user.id)
        second = canonicalize_customer_tags(self.db, ["vip", "新   客户"], created_by_user_id=self.user.id)
        self.db.commit()

        self.assertEqual(first, ["VIP", "新 客户"])
        self.assertEqual(second, first)
        rows = list(self.db.scalars(select(CustomerTag).order_by(CustomerTag.id)).all())
        self.assertEqual([row.normalized_name for row in rows], ["vip", "新 客户"])

    def test_rename_and_disable_propagate_to_every_customer_with_audit(self):
        tag = create_customer_tag(
            self.db,
            name="重点",
            color_key="red",
            operator=self.user,
        )
        self.db.commit()

        tag, renamed_count = update_customer_tag(
            self.db,
            row=tag,
            changes={"name": "核心"},
            operator=self.user,
        )
        self.db.commit()
        self.assertEqual(renamed_count, 2)
        customers = list(self.db.scalars(select(CustomerMaster).order_by(CustomerMaster.customer_code)).all())
        self.assertEqual(customers[0].customer_tags, ["核心", "餐饮"])
        self.assertEqual(customers[1].customer_tags, ["核心"])

        tag, disabled_count = update_customer_tag(
            self.db,
            row=tag,
            changes={"is_active": False},
            operator=self.user,
        )
        self.db.commit()
        self.assertEqual(disabled_count, 2)
        self.assertFalse(tag.is_active)
        customers = list(self.db.scalars(select(CustomerMaster).order_by(CustomerMaster.customer_code)).all())
        self.assertEqual(customers[0].customer_tags, ["餐饮"])
        self.assertEqual(customers[1].customer_tags, [])
        audit_rows = list(
            self.db.scalars(
                select(AuditLog).where(AuditLog.action_type == "customer_tag_assignment_sync")
            ).all()
        )
        self.assertGreaterEqual(len(audit_rows), 4)

    def test_customer_list_supports_any_and_all_tag_matching(self):
        any_page = list_customers_page(
            customer_tags="重点,餐饮",
            customer_tag_match="any",
            limit=50,
            offset=0,
            db=self.db,
            current_user=self.user,
        )
        all_page = list_customers_page(
            customer_tags="重点,餐饮",
            customer_tag_match="all",
            limit=50,
            offset=0,
            db=self.db,
            current_user=self.user,
        )
        self.assertEqual(any_page["total"], 3)
        self.assertEqual(all_page["total"], 1)
        self.assertEqual(all_page["items"][0]["customer_code"], "C001")

    def test_external_key_customer_fields_update_preserves_key_and_is_audited(self):
        key = ExternalApiKey(
            key_id="ext_second_brain",
            name="第二大脑",
            key_prefix="prefix",
            key_hash="hash",
            allowed_customer_fields=["customer_code", "customer_name"],
        )
        self.db.add(key)
        self.db.commit()

        result = update_external_api_key_customer_fields(
            key.key_id,
            ExternalApiKeyCustomerFields(allowed_customer_fields=["customer_tags"]),
            request=None,
            db=self.db,
            current_user=self.user,
        )
        self.assertEqual(result["key_prefix"], "prefix")
        self.assertEqual(result["allowed_customer_fields"], ["customer_code", "customer_name", "customer_tags"])
        audit = self.db.scalar(
            select(AuditLog).where(AuditLog.action_type == "external_api_key_customer_fields_update")
        )
        self.assertIsNotNone(audit)
        self.assertEqual(audit.after_data["allowed_customer_fields"], ["customer_code", "customer_name", "customer_tags"])


if __name__ == "__main__":
    unittest.main()
