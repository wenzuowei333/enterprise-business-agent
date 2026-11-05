from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from numbers import Integral, Real
from pathlib import Path
import hashlib
import re
import shutil
import uuid

import pandas as pd
from fastapi import UploadFile
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    AccountBalanceSnapshot,
    AccountLedgerEntry,
    CustomerMaster,
    EmployeeProfile,
    ImportBatch,
    ImportError,
    InventorySnapshot,
    ProductMaster,
    PurchaseDetail,
    ReceivableSnapshot,
    SalesDetail,
    SupplierMaster,
    User,
)
from app.services.audit_service import write_audit_log
from app.services.customer_identity_service import acquire_customer_identity_locks
from app.services.customer_tag_service import canonicalize_customer_tags
from app.services.master_category_service import ensure_category_binding, split_category_path

MASTER_FILE_TYPES = {"employee_profile", "customer_master", "product_master", "supplier_master"}
PROCESS_FILE_TYPES = {"sales_detail", "purchase_detail", "inventory_snapshot", "account_balance", "account_ledger", "receivable_snapshot"}
SUPPORTED_FILE_TYPES = MASTER_FILE_TYPES | PROCESS_FILE_TYPES
FILE_TYPE_IMPORT_PERMISSIONS = {
    "account_ledger": "account_ledger.import",
    "receivable_snapshot": "receivable.import",
}


class UploadStorageError(ValueError):
    """Raised when the application cannot persist an uploaded import file."""


UPLOAD_STORAGE_ERROR_MESSAGE = "上传目录不可写，暂时无法接收文件，请联系管理员处理上传目录权限。"


def required_file_type_import_permission(file_type: str | None) -> str | None:
    return FILE_TYPE_IMPORT_PERMISSIONS.get((file_type or "").strip())

DATE_SOURCE_LABELS = {
    "filename": "文件名",
    "table_meta": "表格日期字段",
    "table_rows": "表格明细日期",
}

DATE_FIELD_ALIASES: dict[str, list[str]] = {
    "sales_detail": ["单据日期", "业务日期", "日期", "document_date", "data_date"],
    "purchase_detail": ["单据日期", "业务日期", "日期", "document_date", "data_date"],
    "inventory_snapshot": ["截止时间", "截止日期", "快照日期", "库存日期", "数据日期", "日期", "data_date"],
    "account_balance": ["截止时间", "截止日期", "对账日期", "数据日期", "日期", "data_date"],
    "account_ledger": ["查询日期", "截止时间", "截止日期", "对账日期", "数据日期", "单据日期", "日期", "data_date"],
    "receivable_snapshot": ["截止时间", "截止日期", "查询日期", "应收日期", "数据日期", "日期", "data_date"],
    "customer_master": ["最后修改时间", "资料更新时间", "基础信息更新时间", "建档日期", "创建时间", "data_date"],
    "product_master": ["创建日期", "建档日期", "资料更新时间", "data_date"],
    "supplier_master": ["创建日期", "建档日期", "资料更新时间", "data_date"],
    "employee_profile": ["创建日期", "建档日期", "资料更新时间", "data_date"],
}

