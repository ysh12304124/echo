package com.echo.phone.ui.mine

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.unit.dp
import com.echo.phone.EchoApplication
import com.echo.phone.util.EchoLog

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun InfoScaffold(title: String, onBack: () -> Unit, content: @Composable ColumnScope.() -> Unit) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(title) },
                navigationIcon = {
                    IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "返回") }
                },
            )
        },
    ) { padding ->
        Column(
            Modifier.fillMaxSize().padding(padding).padding(16.dp).verticalScroll(rememberScrollState()),
            content = content,
        )
    }
}

@Composable
fun DeviceScreen(onBack: () -> Unit) {
    val context = LocalContext.current
    val app = context.applicationContext as EchoApplication
    val status by app.glassesConnection.deviceStatus.collectAsState()
    val connState by app.glassesConnection.connectionState.collectAsState()

    InfoScaffold("设备管理", onBack) {
        ListItem(
            headlineContent = { Text("连接状态") },
            supportingContent = { Text(if (status.connected) "已连接" else "未连接") },
        )
        ListItem(
            headlineContent = { Text("电量") },
            supportingContent = { Text("${status.batteryPercent}%") },
        )
        ListItem(
            headlineContent = { Text("当前状态") },
            supportingContent = { Text(connState.name) },
        )
    }
}

@Composable
fun HelpScreen(onBack: () -> Unit) {
    InfoScaffold("帮助说明", onBack) {
        Text("LED 指示灯", style = MaterialTheme.typography.titleMedium)
        Text("· 白灯常亮：待机")
        Text("· 蓝灯常亮：录制中")
        Text("· 蓝灯呼吸：上传 / 处理中")
        Text("· 红灯：异常（连接断开 / 存储不足）")
        Spacer(Modifier.height(16.dp))
        Text("查询范围", style = MaterialTheme.typography.titleMedium)
        Text("· 全局工作：跨所有工作记忆检索（不含 Quality Time）")
        Text("· 指定记忆：仅在某段记忆内检索")
        Text("· 指定空间：仅在某个空间及其关联记忆内检索")
        Spacer(Modifier.height(16.dp))
        Text("结果状态", style = MaterialTheme.typography.titleMedium)
        Text("· 确定答案：有高置信证据支撑")
        Text("· 可能相关：证据置信度不足，仅供参考")
        Text("· 没有找到：无相关证据，不臆测")
    }
}

@Composable
fun StorageScreen(onBack: () -> Unit) {
    InfoScaffold("存储与隐私", onBack) {
        Text("数据分区", style = MaterialTheme.typography.titleMedium)
        Text("Quality Time 记忆与工作数据物理隔离，全局工作查询不会触及。")
        Spacer(Modifier.height(16.dp))
        Text("导出", style = MaterialTheme.typography.titleMedium)
        Text("查询结果可在结果页导出为带证据的记录，便于存档与分享。")
        Spacer(Modifier.height(16.dp))
        Text("删除", style = MaterialTheme.typography.titleMedium)
        Text("删除记忆将级联清理其媒体文件与检索索引，且不可恢复。锁定的记忆需先解锁。")
    }
}

@Composable
fun DiagnosticsLogScreen(onBack: () -> Unit) {
    val clipboard = LocalClipboardManager.current
    var logs by remember { mutableStateOf(EchoLog.recentLines()) }
    val path = EchoLog.logFilePath()
    val packageName = LocalContext.current.packageName
    val logcatCommand = "adb logcat -s ${EchoLog.TAG}:V AndroidRuntime:E"
    val pullCommand = "adb pull /sdcard/Android/data/$packageName/files/echo_phone.log ./echo_phone.log"

    fun refresh() {
        logs = EchoLog.recentLines()
    }

    InfoScaffold("诊断日志", onBack) {
        Text("日志位置", style = MaterialTheme.typography.titleMedium)
        Text(path, style = MaterialTheme.typography.bodySmall)
        Spacer(Modifier.height(12.dp))

        Text("查看命令", style = MaterialTheme.typography.titleMedium)
        Text("实时日志：", style = MaterialTheme.typography.labelMedium)
        Text(logcatCommand, style = MaterialTheme.typography.bodySmall)
        Spacer(Modifier.height(6.dp))
        Text("导出文件：", style = MaterialTheme.typography.labelMedium)
        Text(pullCommand, style = MaterialTheme.typography.bodySmall)
        Spacer(Modifier.height(12.dp))

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = { clipboard.setText(AnnotatedString("$logcatCommand\n$pullCommand")) }) {
                Icon(Icons.Default.ContentCopy, null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(6.dp))
                Text("复制命令")
            }
            OutlinedButton(onClick = { refresh() }) {
                Icon(Icons.Default.Refresh, null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(6.dp))
                Text("刷新")
            }
            OutlinedButton(onClick = { EchoLog.clear(); refresh() }) {
                Icon(Icons.Default.Delete, null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(6.dp))
                Text("清空")
            }
        }

        Spacer(Modifier.height(16.dp))
        Text("最近日志", style = MaterialTheme.typography.titleMedium)
        Spacer(Modifier.height(8.dp))
        Surface(color = MaterialTheme.colorScheme.surfaceVariant, shape = MaterialTheme.shapes.small) {
            Text(
                logs,
                modifier = Modifier.fillMaxWidth().padding(12.dp),
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}
