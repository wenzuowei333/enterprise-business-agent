package com.demo.management.data

import java.util.UUID
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class FieldCollaborationRepository @Inject constructor(private val api: MobileApi) {
    suspend fun customerTags(customerCode: String): MobileCustomerTagPayload = api.customerTags(customerCode)

    suspend fun deliveries(query: String?, status: String?, offset: Int): MobileDeliveryPage = api.deliveries(
        query = query?.trim()?.takeIf(String::isNotEmpty),
        status = status,
        offset = offset,
    )

    suspend fun addDeliveryEvent(
        delivery: MobileDeliveryTask,
        transition: MobileDeliveryTransition,
        note: String?,
        signedBy: String?,
    ): MobileDeliveryTask = api.addDeliveryEvent(
        delivery.id,
        MobileDeliveryEventRequest(
            expectedUpdatedAt = delivery.updatedAt,
            idempotencyKey = "android:delivery:${UUID.randomUUID()}",
            eventType = transition.eventType,
            toStatus = transition.toStatus,
            note = note?.trim()?.takeIf(String::isNotEmpty),
            signedBy = signedBy?.trim()?.takeIf(String::isNotEmpty),
        ),
    )
}

data class MobileDeliveryTransition(
    val eventType: String,
    val toStatus: String,
    val label: String,
    val requiresNote: Boolean = false,
    val requiresSignature: Boolean = false,
)
