import unittest
import sys
import types
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch


def install_runtime_stubs() -> None:
    try:
        import fastapi  # noqa: F401
        import sqlalchemy  # noqa: F401
        import sqlalchemy.orm  # noqa: F401
        import app.models  # noqa: F401
        import app.core.config  # noqa: F401
        import app.services.audit_service  # noqa: F401
        return
    except Exception:
        pass

    fastapi_module = types.ModuleType("fastapi")
    fastapi_module.UploadFile = object
    sys.modules.setdefault("fastapi", fastapi_module)

    sqlalchemy_module = types.ModuleType("sqlalchemy")
    class _SelectStub:
        def where(self, *args, **kwargs):
            return self

    sqlalchemy_module.delete = lambda *args, **kwargs: None
    sqlalchemy_module.select = lambda *args, **kwargs: _SelectStub()
    sys.modules.setdefault("sqlalchemy", sqlalchemy_module)

    sqlalchemy_orm_module = types.ModuleType("sqlalchemy.orm")
    sqlalchemy_orm_module.Session = object
    sys.modules.setdefault("sqlalchemy.orm", sqlalchemy_orm_module)

    config_module = types.ModuleType("app.core.config")
    config_module.settings = types.SimpleNamespace(upload_root="/tmp/project-base-tests")
    sys.modules.setdefault("app.core.config", config_module)

    models_module = types.ModuleType("app.models")
    for name in [
        "AccountBalanceSnapshot",
        "CustomerMaster",
        "EmployeeProfile",
        "ImportBatch",
        "ImportError",
        "InventorySnapshot",
        "MasterCategoryBinding",
        "MasterCategoryNode",
        "ProductMaster",
        "PurchaseDetail",
        "ReceivableSnapshot",
        "SalesDetail",
        "SupplierMaster",
        "User",
    ]:
        setattr(models_module, name, type(name, (), {}))
    models_module.EmployeeProfile.status = "active"
    models_module.EmployeeProfile.employee_code = "employee_code"
    models_module.EmployeeProfile.employee_name = "employee_name"
    sys.modules.setdefault("app.models", models_module)

    audit_module = types.ModuleType("app.services.audit_service")
    audit_module.write_audit_log = lambda *args, **kwargs: None
    sys.modules.setdefault("app.services.audit_service", audit_module)


install_runtime_stubs()

from app.services.import_service import (  # noqa: E402
    build_field_mapping,
    create_batch_from_upload,
    infer_data_date_from_filename,
    infer_data_date_from_table,
    required_file_type_import_permission,
    normalize_customer_row,
    path_without_root,
    row_to_standard,
    validate_rows,
)