FIELD_ALIASES: dict[str, dict[str, list[str]]] = {
    "employee_profile": {
        "employee_code": ["员工编号", "职员编号", "业务员编号", "员工编码", "操作员编号", "employee_code"],
        "employee_name": ["员工姓名", "职员姓名", "职员名称", "业务员姓名", "姓名", "employee_name"],
        "department": ["部门", "所属部门", "department"],
        "position": ["职位", "岗位", "职务", "position"],
        "role_code": ["角色", "角色编码", "role_code"],
        "manager_employee_code": ["上级编号", "主管编号", "manager_employee_code"],
        "status": ["状态", "员工状态", "status"],
        "phone": ["电话", "手机号", "手机", "办公电话", "联系电话", "phone"],
        "employee_path": ["职员路径", "员工路径", "employee_path"],
    },
    "customer_master": {
        "customer_code": ["客户编号", "往来单位编号", "单位编号", "客户编码", "客户代码", "customer_code"],
        "customer_name": ["客户名称", "往来单位名称", "单位名称", "客户全称", "customer_name"],
        "customer_short_name": ["客户简称", "简称", "customer_short_name"],
        "customer_type": ["客户类型", "客户分类", "类别", "客户类别", "customer_type"],
        "region": ["销售区域", "区域", "地区", "所属区域", "客户路径", "region"],
        "salesperson_employee_code": ["业务员编号", "职员编号", "员工编号", "salesperson_employee_code"],
        "salesperson_name": ["业务经理", "业务员", "经手人", "职员", "销售员", "业务员姓名", "关联职员", "salesperson_name"],
        "contact_name": ["联系人", "联系人1", "联系人姓名", "收货人姓名1", "contact_name"],
        "contact_phone": ["电话", "手机1", "手机号", "联系电话", "联系方式1", "contact_phone"],
        "contact_channel": ["微信/对接方式", "微信", "对接方式", "联系方式说明", "contact_channel"],
        "customer_group_name": ["客户群名称", "客户群", "微信群", "群名称", "customer_group_name"],
        "customer_tags": ["客户标签", "标签", "客户分类标签", "customer_tags"],
        "address": ["公司地址", "地址", "详细地址", "客户详细地址", "收货地址1", "address"],
        "status": ["状态", "客户状态", "status"],
        "profile_updated_at": ["最后修改时间", "最近基础信息更新时间", "资料更新时间", "基础信息更新时间", "建档日期", "创建时间", "profile_updated_at"],
        "base_remark": ["备注", "基础备注", "客户备注", "客户标签", "base_remark"],
        "disabled_at": ["停用日期", "disabled_at"],
        "customer_path": ["第三方 ERP 客户分类", "客户路径", "客户分类路径", "customer_path"],
    },
    "product_master": {
        "product_code": ["商品编号", "商品编码", "存货编码", "货品编号", "商品代码", "product_code"],
        "product_name": ["商品名称", "货品名称", "存货名称", "产品名称", "product_name"],
        "spec": ["规格", "型号", "规格型号", "spec"],
        "unit": ["单位", "计量单位", "基本计量单位", "销售默认单位", "存货默认单位", "采购默认单位", "unit"],
        "category": ["类别", "商品类别", "分类", "category"],
        "brand": ["品牌", "brand"],
        "barcode": ["条码", "商品条码", "barcode"],
        "reference_sale_price": ["参考售价", "销售价", "售价", "门面售价", "零售价", "快马售价", "reference_sale_price"],
        "reference_cost": ["参考成本", "成本价", "最近进价", "最高进价", "采购价", "reference_cost"],
        "status": ["状态", "商品状态", "status"],
        "stopped_purchase": ["停止采购", "stopped_purchase"],
        "created_at_source": ["创建日期", "建档日期", "created_at_source"],
        "product_path": ["商品路径", "product_path"],
    },
    "supplier_master": {
        "supplier_code": ["供应商编号", "供货商编号", "供应单位编号", "供应商编码", "供应商代码", "supplier_code"],
        "supplier_name": ["供应商名称", "供货商名称", "供应单位名称", "supplier_name"],
        "supplier_short_name": ["供应商简称", "简称", "supplier_short_name"],
        "supplier_type": ["供应商类型", "供货商类型", "类别", "supplier_type"],
        "region": ["区域", "地区", "所属区域", "region"],
        "contact_name": ["联系人", "联系人姓名", "contact_name"],
        "contact_phone": ["电话", "手机号", "联系电话", "contact_phone"],
        "address": ["地址", "详细地址", "供货商详细地址", "供应商详细地址", "address"],
        "status": ["状态", "供应商状态", "status"],
        "disabled_at": ["停用日期", "disabled_at"],
        "supplier_path": ["供货商路径", "供应商路径", "supplier_path"],
    },
    "sales_detail": {
        "document_no": ["单据编号", "document_no"],
        "document_date": ["单据日期", "document_date"],
        "posted_at": ["过账时间", "posted_at"],
        "document_type": ["单据类型", "document_type"],
        "branch_name": ["分支机构名称", "分支机构", "branch_name"],
        "department_name": ["部门名称", "部门", "department_name"],
        "settlement_unit_code": ["结算单位编号", "settlement_unit_code"],
        "settlement_unit_name": ["结算单位名称", "settlement_unit_name"],
        "customer_code": ["往来单位编号", "客户编号", "customer_code"],
        "customer_name": ["往来单位名称", "客户名称", "customer_name"],
        "employee_name": ["职员名称", "业务员", "employee_name"],
        "warehouse_name": ["仓库名称", "warehouse_name"],
        "product_code": ["商品编号", "product_code"],
        "product_name": ["商品名称", "product_name"],
        "sale_qty_base": ["销售数量_基本单位数量", "销售数量_基本单位", "sale_qty_base"],
        "sale_qty_unit": ["销售数量_销售单位数量", "销售数量_销售单位", "sale_qty_unit"],
        "sale_qty_float": ["销售数量_浮动单位数量", "销售数量_浮动单位", "sale_qty_float"],
        "amount_before_discount": ["折前金额_原币", "amount_before_discount"],
        "unit_price_after_discount": ["折后单价_原币", "unit_price_after_discount"],
        "amount_after_discount": ["折后金额_原币", "折后金额_ 原币", "amount_after_discount"],
        "amount_tax_total": ["价税合计_原币", "amount_tax_total"],
        "tax_amount": ["税额", "税额_原币", "tax_amount"],
        "cost_unit_price": ["成本单价", "cost_unit_price"],
        "cost_amount": ["成本金额", "cost_amount"],
        "expense_allocated_amount": ["费用分摊金额", "expense_allocated_amount"],
        "gross_profit": ["毛利", "gross_profit"],
        "gross_margin_rate": ["毛利率(%)", "毛利率", "gross_margin_rate"],
        "prepared_by": ["制单人", "prepared_by"],
        "note": ["说明", "note"],
        "summary": ["摘要", "summary"],
        "reconciliation_mark": ["对账标记", "reconciliation_mark"],
    },
    "purchase_detail": {
        "document_no": ["单据编号", "document_no"],
        "document_date": ["单据日期", "document_date"],
        "posted_at": ["过账时间", "posted_at"],
        "document_type": ["单据类型", "document_type"],
        "branch_name": ["分支机构名称", "分支机构", "branch_name"],
        "settlement_unit_code": ["结算单位编号", "settlement_unit_code"],
        "settlement_unit_name": ["结算单位名称", "settlement_unit_name"],
        "supplier_code": ["往来单位编号", "供应商编号", "供货商编号", "supplier_code"],
        "supplier_name": ["往来单位名称", "供应商名称", "供货商名称", "supplier_name"],
        "employee_name": ["职员名称", "采购员", "employee_name"],
        "department_name": ["部门名称", "部门", "department_name"],
        "warehouse_name": ["仓库名称", "warehouse_name"],
        "product_code": ["商品编号", "product_code"],
        "product_name": ["商品名称", "product_name"],
        "purchase_qty_base": ["数量_基本单位数量", "数量_基本单位", "purchase_qty_base"],
        "purchase_qty_unit": ["数量_采购单位数量", "数量_采购单位", "purchase_qty_unit"],
        "purchase_qty_float": ["数量_浮动单位数量", "数量_浮动单位", "purchase_qty_float"],
        "unit_price": ["商品单价_原币", "unit_price"],
        "amount_after_discount": ["折后金额_原币", "amount_after_discount"],
        "amount_tax_total": ["价税合计_原币", "amount_tax_total"],
        "tax_amount": ["税额_原币", "税额", "tax_amount"],
        "tax_rate": ["税率", "tax_rate"],
        "purchase_amount": ["采购金额_原币", "purchase_amount"],
        "discount_amount": ["折扣额_原币", "discount_amount"],
        "prepared_note": ["说明", "prepared_note"],
        "summary": ["摘要", "summary"],
        "remark": ["备注", "remark"],
        "reconciliation_mark": ["对账标记", "reconciliation_mark"],
    },
    "inventory_snapshot": {
        "product_code": ["商品编号", "product_code"],
        "product_name": ["商品名称", "product_name"],
        "warehouse_name": ["仓库", "仓库名称", "所属仓库", "所查仓库", "warehouse_name"],
        "barcode": ["商品条码", "条码", "barcode"],
        "default_supplier": ["默认供货商", "默认供应商", "default_supplier"],
        "unit_relation": ["单位关系", "unit_relation"],
        "stock_qty": ["账面库存_数量", "stock_qty"],
        "stock_base_unit": ["账面库存_基本单位", "stock_base_unit"],
        "stock_inventory_qty": ["账面库存_库存数量", "stock_inventory_qty"],
        "stock_inventory_unit": ["账面库存_库存单位", "stock_inventory_unit"],
        "locked_base_qty": ["锁定基本数量", "locked_base_qty"],
        "inventory_status": ["库存状况", "inventory_status"],
        "float_qty": ["账面浮动数量_数量", "float_qty"],
        "float_unit": ["账面浮动数量_单位", "float_unit"],
        "average_cost": ["成本均价", "average_cost"],
        "cost_amount": ["成本金额", "cost_amount"],
        "auxiliary_qty": ["自定义辅助数量", "auxiliary_qty"],
    },
    "account_balance": {
        "settlement_unit_code": ["结算单位编号", "往来单位编号", "settlement_unit_code"],
        "settlement_unit_name": ["结算单位名称", "往来单位名称", "settlement_unit_name"],
        "current_opening_balance": ["往来期初余额", "current_opening_balance"],
        "current_amount": ["往来发生额", "current_amount"],
        "current_closing_balance": ["往来期末余额", "current_closing_balance"],
        "ar_opening_balance": ["应收_期初应收余额", "ar_opening_balance"],
        "ar_current_amount": ["应收_本期发生额", "ar_current_amount"],
        "ar_balance": ["应收_应收余额", "ar_balance"],
        "ap_opening_balance": ["应付_期初应付余额", "ap_opening_balance"],
        "ap_current_amount": ["应付_本期发生额", "ap_current_amount"],
        "ap_balance": ["应付_应付余额", "ap_balance"],
        "advance_receipt_opening_balance": ["预收_期初预收余额", "advance_receipt_opening_balance"],
        "advance_receipt_current_amount": ["预收_本期发生额", "advance_receipt_current_amount"],
        "advance_receipt_balance": ["预收_预收余额", "advance_receipt_balance"],
        "advance_payment_opening_balance": ["预付_期初预付余额", "advance_payment_opening_balance"],
        "advance_payment_current_amount": ["预付_本期发生额", "advance_payment_current_amount"],
        "advance_payment_balance": ["预付_预付余额", "advance_payment_balance"],
    },
    "account_ledger": {
        "settlement_unit_code": ["结算单位编号", "往来单位编号", "settlement_unit_code"],
        "settlement_unit_name": ["结算单位名称", "往来单位名称", "settlement_unit_name"],
        "document_type": ["单据类型", "document_type"],
        "document_date": ["单据日期", "document_date"],
        "document_no": ["单据编号", "document_no"],
        "handler_name": ["经手人", "handler_name"],
        "counterparty_name": ["往来单位", "counterparty_name"],
        "amount_before_discount": ["折前金额", "折前金额_原币", "amount_before_discount"],
        "document_amount": ["单据金额", "document_amount"],
        "discount_amount": ["抹零_优惠金额", "抹零/优惠金额", "discount_amount"],
        "received_amount": ["实收金额", "received_amount"],
        "ar_amount": ["应收金额", "ar_amount"],
        "paid_amount": ["实付金额", "paid_amount"],
        "ap_amount": ["应付金额", "ap_amount"],
        "advance_receipt_amount": ["预收金额", "advance_receipt_amount"],
        "advance_payment_amount": ["预付金额", "advance_payment_amount"],
        "current_balance": ["往来余额", "current_balance"],
        "uninvoiced_qty": ["未开票数量", "uninvoiced_qty"],
        "uninvoiced_amount": ["未开票金额", "uninvoiced_amount"],
        "invoice_participation": ["参与开票", "invoice_participation"],
        "summary": ["摘要", "summary"],
        "description": ["说明", "description"],
        "reconciliation_date": ["对账日期", "reconciliation_date"],
        "reconciliation_mark": ["对账标记", "reconciliation_mark"],
    },
    "receivable_snapshot": {
        "customer_code": ["客户编号", "客户编码", "结算单位编号", "往来单位编号", "单位编号", "customer_code"],
        "customer_name": ["客户名称", "客户全称", "结算单位名称", "往来单位名称", "单位名称", "customer_name"],
        "ar_opening_balance": ["期初应收", "期初应收余额", "应收期初余额", "期初余额_原币", "期初余额", "ar_opening_balance"],
        "ar_current_amount": ["本期发生", "应收本期发生", "本期应收发生额", "本期增加_原币", "本期增加", "ar_current_amount"],
        "received_amount": ["已收", "已收金额", "收款", "收款金额", "本期收款", "本期减少_原币", "本期减少", "received_amount"],
        "unreceived_amount": ["未收", "未收金额", "未收余额", "unreceived_amount"],
        "ar_balance": ["应收余额", "应收_应收余额", "欠款余额", "客户欠款", "期末余额_原币", "期末余额", "余额", "ar_balance"],
        "aging_label": ["账龄", "账龄区间", "账龄段", "aging_label"],
        "overdue_days": ["逾期天数", "超期天数", "overdue_days"],
        "salesperson_name": ["业务员", "业务经理", "经手人", "职员名称", "salesperson_name"],
        "department_name": ["部门", "部门名称", "department_name"],
        "remark": ["备注", "说明", "摘要", "remark"],
    },
}

