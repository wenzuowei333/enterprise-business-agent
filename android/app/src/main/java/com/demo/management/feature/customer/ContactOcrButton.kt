package com.demo.management.feature.customer

import android.Manifest
import android.content.pm.PackageManager
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.DocumentScanner
import androidx.compose.material.icons.outlined.CameraAlt
import com.demo.designsystem.components.LiquidDialog as AlertDialog
import com.demo.designsystem.components.LiquidActionButton as Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import com.demo.designsystem.components.LiquidOutlinedButton as OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import coil.compose.AsyncImage
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.chinese.ChineseTextRecognizerOptions
import java.io.File

@Composable
fun ContactOcrButton(
    currentValues: Map<String, String>,
    onApply: (Map<String, String>, Boolean) -> Unit,
) {
    val context = LocalContext.current
    var source by remember { mutableStateOf<Uri?>(null) }
    var candidates by remember { mutableStateOf<List<OcrFieldCandidate>>(emptyList()) }
    var selectedFields by remember { mutableStateOf<Set<String>>(emptySet()) }
    var processing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var cameraUri by remember { mutableStateOf<Uri?>(null) }
    var cameraFile by remember { mutableStateOf<File?>(null) }
    var overwriteValues by remember { mutableStateOf<Map<String, String>?>(null) }
    fun clearReview() {
        candidates = emptyList()
        selectedFields = emptySet()
        source = null
        cameraFile?.delete()
        cameraFile = null
        cameraUri = null
        overwriteValues = null
    }
    fun recognize(uri: Uri) {
        source = uri
        processing = true
        error = null
        val recognizer = TextRecognition.getClient(ChineseTextRecognizerOptions.Builder().build())
        runCatching { InputImage.fromFilePath(context, uri) }
            .onFailure {
                processing = false
                error = "无法读取名片图片，请重新选择"
                cameraFile?.delete()
                cameraFile = null
                source = null
                recognizer.close()
            }
            .onSuccess { image ->
                recognizer.process(image)
                    .addOnSuccessListener { result ->
                        val parsed = parseBusinessCardText(result.text)
                        candidates = parsed
                        selectedFields = emptySet()
                        if (parsed.isEmpty()) {
                            error = "没有识别到姓名、电话、地址或公司信息"
                            cameraFile?.delete()
                            cameraFile = null
                        }
                    }
                    .addOnFailureListener {
                        error = "名片识别失败，请换一张更清晰的图片"
                        cameraFile?.delete()
                        cameraFile = null
                    }
                    .addOnCompleteListener {
                        processing = false
                        recognizer.close()
                    }
            }
    }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        if (uri != null) {
            cameraFile?.delete()
            cameraFile = null
            cameraUri = null
            recognize(uri)
        }
    }
    val camera = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { success ->
        if (success) {
            cameraUri?.let(::recognize)
        } else {
            cameraFile?.delete()
            cameraFile = null
            cameraUri = null
        }
    }
    fun launchCamera() {
        val directory = File(context.cacheDir, "ocr_cards").also(File::mkdirs)
        val file = File.createTempFile("business-card-", ".jpg", directory)
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.files", file)
        cameraUri = uri
        cameraFile = file
        camera.launch(uri)
    }
    val cameraPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) launchCamera() else error = "未获得相机权限，可继续从相册选择名片"
    }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
        OutlinedButton(
            onClick = {
                if (ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
                    launchCamera()
                } else {
                    cameraPermission.launch(Manifest.permission.CAMERA)
                }
            },
            modifier = Modifier.weight(1f),
        ) {
            Icon(Icons.Outlined.CameraAlt, contentDescription = null)
            Text(" 拍摄名片")
        }
        OutlinedButton(onClick = { picker.launch("image/*") }, modifier = Modifier.weight(1f)) {
            Icon(Icons.Outlined.DocumentScanner, contentDescription = null)
            Text(" 选择图片")
        }
    }
    if (processing) {
        Row(modifier = Modifier.fillMaxWidth().padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            CircularProgressIndicator()
            Text("正在设备端识别名片")
        }
    }
    error?.let { Text(it, modifier = Modifier.padding(top = 6.dp)) }
    if (candidates.isNotEmpty() && overwriteValues == null) {
        AlertDialog(
            onDismissRequest = ::clearReview,
            title = { Text("确认回填字段") },
            text = {
                Column(modifier = Modifier.heightIn(max = 480.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    source?.let { AsyncImage(model = it, contentDescription = "名片预览", modifier = Modifier.fillMaxWidth().heightIn(max = 150.dp)) }
                    Text("只会回填勾选字段，保存前仍可继续修改。")
                    candidates.forEach { candidate ->
                        Row(modifier = Modifier.fillMaxWidth()) {
                            Checkbox(
                                checked = candidate.field in selectedFields,
                                onCheckedChange = { checked ->
                                    selectedFields = if (checked) selectedFields + candidate.field else selectedFields - candidate.field
                                },
                            )
                            Column(modifier = Modifier.padding(top = 8.dp)) {
                                Text(candidate.label, fontWeight = FontWeight.Bold)
                                val current = currentValues[candidate.field].orEmpty()
                                if (current.isNotBlank()) Text("当前：$current")
                                Text("识别：${candidate.value}")
                            }
                        }
                    }
                }
            },
            confirmButton = {
                Button(
                    onClick = {
                        val values = candidates.filter { it.field in selectedFields }.associate { it.field to it.value }
                        if (ocrOverwriteFields(currentValues, values).isEmpty()) {
                            onApply(values, false)
                            clearReview()
                        } else {
                            overwriteValues = values
                        }
                    },
                    enabled = selectedFields.isNotEmpty(),
                ) { Text("回填所选字段") }
            },
            dismissButton = { TextButton(onClick = ::clearReview) { Text("取消") } },
        )
    }
    overwriteValues?.let { values ->
        val labels = candidates.filter { it.field in ocrOverwriteFields(currentValues, values) }.joinToString("、") { it.label }
        AlertDialog(
            onDismissRequest = { overwriteValues = null },
            title = { Text("确认覆盖已有资料") },
            text = { Text("以下已有字段将被识别结果替换：$labels。请再次确认。") },
            confirmButton = {
                Button(onClick = { onApply(values, true); clearReview() }) { Text("确认覆盖") }
            },
            dismissButton = { TextButton(onClick = { overwriteValues = null }) { Text("返回核对") } },
        )
    }
}