class CustomerImportMappingTest(unittest.TestCase):
    def test_upload_storage_permission_error_has_a_clear_business_message(self):
        upload = SimpleNamespace(filename="采购明细.csv", file=BytesIO(b"test"))

        with patch("app.services.import_service.Path.mkdir", side_effect=PermissionError("denied")):
            with self.assertRaisesRegex(ValueError, "上传目录不可写"):
                create_batch_from_upload(
                    None,
                    file=upload,
                    file_type="purchase_detail",
                    data_date=None,
                    user=SimpleNamespace(id=1),
                )

    def test_zhizhangshang_customer_export_maps_to_customer_master(self):
        headers = [
            "客户名称",
            "客户编号",
            "公司地址",
            "联系人1",
            "手机1",
            "客户分类",
            "销售区域",
            "业务经理",
            "客户标签",
            "备注",
            "第三方 ERP 客户分类",
            "最后修改时间",
            "收货地址1",
        ]
        mapping = build_field_mapping("customer_master", headers)
        self.assertEqual(mapping["customer_code"], "客户编号")
        self.assertEqual(mapping["customer_name"], "客户名称")
        self.assertEqual(mapping["customer_type"], "客户分类")
        self.assertEqual(mapping["region"], "销售区域")
        self.assertEqual(mapping["salesperson_name"], "业务经理")
        self.assertEqual(mapping["contact_name"], "联系人1")
        self.assertEqual(mapping["contact_phone"], "手机1")
        self.assertEqual(mapping["customer_path"], "第三方 ERP 客户分类")
        self.assertEqual(mapping["profile_updated_at"], "最后修改时间")

        raw_row = {
            "客户名称": "天环-142金源洲",
            "客户编号": "KH20260626000002",
            "公司地址": " ",
            "联系人1": "金源洲",
            "手机1": "15006131170",
            "客户分类": "普通客户/成型市场/苏州天环市场",
            "销售区域": "无销售区域",
            "业务经理": "宋会利",
            "客户标签": "全线下下单；未注册",
            "备注": " ",
            "第三方 ERP 客户分类": "所有客户/测试执掌客户分类",
            "最后修改时间": "2026-07-02 09:18",
            "收货地址1": "江苏省-苏州市-吴江区G318",
        }
        standard = row_to_standard(raw_row, mapping, "customer_master")
        self.assertEqual(standard["address"], "江苏省-苏州市-吴江区G318")
        self.assertEqual(standard["base_remark"], "全线下下单；未注册")
        self.assertIsNone(standard["region"])
        normalize_customer_row(standard)
        self.assertEqual(standard["customer_type"], "普通客户")
        self.assertEqual(standard["region"], "成型市场 / 苏州天环市场")

    def test_customer_path_accepts_forward_slash_root(self):
        self.assertEqual(
            path_without_root("所有客户/成型市场/苏州天环市场", root_names={"全部客户", "所有客户"}, leaf_name=None),
            ["成型市场", "苏州天环市场"],
        )

    def test_import_data_date_infers_common_filename_patterns(self):
        self.assertEqual(str(infer_data_date_from_filename("销售统计明细表-2026_06_26-16_12_52.xls")), "2026-06-26")
        self.assertEqual(str(infer_data_date_from_filename("普丰-采购明细20260624.xls")), "2026-06-24")
        self.assertEqual(str(infer_data_date_from_filename("普丰 历史库存250831(1).xls")), "2025-08-31")

    def test_inventory_data_date_infers_deadline_from_table_meta(self):
        import pandas as pd

        raw = pd.DataFrame(
            [
                ["库存状况线性表", None, None],
                ["所查仓库:", "所辖仓库", None],
                ["截止时间:", "2025-08-31", None],
                [None, None, None],
                ["商品编号", "商品名称", "账面库存_数量"],
                ["SP001", "测试商品", 10],
            ],
            dtype=object,
        )

        self.assertEqual(str(infer_data_date_from_table(raw, "inventory_snapshot")), "2025-08-31")

    def test_receivable_snapshot_maps_customer_and_amount_fields(self):
        headers = [
            "结算单位名称",
            "客户编号",
            "应收余额",
            "期初应收",
            "本期发生",
            "已收金额",
            "账龄",
            "业务员",
            "部门",
            "备注",
        ]

        mapping = build_field_mapping("receivable_snapshot", headers)

        self.assertEqual(mapping["customer_code"], "客户编号")
        self.assertEqual(mapping["customer_name"], "结算单位名称")
        self.assertEqual(mapping["ar_balance"], "应收余额")
        self.assertEqual(mapping["ar_opening_balance"], "期初应收")
        self.assertEqual(mapping["ar_current_amount"], "本期发生")
        self.assertEqual(mapping["received_amount"], "已收金额")
        self.assertEqual(mapping["aging_label"], "账龄")
        self.assertEqual(mapping["salesperson_name"], "业务员")
        self.assertEqual(mapping["department_name"], "部门")
        self.assertEqual(mapping["remark"], "备注")

    def test_receivable_snapshot_maps_demo_receivable_export_headers(self):
        headers = [
            "行号",
            "结算单位编号",
            "结算单位名称",
            "对账说明",
            "信用额度",
            "期初余额_原币",
            "本期增加_原币",
            "本期减少_原币",
            "期末余额_原币",
            "超额度应收账款",
        ]

        mapping = build_field_mapping("receivable_snapshot", headers)

        self.assertEqual(mapping["customer_code"], "结算单位编号")
        self.assertEqual(mapping["customer_name"], "结算单位名称")
        self.assertEqual(mapping["ar_opening_balance"], "期初余额_原币")
        self.assertEqual(mapping["ar_current_amount"], "本期增加_原币")
        self.assertEqual(mapping["received_amount"], "本期减少_原币")
        self.assertEqual(mapping["ar_balance"], "期末余额_原币")

    def test_receivable_snapshot_infers_data_date_from_table_meta(self):
        import pandas as pd

        raw = pd.DataFrame(
            [
                ["应收查询表", None, None],
                ["截止日期:", "2025-08-31", None],
                [None, None, None],
                ["结算单位名称", "应收余额", "业务员"],
                ["吴江恒力食堂", 1200, "冯阳"],
            ],
            dtype=object,
        )

        self.assertEqual(str(infer_data_date_from_table(raw, "receivable_snapshot")), "2025-08-31")

    def test_receivable_snapshot_allows_missing_customer_code_but_requires_name_and_balance(self):
        class _ScalarResult:
            def all(self):
                return []

        class _Db:
            def scalars(self, _stmt):
                return _ScalarResult()

        mapping = build_field_mapping("receivable_snapshot", ["结算单位名称", "应收余额", "客户编号"])
        valid_rows, issues = validate_rows(
            _Db(),
            "receivable_snapshot",
            [
                {"__row_number": 2, "结算单位名称": "吴江恒力食堂", "应收余额": "1200", "客户编号": ""},
                {"__row_number": 3, "结算单位名称": "缺余额客户", "应收余额": "", "客户编号": "C002"},
            ],
            mapping,
        )

        self.assertEqual(len(valid_rows), 1)
        self.assertEqual(valid_rows[0]["customer_name"], "吴江恒力食堂")
        self.assertIsNone(valid_rows[0].get("customer_code"))
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].error_type, "missing_ar_balance")

    def test_receivable_snapshot_requires_dedicated_import_permission(self):
        self.assertEqual(required_file_type_import_permission("receivable_snapshot"), "receivable.import")
        self.assertIsNone(required_file_type_import_permission("account_balance"))


if __name__ == "__main__":
    unittest.main()
