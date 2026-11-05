package com.demo.management.data

import com.demo.management.core.sync.NetworkFailurePolicy
import com.demo.management.data.local.OfflineDao
import com.squareup.moshi.Moshi
import java.time.Instant
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class CrmRepository @Inject constructor(
    private val api: MobileApi,
    private val offline: OfflineDao,
    private val syncRepository: SyncRepository,
    moshi: Moshi,
) {
    @Volatile
    var lastReadWasOffline: Boolean = false
        private set

    private val customerAdapter = moshi.adapter(LinkedCustomerRow::class.java)
    private val taskAdapter = moshi.adapter(CrmTaskRow::class.java)

    suspend fun customers(query: String?, scope: String?, offset: Int): LinkedCustomerPage =
        runCatching { api.linkedCustomers(query?.takeIf { it.isNotBlank() }, scope, offset = offset).also { lastReadWasOffline = false } }
            .getOrElse { error ->
                if (!NetworkFailurePolicy.isRetryable(error) || !syncRepository.cacheIsReadable()) throw error
                lastReadWasOffline = true
                offlineCustomers(query, scope, offset)
            }

    suspend fun customer(customerCode: String): CustomerContext =
        runCatching { api.customerContext(customerCode).also { lastReadWasOffline = false } }
            .getOrElse { error ->
                if (!NetworkFailurePolicy.isRetryable(error) || !syncRepository.cacheIsReadable()) throw error
                lastReadWasOffline = true
                val customer = offline.customer(customerCode)?.payloadJson?.let(customerAdapter::fromJson) ?: throw error
                val tasks = offline.tasksForCustomer(customerCode).mapNotNull { taskAdapter.fromJson(it.payloadJson) }
                CustomerContext(
                    customer = customer,
                    crm = CustomerCrmContext(
                        tasks = tasks,
                        stats = mapOf(
                            "task_total" to tasks.size,
                            "task_open" to tasks.count { !it.isClosed },
                            "task_closed" to tasks.count { it.isClosed },
                        ),
                    ),
                )
            }

    suspend fun panorama(customerCode: String): CustomerPanorama = runCatching {
        api.customerPanorama(customerCode).also { lastReadWasOffline = false }
    }.getOrElse { error ->
        if (!NetworkFailurePolicy.isRetryable(error) || !syncRepository.cacheIsReadable()) throw error
        val context = customer(customerCode)
        lastReadWasOffline = true
        CustomerPanorama(
            customer = context.customer,
            stats = context.crm.stats,
            tags = CustomerPanoramaTags(compatibilityTags = context.customer.customerTags),
            tasks = context.crm.tasks,
            timeline = context.crm.tasks.map { task ->
                CustomerTimelineItem(
                    key = "task:${task.id}",
                    kind = "task",
                    title = task.taskCode,
                    detail = task.latestOwnerNextAction ?: task.roundTarget ?: task.businessIssuePoint,
                    status = task.status,
                    occurredAt = task.updatedAt,
                    target = WorkbenchTarget(page = "projects", taskId = task.id, projectId = task.projectId),
                )
            },
        )
    }

    suspend fun execution(): ExecutionPayload = runCatching {
        api.execution().also { lastReadWasOffline = false }
    }.getOrElse { error ->
        if (!NetworkFailurePolicy.isRetryable(error) || !syncRepository.cacheIsReadable()) throw error
        val page = tasks(query = null, filter = TaskFilter(closed = false), offset = 0)
        lastReadWasOffline = true
        ExecutionPayload(
            summary = ExecutionSummary(myOpenTasks = page.total),
            myTasks = ExecutionTaskPage(items = page.items, total = page.total),
        )
    }

    suspend fun tasks(query: String?, filter: TaskFilter, offset: Int): CrmTaskPage = runCatching {
        api.tasks(
            q = query?.takeIf { it.isNotBlank() },
            status = filter.status,
            overdue = filter.overdue,
            blocked = filter.blocked,
            needSupport = filter.needSupport,
            closed = filter.closed,
            offset = offset,
        ).also { lastReadWasOffline = false }
    }.getOrElse { error ->
        if (!NetworkFailurePolicy.isRetryable(error) || !syncRepository.cacheIsReadable()) throw error
        lastReadWasOffline = true
        offlineTasks(query, filter, offset)
    }

    suspend fun task(taskId: Long): CrmTaskDetail = runCatching { api.taskDetail(taskId).also { lastReadWasOffline = false } }
        .getOrElse { error ->
            if (!NetworkFailurePolicy.isRetryable(error) || !syncRepository.cacheIsReadable()) throw error
            lastReadWasOffline = true
            val task = offline.task(taskId)?.payloadJson?.let(taskAdapter::fromJson) ?: throw error
            CrmTaskDetail(
                task = task,
                project = CrmProjectSummary(
                    id = task.projectId,
                    projectCode = task.projectCode ?: "-",
                    projectName = task.projectName ?: "离线项目 ${task.projectId}",
                    status = task.projectStatus ?: "active",
                ),
            )
        }

    private suspend fun offlineCustomers(query: String?, scope: String?, offset: Int): LinkedCustomerPage {
        val keyword = query.orEmpty().trim().lowercase()
        val rows = offline.customers().mapNotNull { customerAdapter.fromJson(it.payloadJson) }
            .filter { row ->
                (keyword.isBlank() || listOf(
                    row.customerCode,
                    row.customerName,
                    row.customerShortName,
                    row.contactName,
                    row.contactPhone,
                    row.latestOwnerNextAction,
                ).any { it.orEmpty().lowercase().contains(keyword) }) && when (scope) {
                    "open" -> row.taskOpen > 0
                    "support" -> row.taskNeedSupport > 0
                    "risk" -> row.riskLevel != "normal" || row.taskBlocked > 0
                    "closed" -> row.taskOpen == 0
                    else -> true
                }
            }
        val page = rows.drop(offset).take(20)
        return LinkedCustomerPage(
            items = page,
            total = rows.size,
            limit = 20,
            offset = offset,
            summary = LinkedCustomerSummary(
                totalCustomers = rows.size,
                profileIncomplete = rows.count { it.baseInfoCompleteness.isNullOrBlank() || it.baseInfoCompleteness != "完整" },
                pendingActionCustomers = rows.count { it.latestOwnerNextAction.isNullOrBlank() },
                riskCustomers = rows.count { it.riskLevel != "normal" || it.taskBlocked > 0 },
            ),
        )
    }

    private suspend fun offlineTasks(query: String?, filter: TaskFilter, offset: Int): CrmTaskPage {
        val keyword = query.orEmpty().trim().lowercase()
        val now = Instant.now()
        val rows = offline.tasks().mapNotNull { taskAdapter.fromJson(it.payloadJson) }.filter { task ->
            val matchesQuery = keyword.isBlank() || listOf(
                task.taskCode,
                task.customerCode,
                task.customerName,
                task.executorName,
                task.businessIssuePoint,
                task.latestOwnerNextAction,
            ).any { it.orEmpty().lowercase().contains(keyword) }
            val overdue = task.feedbackDueAt?.let { runCatching { Instant.parse(it) }.getOrNull()?.isBefore(now) } == true && !task.isClosed
            matchesQuery &&
                (filter.status == null || task.status == filter.status) &&
                (filter.blocked == null || task.isBlocked == filter.blocked) &&
                (filter.needSupport == null || task.needSupport == filter.needSupport) &&
                (filter.closed == null || task.isClosed == filter.closed) &&
                (filter.overdue == null || overdue == filter.overdue)
        }
        return CrmTaskPage(rows.drop(offset).take(20), rows.size, 20, offset)
    }
}

data class TaskFilter(
    val status: String? = null,
    val overdue: Boolean? = null,
    val blocked: Boolean? = null,
    val needSupport: Boolean? = null,
    val closed: Boolean? = null,
)
