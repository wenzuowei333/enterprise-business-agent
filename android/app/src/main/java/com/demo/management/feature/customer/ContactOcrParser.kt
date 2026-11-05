package com.demo.management.feature.customer

data class OcrFieldCandidate(
    val field: String,
    val label: String,
    val value: String,
    val confidence: Float,
    val selected: Boolean = false,
    val alternatives: List<String> = emptyList(),
)

private val phoneRegex = Regex("(?:\\+?86[-\\s]?)?(?:1[3-9](?:[-\\s]?\\d){9}|0\\d{2,3}[-\\s]?\\d{7,8}|400[-\\s]?\\d{3}[-\\s]?\\d{4})")
private val companySuffixes = listOf("有限公司", "股份公司", "集团", "商行", "经营部", "合作社", "公司")
private val excludedNamePrefixes = listOf("电话", "手机", "微信", "地址", "邮箱", "服务热线", "公司")

fun parseBusinessCardText(text: String): List<OcrFieldCandidate> {
    val lines = text.lineSequence().map(String::trim).filter(String::isNotEmpty).toList()
    val candidates = mutableListOf<OcrFieldCandidate>()

    lines.firstOrNull { line -> companySuffixes.any(line::contains) }?.let { company ->
        candidates += OcrFieldCandidate("customer_name", "客户名称", company, 0.9f)
    }

    lines.firstNotNullOfOrNull { line ->
        if (excludedNamePrefixes.any(line::startsWith) || companySuffixes.any(line::contains)) return@firstNotNullOfOrNull null
        Regex("^([\\u4e00-\\u9fa5]{2,4})(?:\\s|$)").find(line)?.groupValues?.get(1)
    }?.let { name -> candidates += OcrFieldCandidate("contact_name", "联系人", name, 0.75f) }

    val phones = phoneRegex.findAll(text).map { match -> match.value.filter(Char::isDigit).removePrefix("86") }.distinct().toList()
    val primaryPhone = phones.firstOrNull { it.length == 11 && it.startsWith("1") } ?: phones.firstOrNull()
    primaryPhone?.let { phone ->
        candidates += OcrFieldCandidate(
            field = "contact_phone",
            label = "联系电话",
            value = phone,
            confidence = if (phone.length == 11 && phone.startsWith("1")) 0.98f else 0.85f,
            alternatives = phones.filterNot { it == phone },
        )
    }

    lines.firstNotNullOfOrNull { line ->
        Regex("^(?:微信|WeChat|wechat)[:：\\s]*(.+)$", RegexOption.IGNORE_CASE).find(line)?.groupValues?.get(1)?.trim()
    }?.takeIf(String::isNotEmpty)?.let { value ->
        candidates += OcrFieldCandidate("contact_channel", "微信/对接方式", value, 0.9f)
    }

    lines.firstNotNullOfOrNull { line ->
        Regex("^(?:地址|联系地址)[:：\\s]*(.+)$").find(line)?.groupValues?.get(1)?.trim()
    }?.takeIf(String::isNotEmpty)?.let { value ->
        candidates += OcrFieldCandidate("address", "详细地址", value, 0.85f)
    }
    return candidates.distinctBy { it.field }
}

fun ocrOverwriteFields(currentValues: Map<String, String>, selectedValues: Map<String, String>): Set<String> =
    selectedValues.mapNotNullTo(mutableSetOf()) { (field, value) ->
        val current = currentValues[field].orEmpty().trim()
        field.takeIf { current.isNotEmpty() && current != value.trim() }
    }
