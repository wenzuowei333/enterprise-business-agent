"""Confirmed customer tag catalog, version 2026.07.

The names and grouping in this module mirror the management-center confirmation
document. Stable codes are generated from the declared order and never from the
display name so future display-name revisions do not break assignments.
"""

from __future__ import annotations

from typing import Any


CATALOG_VERSION_CODE = "2026.07"

CUSTOMER_TAG_CATEGORIES = (
    {"key": "classification", "name": "客户分类", "sort_order": 10},
    {"key": "product_opportunity", "name": "产品机会", "sort_order": 20},
    {"key": "purchase_characteristic", "name": "采购特征", "sort_order": 30},
    {"key": "delivery_requirement", "name": "配送需求", "sort_order": 40},
)

CUSTOMER_CLASSIFICATIONS = (
    "餐饮终端客户",
    "连锁餐饮客户",
    "团餐食堂客户",
    "批发流通客户",
    "食品加工客户",
    "商超零售客户",
    "生鲜零售客户",
    "电商渠道客户",
    "社区团购客户",
    "特通渠道客户",
)

CUSTOMER_TAG_GROUPS = (
    {
        "code": "product_sales_opportunity",
        "category_key": "product_opportunity",
        "name": "产品销售机会",
        "tags": (
            "新品推广", "可增加品类", "可替代竞品", "可提高单量", "老品恢复机会",
            "关联产品搭售", "高毛利产品转化", "季节性产品机会", "活动促销机会", "多门店复制机会",
        ),
    },
    {
        "code": "product_adjustment_opportunity",
        "category_key": "product_opportunity",
        "name": "产品调整机会",
        "tags": ("规格升级", "规格降配", "品牌替换", "包装调整", "口味调整", "定制产品需求", "小包装需求", "大包装需求"),
    },
    {
        "code": "product_selection_preference",
        "category_key": "product_opportunity",
        "name": "客户选品偏好",
        "tags": ("价格敏感", "品质优先", "品牌优先", "稳定供货优先", "高性价比优先", "新品接受度高", "新品接受度低"),
    },
    {
        "code": "deal_support_requirement",
        "category_key": "product_opportunity",
        "name": "成交支持需求",
        "tags": ("需要样品试用", "需要试单验证", "需要价格支持", "需要账期支持", "需要配送服务", "需要产品方案", "需要现场试菜", "需要售后支持"),
    },
    {
        "code": "purchase_frequency_volume",
        "category_key": "purchase_characteristic",
        "name": "采购频率与采购量",
        "tags": ("高频少量", "高频大量", "低频少量", "低频大单", "日常零散采购", "集中批量采购", "旺季集中采购", "淡季少量采购"),
    },
    {
        "code": "purchase_cycle",
        "category_key": "purchase_characteristic",
        "name": "采购周期",
        "tags": ("每日采购", "每周采购", "半月采购", "每月采购", "固定周期采购", "不定期采购", "临时补货", "应急采购", "节庆备货", "项目制采购"),
    },
    {
        "code": "supplier_cooperation_mode",
        "category_key": "purchase_characteristic",
        "name": "供应商合作方式",
        "tags": ("单一供应商采购", "多供应商采购", "主供应商＋备用供应商", "按品类分供应商", "比价后采购", "长期协议采购", "临时询价采购", "平台集中采购"),
    },
    {
        "code": "purchase_decision_mode",
        "category_key": "purchase_characteristic",
        "name": "采购决策方式",
        "tags": ("老板直接采购", "专职采购负责", "厨师长决定", "门店负责人决定", "总部统一采购", "门店自主采购", "总部定品、门店下单", "多人共同决策", "招标采购"),
    },
    {
        "code": "purchase_planning_characteristic",
        "category_key": "purchase_characteristic",
        "name": "采购计划特征",
        "tags": ("有明确采购计划", "按销量滚动补货", "按库存预警补货", "按订单采购", "凭经验采购", "临时需求较多", "采购量相对稳定", "采购量波动较大", "季节性明显", "需求预测困难"),
    },
    {
        "code": "receipt_method",
        "category_key": "delivery_requirement",
        "name": "收货方式",
        "tags": ("普通配送", "客户自提", "物流发货", "快递发货", "配送站点自取", "委托第三方收货", "总仓统一收货", "门店分别收货"),
    },
    {
        "code": "delivery_time_requirement",
        "category_key": "delivery_requirement",
        "name": "配送时间要求",
        "tags": ("无固定时间", "固定日期配送", "固定时段配送", "工作日配送", "周末配送", "早间配送", "午间配送", "夜间配送", "当日送达", "次日送达", "预约配送", "加急配送", "禁止时段配送"),
    },
    {
        "code": "delivery_address_distribution",
        "category_key": "delivery_requirement",
        "name": "配送地址与分拨",
        "tags": ("单一地址配送", "多地址配送", "总仓配送", "门店直配", "总仓收货后分拨", "按门店分拣配送", "临时地址配送", "跨区域配送", "配送地址经常变动"),
    },
    {
        "code": "temperature_transport_requirement",
        "category_key": "delivery_requirement",
        "name": "温度及运输要求",
        "tags": ("常温配送", "冷藏配送", "冷冻配送", "冷链配送", "常温与冷链混合配送", "全程温度记录", "禁止解冻", "防晒防高温", "防潮运输", "易碎品运输"),
    },
    {
        "code": "delivery_acceptance_requirement",
        "category_key": "delivery_requirement",
        "name": "交付验收要求",
        "tags": ("普通签收", "指定人员签收", "现场清点验收", "称重验收", "按批次验收", "检查生产日期", "检查保质期", "检查包装完整", "拍照留存", "签字盖章", "提供配送单", "提供检验报告"),
    },
    {
        "code": "onsite_delivery_restriction",
        "category_key": "delivery_requirement",
        "name": "现场配送限制",
        "tags": ("车辆限行", "车辆限高", "需要通行证", "需要提前报备", "需要排队卸货", "指定卸货地点", "无电梯搬运", "需要送货上楼", "需要搬运入库", "需要托盘交付", "需要周转箱", "停车困难"),
    },
)