SUMMARY_WAREHOUSE_NAMES = {"所辖仓库", "全部仓库", "所有仓库", "全部", "所有", "all", "ALL"}

REQUIRED_FIELDS = {
    "employee_profile": ["employee_code", "employee_name"],
    "customer_master": ["customer_code", "customer_name"],
    "product_master": ["product_code", "product_name"],
    "supplier_master": ["supplier_code", "supplier_name"],
    "sales_detail": ["document_no", "document_date", "customer_code", "product_code"],
    "purchase_detail": ["document_no", "document_date", "supplier_code", "product_code"],
    "inventory_snapshot": ["product_code", "product_name"],
    "account_balance": ["settlement_unit_code", "settlement_unit_name"],
    "account_ledger": ["settlement_unit_name", "document_type"],
    "receivable_snapshot": ["customer_name", "ar_balance"],
}


@dataclass
class ValidationIssue:
    row_number: int
    error_type: str
    error_message: str
    raw_row: dict


@dataclass
class TableDetection:
    file_type: str
    header_index: int
    matched_fields: int
    required_fields: int
    required_met: bool


def normalize_header(value: object) -> str:
    return str(value or "").strip().replace("\ufeff", "")


def clean_value(value: object) -> str | None:
    if value is None:
        return None
    if pd.isna(value):
        return None
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, Integral):
        return str(value)
    if isinstance(value, Real) and float(value).is_integer():
        return str(int(value))
    text = str(value).strip()
    return text if text else None


def json_safe_value(value: object) -> object:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real):
        return int(value) if float(value).is_integer() else float(value)
    return str(value).strip()


def json_safe_row(row: dict) -> dict:
    return {key: json_safe_value(value) for key, value in row.items() if key != "__row_number"}


def to_decimal(value: object) -> Decimal | None:
    text = clean_value(value)
    if text is None:
        return None
    try:
        return Decimal(text.replace(",", "").replace("%", ""))
    except (InvalidOperation, AttributeError):
        return None


def split_import_tags(value: object) -> list[str]:
    text = clean_value(value)
    if not text:
        return []
    normalized = str(text)
    for separator in ["，", "、", "；", ";", "|", "/", "\\", "\n", "\t"]:
        normalized = normalized.replace(separator, ",")
    tags: list[str] = []
    for item in normalized.replace(" ", ",").split(","):
        tag = item.strip()
        if tag and tag not in tags:
            tags.append(tag)
    return tags[:20]


def non_empty_import_payload(payload: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in payload.items()
        if value is not None and not (isinstance(value, str) and value.strip() == "")
    }


def apply_non_empty_updates(row: object, payload: dict[str, object]) -> None:
    for key, value in non_empty_import_payload(payload).items():
        setattr(row, key, value)


def merge_tags(existing: list | None, incoming: list[str]) -> list[str]:
    tags: list[str] = []
    for item in [*(existing or []), *incoming]:
        text = clean_value(item)
        if text and text not in tags:
            tags.append(text)
    return tags[:20]


def build_field_mapping(file_type: str, headers: list[str]) -> dict[str, str]:
    aliases = FIELD_ALIASES[file_type]
    normalized_headers = {normalize_header(header): header for header in headers}
    mapping: dict[str, str] = {}
    for canonical, options in aliases.items():
        for option in options:
            if option in normalized_headers:
                mapping[canonical] = normalized_headers[option]
                break
    return mapping


def unique_headers(headers: list[object]) -> list[str]:
    seen: dict[str, int] = {}
    result: list[str] = []
    for index, header in enumerate(headers, start=1):
        normalized = normalize_header(header) or f"未命名列{index}"
        seen[normalized] = seen.get(normalized, 0) + 1
        result.append(normalized if seen[normalized] == 1 else f"{normalized}_{seen[normalized]}")
    return result


def detect_header(raw: pd.DataFrame, file_type: str) -> TableDetection:
    aliases = FIELD_ALIASES[file_type]
    required = set(REQUIRED_FIELDS[file_type])
    best_index = 0
    best_matched: set[str] = set()
    max_scan_rows = min(len(raw.index), 80)
    for index in range(max_scan_rows):
        row_values = {normalize_header(value) for value in raw.iloc[index].tolist() if normalize_header(value)}
        matched = {
            canonical
            for canonical, options in aliases.items()
            if any(option in row_values for option in options)
        }
        if len(matched) > len(best_matched):
            best_index = index
            best_matched = matched
    return TableDetection(
        file_type=file_type,
        header_index=best_index,
        matched_fields=len(best_matched),
        required_fields=len(best_matched & required),
        required_met=required.issubset(best_matched),
    )


def detect_header_index(raw: pd.DataFrame, file_type: str | None) -> int:
    if not file_type or file_type not in FIELD_ALIASES:
        return 0
    detection = detect_header(raw, file_type)
    return detection.header_index if detection.required_met else 0


def resolve_file_type(raw: pd.DataFrame, requested_file_type: str) -> str:
    requested = detect_header(raw, requested_file_type)
    if requested.required_met:
        return requested_file_type
    candidates = [detect_header(raw, file_type) for file_type in sorted(SUPPORTED_FILE_TYPES)]
    candidates.sort(
        key=lambda item: (item.required_met, item.required_fields, item.matched_fields),
        reverse=True,
    )
    best = candidates[0]
    return best.file_type if best.required_met else requested_file_type


def table_from_raw(raw: pd.DataFrame, file_type: str | None = None) -> pd.DataFrame:
    raw = raw.fillna("")
    header_index = detect_header_index(raw, file_type)
    headers = unique_headers(raw.iloc[header_index].tolist())
    data = raw.iloc[header_index + 1 :].copy()
    data.columns = headers
    data["__row_number"] = [int(index) + 1 for index in data.index]
    data = data.loc[~data.drop(columns=["__row_number"]).apply(lambda row: all(clean_value(value) is None for value in row), axis=1)]
    return data.reset_index(drop=True)


def read_upload_table(path: Path, file_type: str | None = None) -> pd.DataFrame:
    return table_from_raw(read_raw_upload_table(path), file_type)


def read_raw_upload_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, dtype=object, header=None)
    if suffix in {".xlsx", ".xls"}:
        try:
            df = pd.read_excel(path, dtype=object, header=None)
            if not df.empty:
                return df
        except Exception:
            if suffix != ".xls":
                raise
        if suffix == ".xls":
            return read_excel_with_calamine(path)
    raise ValueError("Unsupported file type")


def read_excel_with_calamine(path: Path) -> pd.DataFrame:
    try:
        from python_calamine import load_workbook
    except ImportError as exc:
        raise ValueError("Excel 读取失败，请将旧版 xls 另存为 xlsx 后重新上传。") from exc
    workbook = load_workbook(str(path))
    sheet = workbook.get_sheet_by_index(0)
    rows = sheet.to_python()
    return pd.DataFrame(rows, dtype=object)


def infer_data_date_from_upload(raw: pd.DataFrame, file_type: str, file_name: str) -> tuple[date | None, str | None]:
    if file_type == "account_ledger":
        ledger_date, source = infer_account_ledger_data_date(raw, file_name)
        if ledger_date:
            return ledger_date, source
    table_date = infer_data_date_from_table(raw, file_type)
    if table_date:
        return table_date, "table_meta"
    filename_date = infer_data_date_from_filename(file_name)
    if filename_date:
        return filename_date, "filename"
    return None, None


