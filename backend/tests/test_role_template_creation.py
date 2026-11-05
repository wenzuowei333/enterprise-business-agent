import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Permission, Role, RolePermission
from app.services.role_template_service import RoleTemplateCreateError, create_role_template


class RoleTemplateCreationTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Role.__table__.create(self.engine)
        Permission.__table__.create(self.engine)
        RolePermission.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.db.add_all([
            Permission(permission_code="dashboard.view", permission_name="看首页", resource_type="dashboard", action_type="view"),
            Permission(permission_code="customer.view", permission_name="看客户", resource_type="customer", action_type="view"),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_create_role_template_with_selected_permissions(self):
        role = create_role_template(
            self.db,
            role_code="sales_manager",
            role_name="销售主管",
            description="销售主管默认权限",
            permission_codes=["customer.view", "dashboard.view", "customer.view"],
        )
        self.db.commit()

        saved = self.db.get(Role, role.id)
        self.assertIsNotNone(saved)
        self.assertEqual(saved.role_code, "sales_manager")
        self.assertEqual(saved.role_name, "销售主管")
        self.assertFalse(saved.is_system_role)

        codes = sorted(
            permission.permission_code
            for permission in self.db.query(Permission)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .filter(RolePermission.role_id == role.id)
            .all()
        )
        self.assertEqual(codes, ["customer.view", "dashboard.view"])

    def test_reject_duplicate_role_code(self):
        self.db.add(Role(role_code="sales_manager", role_name="销售主管", description="", is_system_role=False))
        self.db.commit()

        with self.assertRaises(RoleTemplateCreateError) as ctx:
            create_role_template(
                self.db,
                role_code="sales_manager",
                role_name="销售主管2",
                description="",
                permission_codes=[],
            )
        self.assertIn("角色模板编码已存在", str(ctx.exception))

    def test_reject_unknown_permissions(self):
        with self.assertRaises(RoleTemplateCreateError) as ctx:
            create_role_template(
                self.db,
                role_code="sales_manager",
                role_name="销售主管",
                description="",
                permission_codes=["missing.permission"],
            )
        self.assertIn("未知权限", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
