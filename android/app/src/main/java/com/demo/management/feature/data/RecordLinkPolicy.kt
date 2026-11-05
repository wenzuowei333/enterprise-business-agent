package com.demo.management.feature.data

data class DataRecordLink(val module: String, val query: String, val label: String)

fun relatedRecordLinks(row: Map<String, Any?>): List<DataRecordLink> = buildList {
    row["customer_code"].cleanCode()?.let { add(DataRecordLink("customers", it, "查看客户")) }
    row["settlement_unit_code"].cleanCode()?.let { add(DataRecordLink("customers", it, "查看结算单位")) }
    row["supplier_code"].cleanCode()?.let { add(DataRecordLink("suppliers", it, "查看供应商")) }
    row["product_code"].cleanCode()?.let { add(DataRecordLink("products", it, "查看商品")) }
}.distinctBy { it.module to it.query }

private fun Any?.cleanCode(): String? = this?.toString()?.trim()?.takeIf { it.isNotEmpty() && it != "-" }