def infer_account_ledger_data_date(raw: pd.DataFrame, file_name: str) -> tuple[date | None, str | None]:
    _, period_end = infer_account_ledger_period_from_table(raw)
    if period_end:
        return period_end, "table_meta"
    month_end = infer_month_end_from_filename(file_name)
    if month_end:
        return month_end, "filename"
    filename_date = infer_data_date_from_filename(file_name)
    if filename_date:
        return filename_date, "filename"
    return None, None


def infer_account_ledger_period_end_from_table(raw: pd.DataFrame) -> date | None:
    _, period_end = infer_account_ledger_period_from_table(raw)
    return period_end


def infer_account_ledger_period_from_table(raw: pd.DataFrame) -> tuple[date | None, date | None]:
    max_rows = min(len(raw.index), 40)
    max_cols = min(len(raw.columns), 12)
    start_candidates: list[date] = []
    end_candidates: list[date] = []
    for row_index in range(max_rows):
        values = [raw.iat[row_index, col_index] for col_index in range(max_cols)]
        for col_index, value in enumerate(values):
            label = normalize_header(value).rstrip(":：")
            if label not in {"查询日期", "开始日期", "起始日期", "从", "到", "结束日期", "截止日期"}:
                continue
            for offset in range(1, 4):
                if col_index + offset >= len(values):
                    break
                parsed = parse_date(values[col_index + offset])
                if parsed:
                    if label in {"查询日期", "开始日期", "起始日期", "从"}:
                        start_candidates.append(parsed)
                    else:
                        end_candidates.append(parsed)
                    break
    return (
        min(start_candidates) if start_candidates else None,
        max(end_candidates) if end_candidates else None,
    )


def infer_month_end_from_filename(file_name: str) -> date | None:
    name = Path(file_name).stem
    candidates: list[date] = []
    for match in re.finditer(r"(?<!\d)(20\d{2})[-_./年]?(0[1-9]|1[0-2])(?!\d)", name):
        year = int(match.group(1))
        month = int(match.group(2))
        candidates.append(date(year, month, monthrange(year, month)[1]))
    for match in re.finditer(r"(?<!\d)(\d{2})[-_./年]?(0[1-9]|1[0-2])(?!\d)", name):
        year = 2000 + int(match.group(1))
        month = int(match.group(2))
        candidates.append(date(year, month, monthrange(year, month)[1]))
    return max(candidates) if candidates else None


def infer_data_date_from_filename(file_name: str) -> date | None:
    name = Path(file_name).stem
    candidates: list[date] = []
    for match in re.finditer(r"(?<!\d)(20\d{2})[-_./年](0?[1-9]|1[0-2])[-_./月](0?[1-9]|[12]\d|3[01])(?:日)?(?!\d)", name):
        candidate = safe_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if candidate:
            candidates.append(candidate)
    for match in re.finditer(r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])([0-3]\d)(?!\d)", name):
        candidate = safe_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if candidate:
            candidates.append(candidate)
    for match in re.finditer(r"(?<!\d)(\d{2})(0[1-9]|1[0-2])([0-3]\d)(?!\d)", name):
        year = 2000 + int(match.group(1))
        candidate = safe_date(year, int(match.group(2)), int(match.group(3)))
        if candidate:
            candidates.append(candidate)
    return max(candidates) if candidates else None


def infer_data_date_from_table(raw: pd.DataFrame, file_type: str) -> date | None:
    aliases = {normalize_header(alias) for alias in DATE_FIELD_ALIASES.get(file_type, [])}
    candidates: list[date] = []
    max_rows = min(len(raw.index), 80)
    max_cols = min(len(raw.columns), 40)
    for row_index in range(max_rows):
        values = [raw.iat[row_index, col_index] for col_index in range(max_cols)]
        for col_index, value in enumerate(values):
            label = normalize_header(value).rstrip(":：")
            if label in aliases:
                for offset in range(1, 4):
                    if col_index + offset >= len(values):
                        break
                    parsed = parse_date(values[col_index + offset])
                    if parsed:
                        candidates.append(parsed)
                        break
            if isinstance(value, str):
                embedded = extract_date_from_text(value)
                if embedded:
                    left = value.split(str(embedded.year), 1)[0]
                    if any(alias in normalize_header(left).rstrip(":：") for alias in aliases) or not aliases:
                        candidates.append(embedded)
    if candidates:
        return most_common_date(candidates)

    try:
        df = table_from_raw(raw, file_type)
    except Exception:
        return None
    headers = [normalize_header(column) for column in df.columns.tolist()]
    mapping = build_field_mapping(file_type, headers) if file_type in FIELD_ALIASES else {}
    date_columns = [
        source
        for canonical, source in mapping.items()
        if canonical in {"document_date", "profile_updated_at", "created_at_source"} or normalize_header(source) in aliases
    ]
    date_columns.extend(header for header in headers if normalize_header(header).rstrip(":：") in aliases)
    seen_columns: set[str] = set()
    row_dates: list[date] = []
    for column in date_columns:
        if column in seen_columns or column not in df:
            continue
        seen_columns.add(column)
        for value in df[column].head(200).tolist():
            parsed = parse_date(value)
            if parsed:
                row_dates.append(parsed)
    return most_common_date(row_dates) if row_dates else None


def extract_date_from_text(value: str) -> date | None:
    for pattern in [
        r"(20\d{2})[-_./年](0?[1-9]|1[0-2])[-_./月](0?[1-9]|[12]\d|3[01])(?:日)?",
        r"(20\d{2})(0[1-9]|1[0-2])([0-3]\d)",
        r"(?<!\d)(\d{2})(0[1-9]|1[0-2])([0-3]\d)(?!\d)",
    ]:
        match = re.search(pattern, value)
        if not match:
            continue
        year = int(match.group(1))
        if year < 100:
            year += 2000
        parsed = safe_date(year, int(match.group(2)), int(match.group(3)))
        if parsed:
            return parsed
    return None


