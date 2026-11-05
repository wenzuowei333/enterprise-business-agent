package com.demo.management.feature.collaboration

import com.demo.management.data.MobileDeliveryTransition

fun canViewCustomerTags(permissions: Collection<String>, flags: Map<String, Boolean>): Boolean =
    flags["customer_tags"] == true && permissions.any {
        it in setOf("customer.view", "crm_customer_profile.view", "customer_tag.submit", "customer_tag.review", "customer_tag.history")
    }

fun canViewFulfillment(permissions: Collection<String>, flags: Map<String, Boolean>): Boolean =
    flags["fulfillment"] == true && "delivery.view" in permissions

fun canManageFulfillment(permissions: Collection<String>, flags: Map<String, Boolean>): Boolean =
    canViewFulfillment(permissions, flags) && "delivery.manage" in permissions

fun deliveryTransitions(status: String): List<MobileDeliveryTransition> = when (status) {
    "pending" -> listOf(
        MobileDeliveryTransition("plan", "planned", "确认计划"),
        MobileDeliveryTransition("dispatch", "delivering", "开始配送"),
        MobileDeliveryTransition("cancel", "cancelled", "取消任务", requiresNote = true),
    )
    "planned" -> listOf(
        MobileDeliveryTransition("dispatch", "delivering", "开始配送"),
        MobileDeliveryTransition("exception", "exception", "登记异常", requiresNote = true),
        MobileDeliveryTransition("cancel", "cancelled", "取消任务", requiresNote = true),
    )
    "delivering" -> listOf(
        MobileDeliveryTransition("sign", "delivered", "完成签收", requiresSignature = true),
        MobileDeliveryTransition("exception", "exception", "登记异常", requiresNote = true),
        MobileDeliveryTransition("cancel", "cancelled", "取消任务", requiresNote = true),
    )
    "exception" -> listOf(
        MobileDeliveryTransition("plan", "planned", "重新计划"),
        MobileDeliveryTransition("dispatch", "delivering", "恢复配送"),
        MobileDeliveryTransition("sign", "delivered", "完成签收", requiresSignature = true),
        MobileDeliveryTransition("cancel", "cancelled", "取消任务", requiresNote = true),
    )
    else -> emptyList()
}
