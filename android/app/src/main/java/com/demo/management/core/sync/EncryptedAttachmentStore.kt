package com.demo.management.core.sync

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import com.demo.management.data.MobileApi
import com.demo.management.data.local.OfflineAttachmentDao
import com.demo.management.data.local.OfflineAttachmentEntity
import dagger.hilt.android.qualifiers.ApplicationContext
import java.io.File
import java.security.KeyStore
import java.util.UUID
import javax.crypto.Cipher
import javax.crypto.CipherInputStream
import javax.crypto.CipherOutputStream
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import javax.inject.Inject
import javax.inject.Singleton
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.asRequestBody

@Singleton
class EncryptedAttachmentStore @Inject constructor(
    @ApplicationContext private val context: Context,
    private val dao: OfflineAttachmentDao,
    private val api: MobileApi,
) {
    suspend fun storeAll(operationId: String, uris: List<Uri>) {
        uris.distinct().take(10).forEach { store(operationId, it) }
    }

    suspend fun uploadForApproval(operationId: String, approvalId: Long): Boolean {
        var allUploaded = true
        dao.forOperation(operationId).filter { it.status in setOf("pending", "failed") }.forEach { row ->
            val source = File(row.encryptedPath)
            val plain = File.createTempFile("mobile-attachment-", ".upload", context.cacheDir)
            try {
                decrypt(source, plain)
                dao.updateStatus(row.id, "uploading")
                val body = plain.asRequestBody(row.mimeType?.toMediaTypeOrNull())
                api.uploadApprovalAttachment(approvalId, MultipartBody.Part.createFormData("file", row.displayName, body)).close()
                source.delete()
                dao.delete(row.id)
            } catch (_: Throwable) {
                allUploaded = false
                dao.updateStatus(row.id, "failed")
            } finally {
                plain.delete()
            }
        }
        return allUploaded
    }

    suspend fun pending(): List<OfflineAttachmentEntity> = dao.pending()

    suspend fun deleteForOperation(operationId: String) {
        dao.forOperation(operationId).forEach { File(it.encryptedPath).delete() }
        dao.deleteForOperation(operationId)
    }

    fun clearFiles() {
        File(context.filesDir, "offline_attachments").deleteRecursively()
        File(context.cacheDir, "mobile-attachment-").deleteRecursively()
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        if (store.containsAlias(KEY_ALIAS)) store.deleteEntry(KEY_ALIAS)
    }

    private suspend fun store(operationId: String, uri: Uri) {
        val resolver = context.contentResolver
        val metadata = resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { cursor ->
            if (!cursor.moveToFirst()) null else Pair(
                cursor.getString(cursor.getColumnIndexOrThrow(OpenableColumns.DISPLAY_NAME)),
                cursor.getLong(cursor.getColumnIndexOrThrow(OpenableColumns.SIZE)),
            )
        }
        val displayName = metadata?.first ?: "attachment-${System.currentTimeMillis()}"
        val size = metadata?.second ?: 0L
        require(size <= MAX_BYTES || size == 0L) { "单个附件不能超过 30MB" }
        val id = UUID.randomUUID().toString()
        val directory = File(context.filesDir, "offline_attachments").apply { mkdirs() }
        val target = File(directory, "$id.bin")
        val cipher = Cipher.getInstance(TRANSFORMATION).apply { init(Cipher.ENCRYPT_MODE, encryptionKey()) }
        target.outputStream().use { output ->
            output.write(cipher.iv.size)
            output.write(cipher.iv)
            CipherOutputStream(output, cipher).use { encrypted ->
                resolver.openInputStream(uri)?.use { input -> input.copyTo(encrypted) }
                    ?: error("无法读取附件")
            }
        }
        dao.save(
            OfflineAttachmentEntity(
                id = id,
                operationId = operationId,
                encryptedPath = target.absolutePath,
                displayName = displayName,
                mimeType = resolver.getType(uri),
                sizeBytes = size,
            )
        )
    }

    private fun decrypt(source: File, target: File) {
        source.inputStream().use { input ->
            val ivSize = input.read()
            require(ivSize in 12..32) { "附件加密数据损坏" }
            val iv = ByteArray(ivSize)
            require(input.read(iv) == ivSize) { "附件加密数据损坏" }
            val cipher = Cipher.getInstance(TRANSFORMATION).apply {
                init(Cipher.DECRYPT_MODE, encryptionKey(), GCMParameterSpec(128, iv))
            }
            CipherInputStream(input, cipher).use { decrypted -> target.outputStream().use(decrypted::copyTo) }
        }
    }

    private fun encryptionKey(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance("AES", "AndroidKeyStore").apply {
            init(
                android.security.keystore.KeyGenParameterSpec.Builder(
                    KEY_ALIAS,
                    android.security.keystore.KeyProperties.PURPOSE_ENCRYPT or android.security.keystore.KeyProperties.PURPOSE_DECRYPT,
                ).setBlockModes(android.security.keystore.KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(android.security.keystore.KeyProperties.ENCRYPTION_PADDING_NONE)
                    .build()
            )
        }.generateKey()
    }

    private companion object {
        const val KEY_ALIAS = "demo_mobile_offline_attachments"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val MAX_BYTES = 20L * 1024L * 1024L
    }
}
