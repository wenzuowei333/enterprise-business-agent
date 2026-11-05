package com.demo.management.core.upload

import android.content.Context
import androidx.hilt.work.HiltWorker
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.demo.management.data.MobileApi
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.asRequestBody
import java.io.File

@HiltWorker
class ApprovalAttachmentWorker @AssistedInject constructor(
    @Assisted context: Context,
    @Assisted params: WorkerParameters,
    private val api: MobileApi,
) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val approvalId = inputData.getLong(KEY_APPROVAL_ID, 0)
        val path = inputData.getString(KEY_FILE_PATH) ?: return Result.failure()
        val fileName = inputData.getString(KEY_FILE_NAME) ?: "attachment"
        val mime = inputData.getString(KEY_MIME) ?: "application/octet-stream"
        val file = File(path)
        if (approvalId <= 0 || !file.exists()) return Result.failure()
        return runCatching {
            val part = MultipartBody.Part.createFormData("file", fileName, file.asRequestBody(mime.toMediaTypeOrNull()))
            api.uploadApprovalAttachment(approvalId, part).close()
            file.delete()
            Result.success()
        }.getOrElse {
            if (runAttemptCount < 3) Result.retry() else Result.failure()
        }
    }

    companion object {
        const val KEY_APPROVAL_ID = "approval_id"
        const val KEY_FILE_PATH = "file_path"
        const val KEY_FILE_NAME = "file_name"
        const val KEY_MIME = "mime"
    }
}
