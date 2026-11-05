import json
import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.api.routes.master_data import list_customers_page, update_customer
from app.core.database import Base
from app.models import CustomerMaster, Permission, Role, RolePermission, User
from app.schemas.master_data import CustomerMasterPublic, CustomerMasterUpdate


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


class CustomerAttentionTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self._seed_identity()
        self._seed_customers()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _seed_identity(self):
        role = Role(role_code="admin", role_name="管理员")
        permission = Permission(
            permission_code="customer.view",
            permission_name="查看客户",
            resource_type="customer",
            action_type="view",
        )
        self.user = User(
            username="admin",
            password_hash="hash",
            real_name="管理员",
            role="admin",
            status="active",
            is_active=True,
        )
        self.db.add_all([role, permission, self.user])
        self.db.flush()
        self.db.add(RolePermission(role_id=role.id, permission_id=permission.id))
        self.db.commit()

    def _seed_customers(self):
        self.db.add_all(
            [
                CustomerMaster(
                    customer_code="C001",
                    customer_name="华东完整客户",
                    customer_group_name="华东",
                    contact_name="联系人一",
                    contact_phone="13900000001",
                    address="地址一",
                    status="active",
                ),
                CustomerMaster(
                    customer_code="C002",
                    customer_name="华东停用客户",
                    customer_group_name="华东",
                    contact_name="联系人二",
                    contact_phone="13900000002",
                    address="地址二",
                    status="disabled",
                ),
                CustomerMaster(
                    customer_code="C003",
                    customer_name="华南联系待补客户",
                    customer_group_name="华南",
                    contact_name=None,
                    contact_phone=None,
                    address="地址三",
                    status="active",
                ),
                CustomerMaster(
                    customer_code="C004",
                    customer_name="华南地址待补客户",
                    customer_group_name="华南",
                    contact_name="联系人四",
                    contact_phone="13900000004",
                    address=None,
                    status="active",
                ),
            ]
        )
        self.db.commit()

    @staticmethod
    def _reason_counts(page):
        return {row["code"]: row["count"] for row in page["attention_summary"]["by_reason"]}

    def _page(self, **overrides):
        options = {
            "limit": 50,
            "offset": 0,
            "db": self.db,
            "current_user": self.user,
        }
        options.update(overrides)
        return list_customers_page(**options)

    def test_default_page_adds_attention_fields_without_changing_rows(self):
        page = self._page()

        self.assertEqual(page["total"], 4)
        self.assertEqual([row["customer_code"] for row in page["items"]], ["C001", "C002", "C003", "C004"])
        self.assertEqual(
            page["attention_summary"],
            {
                "total": 4,
                "normal": 1,
                "needs_attention": 3,
                "by_reason": [
                    {"code": "inactive", "label": "已停用", "count": 1},
                    {"code": "missing_contact", "label": "缺联系人", "count": 1},
                    {"code": "missing_phone", "label": "缺电话", "count": 1},
                    {"code": "missing_address", "label": "缺地址", "count": 1},
                ],
            },
        )
        rows = {row["customer_code"]: row for row in page["items"]}
        self.assertEqual(rows["C001"]["attention_state"], "normal")
        self.assertEqual(rows["C001"]["attention_reasons"], [])
        self.assertEqual(
            rows["C003"]["attention_reasons"],
            [
                {"code": "missing_contact", "label": "缺联系人"},
                {"code": "missing_phone", "label": "缺电话"},
            ],
        )

    def test_attention_filters_do_not_narrow_attention_summary(self):
        needs_attention = self._page(attention_state="needs_attention")
        self.assertEqual(needs_attention["total"], 3)
        self.assertEqual(needs_attention["attention_summary"]["total"], 4)
        self.assertEqual(needs_attention["attention_summary"]["normal"], 1)

        normal = self._page(attention_state="normal")
        self.assertEqual(normal["total"], 1)
        self.assertEqual(normal["items"][0]["customer_code"], "C001")
        self.assertEqual(normal["attention_summary"]["needs_attention"], 3)

        missing_address = self._page(attention_reason="missing_address")
        self.assertEqual(missing_address["total"], 1)
        self.assertEqual(missing_address["items"][0]["customer_code"], "C004")
        self.assertEqual(self._reason_counts(missing_address)["missing_address"], 1)
        self.assertEqual(missing_address["attention_summary"]["total"], 4)

    def test_summary_respects_search_and_category_before_attention_filter(self):
        searched = self._page(q="华南", attention_reason="missing_phone")
        self.assertEqual(searched["total"], 1)
        self.assertEqual(searched["items"][0]["customer_code"], "C003")
        self.assertEqual(searched["attention_summary"]["total"], 2)
        self.assertEqual(searched["attention_summary"]["needs_attention"], 2)

        category = self._page(category_path=json.dumps(["华东"]), attention_state="needs_attention")
        self.assertEqual(category["total"], 1)
        self.assertEqual(category["items"][0]["customer_code"], "C002")
        self.assertEqual(category["attention_summary"]["total"], 2)
        self.assertEqual(category["attention_summary"]["normal"], 1)
        self.assertEqual(category["attention_summary"]["needs_attention"], 1)
        self.assertEqual(self._reason_counts(category)["inactive"], 1)

    def test_existing_missing_filters_remain_compatible(self):
        page = self._page(missing_phone=True)

        self.assertEqual(page["total"], 1)
        self.assertEqual(page["items"][0]["customer_code"], "C003")
        self.assertIn("缺电话", page["items"][0]["missing_fields"])
        self.assertEqual(page["attention_summary"]["total"], 1)
        self.assertEqual(page["attention_summary"]["needs_attention"], 1)

    def test_patch_response_keeps_remaining_attention_reasons(self):
        customer = self.db.scalar(
            select(CustomerMaster).where(CustomerMaster.customer_code == "C004")
        )
        customer.contact_phone = None
        self.db.commit()

        updated = update_customer(
            customer.customer_code,
            CustomerMasterUpdate(contact_phone="13900000004"),
            request=None,
            db=self.db,
            current_user=self.user,
        )
        response = CustomerMasterPublic.model_validate(updated).model_dump()

        self.assertEqual(response["attention_state"], "needs_attention")
        self.assertEqual(
            response["attention_reasons"],
            [{"code": "missing_address", "label": "缺地址"}],
        )


if __name__ == "__main__":
    unittest.main()