def most_common_date(values: list[date]) -> date | None:
    if not values:
        return None
    counts: dict[date, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return sorted(counts, key=lambda item: (counts[item], item), reverse=True)[0]


def infer_inventory_warehouse_from_raw(raw: pd.DataFrame) -> tuple[str | None, str]:
    aliases = {"所查仓库", "仓库", "仓库名称", "所属仓库", "warehouse_name"}
    max_rows = min(len(raw.index), 40)
    max_cols = min(len(raw.columns), 12)
    for row_index in range(max_rows):
        values = [raw.iat[row_index, col_index] for col_index in range(max_cols)]
        for col_index, value in enumerate(values):
            label = normalize_header(value).rstrip(":：")
            if label not in aliases:
                continue
            for offset in range(1, 4):
                if col_index + offset >= len(values):
                    break
                warehouse = clean_value(values[col_index + offset])
                if warehouse:
                    return warehouse, warehouse_scope_for_name(warehouse)
    return None, "unknown"


def warehouse_scope_for_name(value: str | None) -> str:
    text = clean_value(value)
    if not text:
        return "unknown"
    return "all" if text in SUMMARY_WAREHOUSE_NAMES else "specific"


def safe_date(year: int, month: int, day: int) -> date | None:
    try:
        parsed = date(year, month, day)
    except ValueError:
        return None
    if not 2000 <= parsed.year <= 2099:
        return None
    return parsed


def is_placeholder_import_value(file_type: str, canonical: str, text: str) -> bool:
    if file_type != "customer_master":
        return False
    if canonical in {"contact_name", "contact_phone", "address", "contact_channel", "customer_group_name", "base_remark"}:
        return text in {"99", "-", "--", "无", "暂无"}
    if canonical == "region":
        return text in {"无销售区域", "无区域", "-", "--"}
    return False


def row_to_standard(row: dict, mapping: dict[str, str], file_type: str | None = None) -> dict[str, object]:
    standard: dict[str, object] = {}
    aliases = FIELD_ALIASES.get(file_type or "", {})
    for canonical, source in mapping.items():
        candidate_sources = [source, *aliases.get(canonical, [])]
        seen_sources: set[str] = set()
        for candidate_source in candidate_sources:
            if candidate_source in seen_sources or candidate_source not in row:
                continue
            seen_sources.add(candidate_source)
            value = row.get(candidate_source)
            text = clean_value(value)
            if text is None:
                continue
            if file_type and is_placeholder_import_value(file_type, canonical, text):
                continue
            standard[canonical] = value
            break
        else:
            standard[canonical] = None
    return standard


def validate_rows(db: Session, file_type: str, rows: list[dict], mapping: dict[str, str]) -> tuple[list[dict], list[ValidationIssue]]:
    valid_rows: list[dict] = []
    issues: list[ValidationIssue] = []
    seen_codes: set[str] = set()
    employees_by_name = {
        employee.employee_name: employee.employee_code
        for employee in db.scalars(select(EmployeeProfile).where(EmployeeProfile.status == "active")).all()
    }
    employees_by_code = set(db.scalars(select(EmployeeProfile.employee_code).where(EmployeeProfile.status == "active")).all())
    current_ledger_unit_code: str | None = None
    current_ledger_unit_name: str | None = None

    for position, raw_row in enumerate(rows, start=2):
        row_number = int(raw_row.get("__row_number") or position)
        raw_row_for_error = json_safe_row(raw_row)
        normalized = {key: clean_value(value) for key, value in row_to_standard(raw_row, mapping, file_type).items()}
        if file_type == "employee_profile":
            normalize_employee_row(normalized)
        elif file_type == "customer_master":
            normalize_customer_row(normalized)
        elif file_type == "product_master":
            normalize_product_row(normalized)
        elif file_type == "supplier_master":
            normalize_supplier_row(normalized)
        elif file_type == "account_ledger":
            current_ledger_unit_code, current_ledger_unit_name = normalize_account_ledger_row(
                normalized,
                current_ledger_unit_code,
                current_ledger_unit_name,
            )
        normalized["__row_number"] = row_number
        normalized["__raw_row_json"] = raw_row_for_error
        if file_type in PROCESS_FILE_TYPES and is_process_summary_row(file_type, normalized, raw_row):
            continue
        row_issues: list[ValidationIssue] = []
        for field in REQUIRED_FIELDS[file_type]:
            if not normalized.get(field):
                row_issues.append(
                    ValidationIssue(row_number, f"missing_{field}", f"必填字段为空：{field}", raw_row_for_error)
                )

        if file_type in MASTER_FILE_TYPES:
            primary_code_field = REQUIRED_FIELDS[file_type][0]
            primary_code = normalized.get(primary_code_field)
            if primary_code and primary_code in seen_codes:
                row_issues.append(ValidationIssue(row_number, "duplicate_row", f"文件内编号重复：{primary_code}", raw_row_for_error))
            if primary_code:
                seen_codes.add(primary_code)

        if file_type == "customer_master":
            employee_code = normalized.get("salesperson_employee_code")
            salesperson_name = normalized.get("salesperson_name")
            if not employee_code and salesperson_name and salesperson_name in employees_by_name:
                employee_code = employees_by_name[salesperson_name]
                normalized["salesperson_employee_code"] = employee_code
            if employee_code and employee_code not in employees_by_code:
                row_issues.append(
                    ValidationIssue(row_number, "unknown_employee", f"业务员编号未找到员工档案：{employee_code}", raw_row_for_error)
                )

        if row_issues:
            issues.extend(row_issues)
        else:
            valid_rows.append(normalized)

    return valid_rows, issues


def normalize_account_ledger_row(
    row: dict[str, str | None],
    current_unit_code: str | None,
    current_unit_name: str | None,
) -> tuple[str | None, str | None]:
    document_type = row.get("document_type")
    unit_code = row.get("settlement_unit_code")
    unit_name = row.get("settlement_unit_name")
    if unit_code or unit_name:
        current_unit_code = unit_code or current_unit_code
        current_unit_name = unit_name or current_unit_name
    elif current_unit_code or current_unit_name:
        row["settlement_unit_code"] = current_unit_code
        row["settlement_unit_name"] = current_unit_name

    if document_type in {"期初", "期末"}:
        row["document_no"] = row.get("document_no") or document_type
    return current_unit_code, current_unit_name


def normalize_employee_row(row: dict[str, str | None]) -> None:
    employee_path = row.get("employee_path")
    if employee_path and "已停用" in employee_path:
        row["status"] = "disabled"
    elif not row.get("status"):
        row["status"] = "active"
    else:
        row["status"] = normalize_status(row.get("status"))

    department = row.get("department") or ""
    if not row.get("role_code"):
        if "销售" in department:
            row["role_code"] = "salesperson"
        elif "采购" in department:
            row["role_code"] = "business_middle_office"
        elif "运营" in department:
            row["role_code"] = "business_middle_office"
        elif "管理" in department:
            row["role_code"] = "business_middle_office"


def normalize_customer_row(row: dict[str, str | None]) -> None:
    customer_name = row.get("customer_name")
    if customer_name and not row.get("customer_short_name"):
        row["customer_short_name"] = customer_name

    customer_type_segments = split_category_path(row.get("customer_type"))
    if len(customer_type_segments) > 1:
        row["customer_type"] = customer_type_segments[0]
        if not row.get("region"):
            row["region"] = " / ".join(customer_type_segments[1:])

    customer_path = row.get("customer_path") or row.get("region")
    if customer_path:
        segments = split_category_path(customer_path)
        categories = [segment for segment in segments if segment not in {"全部客户", "所有客户", customer_name}]
        has_customer_type = bool(row.get("customer_type"))
        if categories and not has_customer_type:
            row["customer_type"] = categories[0]
        if len(categories) > 1 and not row.get("region"):
            row["region"] = " / ".join(categories if has_customer_type else categories[1:])
        elif categories and categories[0] not in {"未分类客户", "普通客户"} and not row.get("region"):
            row["region"] = categories[0]
        elif not row.get("region"):
            row["region"] = None

    if row.get("disabled_at"):
        row["status"] = "disabled"
    elif not row.get("status"):
        row["status"] = "active"


def normalize_product_row(row: dict[str, str | None]) -> None:
    product_name = row.get("product_name")
    product_path = row.get("product_path")
    path_segments = path_without_root(product_path, root_names={"全部商品"}, leaf_name=product_name)
    if path_segments:
        if not row.get("brand"):
            row["brand"] = path_segments[-1]
        if not row.get("category"):
            category_segments = path_segments[:-1] or path_segments
            row["category"] = " / ".join(category_segments)

    if is_truthy(row.get("stopped_purchase")):
        row["status"] = "disabled"
    elif not row.get("status"):
        row["status"] = "active"
    else:
        row["status"] = normalize_status(row.get("status"))


def normalize_supplier_row(row: dict[str, str | None]) -> None:
    supplier_name = row.get("supplier_name")
    if supplier_name and not row.get("supplier_short_name"):
        row["supplier_short_name"] = supplier_name

    supplier_path = row.get("supplier_path")
    path_segments = path_without_root(supplier_path, root_names={"全部供货商", "全部供应商"}, leaf_name=supplier_name)
    if path_segments:
        if not row.get("supplier_type"):
            row["supplier_type"] = path_segments[0]
        if len(path_segments) > 1 and not row.get("region"):
            row["region"] = " / ".join(path_segments[1:])

    if row.get("disabled_at"):
        row["status"] = "disabled"
    elif not row.get("status"):
        row["status"] = "active"
    else:
        row["status"] = normalize_status(row.get("status"))


def path_without_root(path: str | None, *, root_names: set[str], leaf_name: str | None) -> list[str]:
    if not path:
        return []
    segments = split_category_path(path)
    return [segment for segment in segments if segment not in root_names and segment != leaf_name]


def is_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "是", "启用", "停止", "停用"}


def normalize_status(value: str | None) -> str:
    text = str(value or "").strip().lower()
    if text in {"disabled", "inactive", "停用", "禁用", "停止", "否"}:
        return "disabled"
    return "active"


def is_process_summary_row(file_type: str, normalized: dict[str, object], raw_row: dict) -> bool:
    required_values = [normalized.get(field) for field in REQUIRED_FIELDS[file_type]]
    if any(required_values):
        return False
    row_label = clean_value(raw_row.get("行号")) or ""
    if row_label in {"合计", "总计", "小计"}:
        return True
    raw_values = [clean_value(value) for key, value in raw_row.items() if key != "__row_number"]
    return any(value in {"合计", "总计", "小计"} for value in raw_values) or any(to_decimal(value) is not None for value in raw_values)


