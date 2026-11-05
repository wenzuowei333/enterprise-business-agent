package com.demo.management.data.round5

import android.content.Context
import android.net.Uri
import java.io.ByteArrayOutputStream
import java.io.InputStream
import dagger.hilt.android.qualifiers.ApplicationContext
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.toRequestBody
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class Round5Repository @Inject constructor(
    private val api: Round5Api,
    @ApplicationContext private val context: Context,
) {
    suspend fun myFeedback(): FeedbackPage = api.myFeedback()

    suspend fun createFeedback(payload: FeedbackCreate, screenshot: Uri?): FeedbackRow {
        val screenshotPath = if (screenshot == null) null else uploadScreenshot(screenshot)
        return api.createFeedback(payload.copy(screenshotPath = screenshotPath))
    }

    suspend fun adminFeedback(status: String? = null): FeedbackPage = api.adminFeedback(status)
    suspend fun updateFeedback(id: Long, status: String, resolution: String?): FeedbackRow = api.updateFeedback(id, FeedbackUpdate(status, resolution))
    suspend fun followupDraft(payload: AssistantDraftRequest) = api.followupDraft(payload)
    suspend fun approvalOpinionDraft(payload: AssistantDraftRequest) = api.approvalOpinionDraft(payload)
    suspend fun projectSummaryDraft(payload: AssistantDraftRequest) = api.projectSummaryDraft(payload)
    suspend fun adoptionOverview(days: Int = 7) = api.adoptionOverview(days)

    private suspend fun uploadScreenshot(uri: Uri): String {
        val resolver = context.contentResolver
        val image = resolver.openInputStream(uri)?.use(::readFeedbackImage) ?: error("无法读取反馈截图")
        val body = image.bytes.toRequestBody(image.contentType.toMediaTypeOrNull())
        val part = MultipartBody.Part.createFormData("file", "feedback.${image.extension}", body)
        return api.uploadFeedbackAttachment(part).screenshotPath
    }
}

internal data class FeedbackImagePayload(val bytes: ByteArray, val contentType: String, val extension: String)

internal fun readFeedbackImage(input: InputStream, maxBytes: Int = 5 * 1024 * 1024): FeedbackImagePayload {
    val output = ByteArrayOutputStream(minOf(maxBytes, 64 * 1024))
    val buffer = ByteArray(16 * 1024)
    var total = 0
    while (true) {
        val count = input.read(buffer)
        if (count < 0) break
        total += count
        require(total <= maxBytes) { "反馈截图不能超过 5MB" }
        output.write(buffer, 0, count)
    }
    val bytes = output.toByteArray()
    val format = when {
        bytes.size >= 3 && bytes[0] == 0xff.toByte() && bytes[1] == 0xd8.toByte() && bytes[2] == 0xff.toByte() -> "image/jpeg" to "jpg"
        bytes.size >= 8 && bytes.copyOfRange(0, 8).contentEquals(byteArrayOf(0x89.toByte(), 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a)) -> "image/png" to "png"
        bytes.size >= 12 && bytes.copyOfRange(0, 4).decodeToString() == "RIFF" && bytes.copyOfRange(8, 12).decodeToString() == "WEBP" -> "image/webp" to "webp"
        else -> throw IllegalArgumentException("反馈截图仅支持 JPG、PNG 或 WebP")
    }
    return FeedbackImagePayload(bytes, format.first, format.second)
}
