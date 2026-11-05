package com.demo.management.core.ui

import android.app.Activity
import android.app.KeyguardManager
import android.content.Context
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import com.demo.designsystem.components.LiquidActionButton as Button
import com.demo.designsystem.components.ContentSection as Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

@Composable
fun OfflineAccessGuard(
    offline: Boolean,
    content: @Composable () -> Unit,
) {
    val context = LocalContext.current
    val keyguard = remember { context.getSystemService(Context.KEYGUARD_SERVICE) as KeyguardManager }
    var unlocked by remember { mutableStateOf(!offline) }
    var message by remember { mutableStateOf<String?>(null) }
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        unlocked = result.resultCode == Activity.RESULT_OK
        if (!unlocked) message = "未完成设备身份验证，离线客户资料保持锁定。"
    }
    LaunchedEffect(offline) {
        if (!offline) unlocked = true
        if (offline) unlocked = false
    }
    if (!offline || unlocked) {
        Column(modifier = Modifier.fillMaxSize()) {
            if (offline) {
                Text(
                    "当前为离线数据，联网后将自动校验权限并更新。",
                    color = MaterialTheme.colorScheme.tertiary,
                    modifier = Modifier.fillMaxWidth().padding(bottom = 8.dp),
                )
            }
            content()
        }
        return
    }
    Column(
        modifier = Modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.Center,
    ) {
        Card(modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("验证后查看离线资料", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                Text("离线客户和任务包含业务资料，需要使用手机锁屏凭据确认本人操作。")
                message?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                Button(
                    onClick = {
                        if (!keyguard.isDeviceSecure) {
                            message = "请先为手机设置锁屏密码、图案或生物识别。"
                            return@Button
                        }
                        val intent = keyguard.createConfirmDeviceCredentialIntent("验证身份", "查看星河演示管理中心离线资料")
                        if (intent == null) message = "无法启动设备身份验证，请联网后重试。" else launcher.launch(intent)
                    },
                    modifier = Modifier.fillMaxWidth(),
                ) { Text("验证身份") }
            }
        }
    }
}