def create_batch_from_upload(db: Session, *, file: UploadFile, file_type: str, data_date: date | None, user: User) -> ImportBatch:
    if file_type not in SUPPORTED_FILE_TYPES:
        raise ValueError("Unsupported file type")
    upload_root = Path(settings.upload_root).resolve()
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".xlsx", ".xls", ".csv"}:
        raise ValueError("Unsupported file extension")
    batch_no = f"IMP{datetime.now():%Y%m%d%H%M%S}-{uuid.uuid4().hex[:8]}"
    batch_dir = upload_root / batch_no
    safe_name = Path(file.filename or f"{batch_no}{suffix}").name
    raw_path = batch_dir / safe_name
    try:
        upload_root.mkdir(parents=True, exist_ok=True)
        batch_dir.mkdir(parents=True, exist_ok=True)
        with raw_path.open("wb") as output:
            shutil.copyfileobj(file.file, output)
        with raw_path.open("rb") as uploaded_file:
            content_sha256 = hashlib.file_digest(uploaded_file, "sha256").hexdigest()
    except OSError as exc:
        shutil.rmtree(batch_dir, ignore_errors=True)
        raise UploadStorageError(UPLOAD_STORAGE_ERROR_MESSAGE) from exc

    raw = read_raw_upload_table(raw_path)
    resolved_file_type = resolve_file_type(raw, file_type)
    inferred_data_date, inferred_data_date_source = infer_data_date_from_upload(raw, resolved_file_type, safe_name)
    resolved_data_date = data_date or inferred_data_date
    df = table_from_raw(raw, resolved_file_type)
    headers = [normalize_header(column) for column in df.columns.tolist()]
    mapping = build_field_mapping(resolved_file_type, headers)
    preview_rows = [json_safe_row(row) for row in df.head(20).to_dict(orient="records")]
    batch = ImportBatch(
        batch_no=batch_no,
        file_name=safe_name,
        file_type=resolved_file_type,
        data_date=resolved_data_date,
        export_date=inferred_data_date,
        uploaded_by=user.id,
        status="uploaded",
        total_rows=len(df.index),
        raw_file_path=str(raw_path),
        content_sha256=content_sha256,
        header_json=headers,
        preview_json=preview_rows,
        mapping_json=mapping,
    )
    db.add(batch)
    db.flush()
    write_audit_log(
        db,
        action_type="upload",
        resource_type="import_batch",
        resource_id=batch.batch_no,
        user=user,
        after_data={
            "requested_file_type": file_type,
            "file_type": resolved_file_type,
            "file_name": safe_name,
            "rows": len(df.index),
            "data_date": resolved_data_date.isoformat() if resolved_data_date else None,
            "inferred_data_date": inferred_data_date.isoformat() if inferred_data_date else None,
            "inferred_data_date_source": DATE_SOURCE_LABELS.get(inferred_data_date_source or "", inferred_data_date_source),
        },
    )
    return batch


def validate_batch(db: Session, batch: ImportBatch) -> ImportBatch:
    df = read_upload_table(Path(batch.raw_file_path), batch.file_type)
    rows = df.to_dict(orient="records")
    mapping = batch.mapping_json or {}
    db.execute(delete(ImportError).where(ImportError.batch_id == batch.id))
    valid_rows, issues = validate_rows(db, batch.file_type, rows, mapping)
    from app.services.master_link_service import rebuild_batch_master_link_issues
    rebuild_batch_master_link_issues(db, batch, valid_rows)
    for issue in issues:
        db.add(
            ImportError(
                batch_id=batch.id,
                row_number=issue.row_number,
                error_type=issue.error_type,
                error_message=issue.error_message,
                raw_row_json=issue.raw_row,
            )
        )
    batch.total_rows = len(valid_rows) + len(issues)
    batch.success_rows = len(valid_rows)
    batch.error_rows = len(issues)
    batch.status = "validated" if not issues else "partial_error"
    return batch


def commit_batch(db: Session, batch: ImportBatch) -> ImportBatch:
    if batch.status not in {"validated", "partial_error"}:
        validate_batch(db, batch)
    if batch.error_rows:
        batch.status = "partial_error"
        return batch
    raw_path = Path(batch.raw_file_path)
    rows = read_upload_table(raw_path, batch.file_type).to_dict(orient="records")
    valid_rows, issues = validate_rows(db, batch.file_type, rows, batch.mapping_json or {})
    if issues:
        batch.status = "partial_error"
        batch.error_rows = len(issues)
        return batch

    if batch.file_type == "employee_profile":
        for row in valid_rows:
            upsert_employee(db, row)
        from app.services.master_link_service import rebuild_master_link_issues
        rebuild_master_link_issues(db)
    elif batch.file_type == "customer_master":
        for row in valid_rows:
            upsert_customer(db, row)
        from app.services.master_link_service import rebuild_master_link_issues
        rebuild_master_link_issues(db)
    elif batch.file_type == "product_master":
        for row in valid_rows:
            upsert_product(db, row)
        from app.services.master_link_service import rebuild_master_link_issues
        rebuild_master_link_issues(db)
    elif batch.file_type == "supplier_master":
        for row in valid_rows:
            upsert_supplier(db, row)
        from app.services.master_link_service import rebuild_master_link_issues
        rebuild_master_link_issues(db)
    elif batch.file_type == "sales_detail":
        db.execute(delete(SalesDetail).where(SalesDetail.batch_id == batch.id))
        for row in valid_rows:
            insert_sales_detail(db, batch, row)
        from app.services.inventory_flow_service import rebuild_after_sales_import
        rebuild_after_sales_import(db, batch.id)
        from app.services.master_link_service import rebuild_batch_master_link_issues
        rebuild_batch_master_link_issues(db, batch)
    elif batch.file_type == "purchase_detail":
        db.execute(delete(PurchaseDetail).where(PurchaseDetail.batch_id == batch.id))
        for row in valid_rows:
            insert_purchase_detail(db, batch, row)
        from app.services.inventory_flow_service import rebuild_after_purchase_import
        rebuild_after_purchase_import(db, batch.id)
        from app.services.master_link_service import rebuild_batch_master_link_issues
        rebuild_batch_master_link_issues(db, batch)
    elif batch.file_type == "inventory_snapshot":
        meta_warehouse, meta_scope = infer_inventory_warehouse_from_raw(read_raw_upload_table(raw_path))
        db.execute(delete(InventorySnapshot).where(InventorySnapshot.batch_id == batch.id))
        for row in valid_rows:
            insert_inventory_snapshot(db, batch, row, meta_warehouse=meta_warehouse, meta_scope=meta_scope)
        from app.services.inventory_flow_service import rebuild_after_inventory_import
        rebuild_after_inventory_import(db, batch.id)
    elif batch.file_type == "account_balance":
        db.execute(delete(AccountBalanceSnapshot).where(AccountBalanceSnapshot.batch_id == batch.id))
        for row in valid_rows:
            insert_account_balance_snapshot(db, batch, row)
    elif batch.file_type == "account_ledger":
        period_start, period_end = infer_account_ledger_period_from_table(read_raw_upload_table(raw_path))
        db.execute(delete(AccountLedgerEntry).where(AccountLedgerEntry.batch_id == batch.id))
        for row in valid_rows:
            insert_account_ledger_entry(db, batch, row, period_start=period_start, period_end=period_end)
        from app.services.receivable_service import rebuild_receivable_checks
        rebuild_receivable_checks(db)
        from app.services.master_link_service import rebuild_batch_master_link_issues
        rebuild_batch_master_link_issues(db, batch)
    elif batch.file_type == "receivable_snapshot":
        db.execute(delete(ReceivableSnapshot).where(ReceivableSnapshot.batch_id == batch.id))
        for row in valid_rows:
            insert_receivable_snapshot(db, batch, row)
        from app.services.receivable_service import rebuild_receivable_checks
        rebuild_receivable_checks(db)
    batch.success_rows = len(valid_rows)
    batch.error_rows = 0
    batch.status = "committed"
    from app.services.exception_center_service import enqueue_incremental_exception_scan_safely

    derived_domains = []
    if batch.file_type in {"inventory_snapshot", "sales_detail", "purchase_detail"}:
        derived_domains.extend(["inventory", "master_data"])
    elif batch.file_type in {"account_ledger", "receivable_snapshot"}:
        derived_domains.extend(["receivable", "master_data"])
    elif batch.file_type in {"customer_master", "product_master", "supplier_master"}:
        derived_domains.append("master_data")
    enqueue_incremental_exception_scan_safely(
        db,
        domains=["import"],
        source_batch_kind="import",
        source_batch_id=batch.id,
    )
    if derived_domains:
        enqueue_incremental_exception_scan_safely(db, domains=derived_domains)
    return batch


