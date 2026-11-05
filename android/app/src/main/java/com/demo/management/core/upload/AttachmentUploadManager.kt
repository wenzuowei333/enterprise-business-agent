package com.demo.management.core.upload

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.net.Uri
import androidx.exifinterface.media.ExifInterface
import androidx.work.Constraints
import androidx.work.Data
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.util.UUID
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class AttachmentUploadManager @Inject constructor(@ApplicationContext private val context: Context) {
    suspend fun enqueue(approvalId: Long, uri: Uri): UUID = withContext(Dispatchers.IO) {
        val resolver = context.contentResolver
        val mime = resolver.getType(uri) ?: "application/octet-stream"
        val displayName = uri.lastPathSegment?.substringAfterLast('/')?.takeIf { it.isNotBlank() } ?: "attachment"
        val directory = File(context.filesDir, "pending_uploads").apply { mkdirs() }
        val copied = File(directory, "${UUID.randomUUID()}_${displayName}")
        resolver.openInputStream(uri).use { input ->
            requireNotNull(input) { "无法读取所选文件" }
            copied.outputStream().use(input::copyTo)
        }
        val uploadFile = if (mime.startsWith("image/") && copied.length() > 2L * 1024 * 1024) compressImage(copied) else copied
        val request = OneTimeWorkRequestBuilder<ApprovalAttachmentWorker>()
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .setInputData(
                Data.Builder()
                    .putLong(ApprovalAttachmentWorker.KEY_APPROVAL_ID, approvalId)
                    .putString(ApprovalAttachmentWorker.KEY_FILE_PATH, uploadFile.absolutePath)
                    .putString(ApprovalAttachmentWorker.KEY_FILE_NAME, displayName)
                    .putString(ApprovalAttachmentWorker.KEY_MIME, if (uploadFile.extension == "jpg") "image/jpeg" else mime)
                    .build()
            )
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork("approval_attachment_${approvalId}_${request.id}", ExistingWorkPolicy.KEEP, request)
        request.id
    }

    private fun compressImage(source: File): File {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(source.absolutePath, bounds)
        var sample = 1
        while (bounds.outWidth / sample > 2048 || bounds.outHeight / sample > 2048) sample *= 2
        val bitmap = BitmapFactory.decodeFile(source.absolutePath, BitmapFactory.Options().apply { inSampleSize = sample }) ?: return source
        val orientation = runCatching { ExifInterface(source).rotationDegrees }.getOrDefault(0)
        val outputBitmap = if (orientation == 0) bitmap else Bitmap.createBitmap(
            bitmap,
            0,
            0,
            bitmap.width,
            bitmap.height,
            Matrix().apply { postRotate(orientation.toFloat()) },
            true,
        )
        val target = File(source.parentFile, "${source.nameWithoutExtension}.jpg")
        target.outputStream().use { outputBitmap.compress(Bitmap.CompressFormat.JPEG, 84, it) }
        if (outputBitmap !== bitmap) outputBitmap.recycle()
        bitmap.recycle()
        if (target.exists()) source.delete()
        return target.takeIf { it.exists() } ?: source
    }
}