TAG_COLOR_BY_CATEGORY = {
    "classification": "blue",
    "product_opportunity": "purple",
    "purchase_characteristic": "cyan",
    "delivery_requirement": "green",
}

MUTUAL_EXCLUSION_BY_NAME = {
    "新品接受度高": "new_product_acceptance",
    "新品接受度低": "new_product_acceptance",
    "无固定时间": "delivery_time_fixedness",
    "固定日期配送": "delivery_time_fixedness",
    "固定时段配送": "delivery_time_fixedness",
    "当日送达": "delivery_speed",
    "次日送达": "delivery_speed",
    "加急配送": "delivery_speed",
    "单一地址配送": "delivery_address_count",
    "多地址配送": "delivery_address_count",
    "临时地址配送": "delivery_address_count",
    "常温配送": "delivery_temperature_mode",
    "冷藏配送": "delivery_temperature_mode",
    "冷冻配送": "delivery_temperature_mode",
    "冷链配送": "delivery_temperature_mode",
    "常温与冷链混合配送": "delivery_temperature_mode",
}

TEMPORARY_DELIVERY_TAGS = {"加急配送", "临时地址配送"}

LEGACY_TAG_ALIASES = {
    "城市配送": ("DEL_RECEIPT_METHOD_001", 0.72, "旧标签含义较宽，候选为普通配送"),
    "学校相关": ("CLASSIFICATION_003", 0.88, "学校客户候选归入团餐食堂客户"),
}


def _catalog_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, name in enumerate(CUSTOMER_CLASSIFICATIONS, start=1):
        rows.append(
            {
                "stable_code": f"CLASSIFICATION_{index:03d}",
                "name": name,
                "category_key": "classification",
                "category_name": "客户分类",
                "group_code": None,
                "group_name": None,
                "sort_order": index,
                "selection_rule": "single",
                "mutual_exclusion_key": "customer_primary_classification",
                "color_key": TAG_COLOR_BY_CATEGORY["classification"],
                "applicability": {"attribute_types": ["long_term"]},
            }
        )
    category_names = {item["key"]: item["name"] for item in CUSTOMER_TAG_CATEGORIES}
    category_prefixes = {
        "product_opportunity": "OPP",
        "purchase_characteristic": "PUR",
        "delivery_requirement": "DEL",
    }
    for group_order, group in enumerate(CUSTOMER_TAG_GROUPS, start=1):
        category_key = str(group["category_key"])
        group_token = str(group["code"]).upper()
        prefix = category_prefixes[category_key]
        for index, name in enumerate(group["tags"], start=1):
            attribute_types = ["long_term"]
            if category_key == "delivery_requirement" and name in TEMPORARY_DELIVERY_TAGS:
                attribute_types.append("temporary")
            rows.append(
                {
                    "stable_code": f"{prefix}_{group_token}_{index:03d}",
                    "name": name,
                    "category_key": category_key,
                    "category_name": category_names[category_key],
                    "group_code": group["code"],
                    "group_name": group["name"],
                    "sort_order": group_order * 100 + index,
                    "selection_rule": "primary_optional_secondary" if category_key == "purchase_characteristic" else "multi",
                    "mutual_exclusion_key": MUTUAL_EXCLUSION_BY_NAME.get(name),
                    "color_key": TAG_COLOR_BY_CATEGORY[category_key],
                    "applicability": {"attribute_types": attribute_types},
                }
            )
    return rows


FORMAL_CUSTOMER_TAGS = tuple(_catalog_rows())

assert len(CUSTOMER_TAG_GROUPS) == 15
assert len(FORMAL_CUSTOMER_TAGS) == 152
