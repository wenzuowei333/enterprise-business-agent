package com.demo.management.data

import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class ExceptionRepository @Inject constructor(private val api: MobileApi) {
    suspend fun cases(
        query: String?,
        domain: String?,
        severity: String?,
        status: String?,
        assignment: String?,
        offset: Int,
    ): MobileExceptionPage = api.exceptions(
        q = query?.trim()?.takeIf { it.isNotEmpty() },
        domain = domain,
        severity = severity,
        status = status,
        assignment = assignment,
        offset = offset,
    )

    suspend fun detail(caseNo: String): MobileExceptionDetail = api.exceptionDetail(caseNo)

    suspend fun requestDiagnosis(caseNo: String): MobileDiagnosisJob = api.requestExceptionDiagnosis(caseNo)

    suspend fun diagnosisJob(jobId: Long): MobileDiagnosisJob = api.diagnosisJob(jobId)

    suspend fun actions(offset: Int = 0): MobileAiActionPage = api.aiActions(offset = offset)

    suspend fun validateAction(proposalNo: String): MobileAiActionValidation = api.validateAiAction(proposalNo)

    suspend fun executeAction(validation: MobileAiActionValidation, idempotencyKey: String): MobileAiActionExecution {
        val token = requireNotNull(validation.validationToken) { "当前动作未通过校验，不能执行" }
        return api.executeAiAction(
            validation.proposal.proposalNo,
            MobileAiActionExecuteRequest(
                expectedUpdatedAt = validation.proposal.updatedAt,
                idempotencyKey = idempotencyKey,
                validationToken = token,
            ),
        )
    }
}