def upsert_employee(db: Session, row: dict) -> None:
    employee = db.scalar(select(EmployeeProfile).where(EmployeeProfile.employee_code == row["employee_code"]))
    payload = {
        "employee_name": row["employee_name"],
        "department": row.get("department"),
        "position": row.get("position"),
        "role_code": row.get("role_code"),
        "manager_employee_code": row.get("manager_employee_code"),
        "status": row.get("status"),
        "phone": row.get("phone"),
    }
    if employee is None:
        db.add(EmployeeProfile(employee_code=row["employee_code"], **{**payload, "status": payload.get("status") or "active"}))
    else:
        apply_non_empty_updates(employee, payload)


def upsert_customer(db: Session, row: dict) -> None:
    customer = db.scalar(select(CustomerMaster).where(CustomerMaster.customer_code == row["customer_code"]))
    payload = {
        "customer_name": row["customer_name"],
        "customer_short_name": row.get("customer_short_name"),
        "customer_type": row.get("customer_type"),
        "region": row.get("region"),
        "salesperson_employee_code": row.get("salesperson_employee_code"),
        "salesperson_name": row.get("salesperson_name"),
        "contact_name": row.get("contact_name"),
        "contact_phone": row.get("contact_phone"),
        "contact_channel": row.get("contact_channel"),
        "customer_group_name": row.get("customer_group_name"),
        "customer_tags": canonicalize_customer_tags(db, split_import_tags(row.get("customer_tags"))),
        "address": row.get("address"),
        "status": row.get("status"),
        "source": "import",
        "profile_updated_at": parse_datetime(row.get("profile_updated_at")) or datetime.now(timezone.utc),
        "base_remark": row.get("base_remark"),
    }
    if customer is None:
        acquire_customer_identity_locks(
            db,
            customer_name=payload["customer_name"],
            contact_phone=payload["contact_phone"],
        )
        db.add(CustomerMaster(customer_code=row["customer_code"], **{**payload, "status": payload.get("status") or "active"}))
    else:
        next_customer_name = payload["customer_name"] or customer.customer_name
        next_contact_phone = payload["contact_phone"] or customer.contact_phone
        acquire_customer_identity_locks(
            db,
            customer_name=next_customer_name,
            contact_phone=next_contact_phone,
        )
        tags = payload.pop("customer_tags", [])
        apply_non_empty_updates(customer, payload)
        if tags:
            customer.customer_tags = canonicalize_customer_tags(db, merge_tags(customer.customer_tags, tags))
    category_path = path_without_root(row.get("customer_path"), root_names={"全部客户", "所有客户"}, leaf_name=row.get("customer_name"))
    if not category_path:
        category_path = [
            segment
            for segment in [
                *split_category_path(row.get("customer_group_name")),
                *split_category_path(row.get("customer_type")),
                *split_category_path(row.get("region")),
            ]
            if segment
        ]
    ensure_category_binding(
        db,
        kind="customers",
        path=category_path,
        resource_code=row["customer_code"],
        is_primary=True,
        source="import",
    )


def upsert_product(db: Session, row: dict) -> None:
    product = db.scalar(select(ProductMaster).where(ProductMaster.product_code == row["product_code"]))
    payload = {
        "product_name": row["product_name"],
        "spec": row.get("spec"),
        "unit": row.get("unit"),
        "category": row.get("category"),
        "brand": row.get("brand"),
        "barcode": row.get("barcode"),
        "reference_sale_price": to_decimal(row.get("reference_sale_price")),
        "reference_cost": to_decimal(row.get("reference_cost")),
        "status": row.get("status"),
        "source": "import",
    }
    if product is None:
        db.add(ProductMaster(product_code=row["product_code"], **{**payload, "status": payload.get("status") or "active"}))
    else:
        apply_non_empty_updates(product, payload)
    category_path = path_without_root(row.get("product_path"), root_names={"全部商品"}, leaf_name=row.get("product_name"))
    if not category_path:
        category_path = [
            segment
            for segment in [
                *split_category_path(row.get("category")),
                *split_category_path(row.get("brand")),
            ]
            if segment
        ]
    ensure_category_binding(
        db,
        kind="products",
        path=category_path,
        resource_code=row["product_code"],
        is_primary=True,
        source="import",
    )


def upsert_supplier(db: Session, row: dict) -> None:
    supplier = db.scalar(select(SupplierMaster).where(SupplierMaster.supplier_code == row["supplier_code"]))
    payload = {
        "supplier_name": row["supplier_name"],
        "supplier_short_name": row.get("supplier_short_name"),
        "supplier_type": row.get("supplier_type"),
        "region": row.get("region"),
        "contact_name": row.get("contact_name"),
        "contact_phone": row.get("contact_phone"),
        "address": row.get("address"),
        "status": row.get("status"),
        "source": "import",
    }
    if supplier is None:
        db.add(SupplierMaster(supplier_code=row["supplier_code"], **{**payload, "status": payload.get("status") or "active"}))
    else:
        apply_non_empty_updates(supplier, payload)


def insert_sales_detail(db: Session, batch: ImportBatch, row: dict) -> None:
    db.add(
        SalesDetail(
            batch_id=batch.id,
            row_number=int(row.get("__row_number") or 0),
            data_date=parse_date(row.get("document_date")) or batch.data_date,
            document_no=row.get("document_no"),
            document_date=parse_date(row.get("document_date")),
            posted_at=parse_datetime(row.get("posted_at")),
            document_type=row.get("document_type"),
            branch_name=row.get("branch_name"),
            department_name=row.get("department_name"),
            settlement_unit_code=row.get("settlement_unit_code"),
            settlement_unit_name=row.get("settlement_unit_name"),
            customer_code=row.get("customer_code"),
            customer_name=row.get("customer_name"),
            employee_name=row.get("employee_name"),
            warehouse_name=row.get("warehouse_name"),
            product_code=row.get("product_code"),
            product_name=row.get("product_name"),
            sale_qty_base=to_decimal(row.get("sale_qty_base")),
            sale_qty_unit=to_decimal(row.get("sale_qty_unit")),
            sale_qty_float=to_decimal(row.get("sale_qty_float")),
            amount_before_discount=to_decimal(row.get("amount_before_discount")),
            unit_price_after_discount=to_decimal(row.get("unit_price_after_discount")),
            amount_after_discount=to_decimal(row.get("amount_after_discount")),
            amount_tax_total=to_decimal(row.get("amount_tax_total")),
            tax_amount=to_decimal(row.get("tax_amount")),
            cost_unit_price=to_decimal(row.get("cost_unit_price")),
            cost_amount=to_decimal(row.get("cost_amount")),
            expense_allocated_amount=to_decimal(row.get("expense_allocated_amount")),
            gross_profit=to_decimal(row.get("gross_profit")),
            gross_margin_rate=to_decimal(row.get("gross_margin_rate")),
            prepared_by=row.get("prepared_by"),
            note=row.get("note"),
            summary=row.get("summary"),
            reconciliation_mark=row.get("reconciliation_mark"),
            raw_row_json=row.get("__raw_row_json"),
        )
    )


def insert_purchase_detail(db: Session, batch: ImportBatch, row: dict) -> None:
    db.add(
        PurchaseDetail(
            batch_id=batch.id,
            row_number=int(row.get("__row_number") or 0),
            data_date=parse_date(row.get("document_date")) or batch.data_date,
            document_no=row.get("document_no"),
            document_date=parse_date(row.get("document_date")),
            posted_at=parse_datetime(row.get("posted_at")),
            document_type=row.get("document_type"),
            branch_name=row.get("branch_name"),
            department_name=row.get("department_name"),
            settlement_unit_code=row.get("settlement_unit_code"),
            settlement_unit_name=row.get("settlement_unit_name"),
            supplier_code=row.get("supplier_code"),
            supplier_name=row.get("supplier_name"),
            employee_name=row.get("employee_name"),
            warehouse_name=row.get("warehouse_name"),
            product_code=row.get("product_code"),
            product_name=row.get("product_name"),
            purchase_qty_base=to_decimal(row.get("purchase_qty_base")),
            purchase_qty_unit=to_decimal(row.get("purchase_qty_unit")),
            purchase_qty_float=to_decimal(row.get("purchase_qty_float")),
            unit_price=to_decimal(row.get("unit_price")),
            amount_after_discount=to_decimal(row.get("amount_after_discount")),
            amount_tax_total=to_decimal(row.get("amount_tax_total")),
            tax_amount=to_decimal(row.get("tax_amount")),
            tax_rate=to_decimal(row.get("tax_rate")),
            purchase_amount=to_decimal(row.get("purchase_amount")),
            discount_amount=to_decimal(row.get("discount_amount")),
            prepared_note=row.get("prepared_note"),
            summary=row.get("summary"),
            remark=row.get("remark"),
            reconciliation_mark=row.get("reconciliation_mark"),
            raw_row_json=row.get("__raw_row_json"),
        )
    )


