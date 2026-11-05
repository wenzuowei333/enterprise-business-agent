package com.demo.management.data

import com.demo.management.data.local.ProjectDraftDao
import com.demo.management.data.local.ProjectDraftEntity
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class ProjectApplicationRepository @Inject constructor(
    private val api: MobileApi,
    private val drafts: ProjectDraftDao,
) {
    suspend fun users(): List<MobileUserOption> = api.userOptions(limit = 50).items

    suspend fun customers(query: String?): PageResult<MobileCustomerOption> =
        api.customerOptions(q = query?.takeIf { it.isNotBlank() })

    suspend fun create(payload: CrmProjectDraftRequest): ApprovalSummary = api.createProjectDraft(payload)

    suspend fun update(approvalId: Long, payload: CrmProjectDraftRequest): ApprovalSummary =
        api.updateProjectDraft(approvalId, payload).approval

    suspend fun submit(approvalId: Long): ApprovalSummary = api.submitProjectDraft(approvalId).approval

    suspend fun loadLocal(): ProjectDraftEntity? = drafts.find()

    suspend fun saveLocal(contentJson: String, approvalId: Long?) {
        drafts.save(ProjectDraftEntity(approvalId = approvalId, contentJson = contentJson))
    }

    suspend fun clearLocal() = drafts.delete()
}