def insert_inventory_snapshot(db: Session, batch: ImportBatch, row: dict, *, meta_warehouse: str | None = None, meta_scope: str = "unknown") -> None:
    warehouse_name = row.get("warehouse_name") or meta_warehouse
    warehouse_scope = warehouse_scope_for_name(warehouse_name) if row.get("warehouse_name") else meta_scope
    db.add(
        InventorySnapshot(
            batch_id=batch.id,
            row_number=int(row.get("__row_number") or 0),
            data_date=batch.data_date,
            product_code=row.get("product_code"),
            product_name=row.get("product_name"),
            warehouse_name=warehouse_name,
            warehouse_scope=warehouse_scope,
            barcode=row.get("barcode"),
            default_supplier=row.get("default_supplier"),
            unit_relation=row.get("unit_relation"),
            stock_qty=to_decimal(row.get("stock_qty")),
            stock_base_unit=row.get("stock_base_unit"),
            stock_inventory_qty=to_decimal(row.get("stock_inventory_qty")),
            stock_inventory_unit=row.get("stock_inventory_unit"),
            locked_base_qty=to_decimal(row.get("locked_base_qty")),
            inventory_status=row.get("inventory_status"),
            float_qty=to_decimal(row.get("float_qty")),
            float_unit=row.get("float_unit"),
            average_cost=to_decimal(row.get("average_cost")),
            cost_amount=to_decimal(row.get("cost_amount")),
            auxiliary_qty=to_decimal(row.get("auxiliary_qty")),
            raw_row_json=row.get("__raw_row_json"),
        )
    )


def insert_account_balance_snapshot(db: Session, batch: ImportBatch, row: dict) -> None:
    db.add(
        AccountBalanceSnapshot(
            batch_id=batch.id,
            row_number=int(row.get("__row_number") or 0),
            data_date=batch.data_date,
            settlement_unit_code=row.get("settlement_unit_code"),
            settlement_unit_name=row.get("settlement_unit_name"),
            current_opening_balance=to_decimal(row.get("current_opening_balance")),
            current_amount=to_decimal(row.get("current_amount")),
            current_closing_balance=to_decimal(row.get("current_closing_balance")),
            ar_opening_balance=to_decimal(row.get("ar_opening_balance")),
            ar_current_amount=to_decimal(row.get("ar_current_amount")),
            ar_balance=to_decimal(row.get("ar_balance")),
            ap_opening_balance=to_decimal(row.get("ap_opening_balance")),
            ap_current_amount=to_decimal(row.get("ap_current_amount")),
            ap_balance=to_decimal(row.get("ap_balance")),
            advance_receipt_opening_balance=to_decimal(row.get("advance_receipt_opening_balance")),
            advance_receipt_current_amount=to_decimal(row.get("advance_receipt_current_amount")),
            advance_receipt_balance=to_decimal(row.get("advance_receipt_balance")),
            advance_payment_opening_balance=to_decimal(row.get("advance_payment_opening_balance")),
            advance_payment_current_amount=to_decimal(row.get("advance_payment_current_amount")),
            advance_payment_balance=to_decimal(row.get("advance_payment_balance")),
            raw_row_json=row.get("__raw_row_json"),
        )
    )


def insert_account_ledger_entry(
    db: Session,
    batch: ImportBatch,
    row: dict,
    *,
    period_start: date | None = None,
    period_end: date | None = None,
) -> None:
    document_type = row.get("document_type")
    row_role = account_ledger_row_role(document_type)
    document_date = parse_date(row.get("document_date"))
    reconciliation_date = parse_date(row.get("reconciliation_date"))
    if row_role == "opening" and period_start:
        balance_date = period_start - timedelta(days=1)
    elif row_role == "closing":
        balance_date = period_end or batch.data_date
    else:
        balance_date = document_date or reconciliation_date or batch.data_date
    db.add(
        AccountLedgerEntry(
            batch_id=batch.id,
            row_number=int(row.get("__row_number") or 0),
            data_date=balance_date,
            period_start=period_start,
            period_end=period_end or batch.data_date,
            balance_date=balance_date,
            settlement_unit_code=row.get("settlement_unit_code"),
            settlement_unit_name=row.get("settlement_unit_name"),
            document_type=document_type,
            document_date=document_date,
            document_no=row.get("document_no"),
            handler_name=row.get("handler_name"),
            counterparty_name=row.get("counterparty_name"),
            amount_before_discount=to_decimal(row.get("amount_before_discount")),
            document_amount=to_decimal(row.get("document_amount")),
            discount_amount=to_decimal(row.get("discount_amount")),
            received_amount=to_decimal(row.get("received_amount")),
            ar_amount=to_decimal(row.get("ar_amount")),
            paid_amount=to_decimal(row.get("paid_amount")),
            ap_amount=to_decimal(row.get("ap_amount")),
            advance_receipt_amount=to_decimal(row.get("advance_receipt_amount")),
            advance_payment_amount=to_decimal(row.get("advance_payment_amount")),
            current_balance=to_decimal(row.get("current_balance")),
            uninvoiced_qty=to_decimal(row.get("uninvoiced_qty")),
            uninvoiced_amount=to_decimal(row.get("uninvoiced_amount")),
            invoice_participation=row.get("invoice_participation"),
            summary=row.get("summary"),
            description=row.get("description"),
            reconciliation_date=reconciliation_date,
            reconciliation_mark=row.get("reconciliation_mark"),
            row_role=row_role,
            raw_row_json=row.get("__raw_row_json"),
        )
    )


def account_ledger_row_role(document_type: str | None) -> str:
    if document_type == "期初":
        return "opening"
    if document_type == "期末":
        return "closing"
    return "transaction"


def insert_receivable_snapshot(db: Session, batch: ImportBatch, row: dict) -> None:
    overdue_days_decimal = to_decimal(row.get("overdue_days"))
    db.add(
        ReceivableSnapshot(
            batch_id=batch.id,
            row_number=int(row.get("__row_number") or 0),
            data_date=batch.data_date,
            customer_code=row.get("customer_code"),
            customer_name=row.get("customer_name"),
            match_status="pending",
            ar_opening_balance=to_decimal(row.get("ar_opening_balance")),
            ar_current_amount=to_decimal(row.get("ar_current_amount")),
            received_amount=to_decimal(row.get("received_amount")),
            unreceived_amount=to_decimal(row.get("unreceived_amount")),
            ar_balance=to_decimal(row.get("ar_balance")),
            aging_label=row.get("aging_label"),
            overdue_days=int(overdue_days_decimal) if overdue_days_decimal is not None else None,
            salesperson_name=row.get("salesperson_name"),
            department_name=row.get("department_name"),
            remark=row.get("remark"),
            raw_row_json=row.get("__raw_row_json"),
        )
    )


def parse_date(value: object) -> date | None:
    parsed = parse_datetime(value)
    return parsed.date() if parsed else None


def parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
    if isinstance(value, Real) and not isinstance(value, bool):
        try:
            parsed_numeric = pd.to_datetime(value, unit="D", origin="1899-12-30")
        except (TypeError, ValueError, OverflowError):
            parsed_numeric = None
        if parsed_numeric is not None and not pd.isna(parsed_numeric):
            result = parsed_numeric.to_pydatetime()
            return result if result.tzinfo else result.replace(tzinfo=timezone.utc)
    cleaned = clean_value(value)
    if not cleaned:
        return None
    if cleaned.replace(".", "", 1).isdigit():
        numeric = float(cleaned)
        if 20000 <= numeric <= 80000:
            try:
                parsed_numeric = pd.to_datetime(numeric, unit="D", origin="1899-12-30")
            except (TypeError, ValueError, OverflowError):
                parsed_numeric = None
            if parsed_numeric is not None and not pd.isna(parsed_numeric):
                result = parsed_numeric.to_pydatetime()
                return result if result.tzinfo else result.replace(tzinfo=timezone.utc)
    try:
        parsed = pd.to_datetime(cleaned)
    except (TypeError, ValueError):
        return None
    if pd.isna(parsed):
        return None
    result = parsed.to_pydatetime()
    return result if result.tzinfo else result.replace(tzinfo=timezone.utc)
