package com.echo.phone.ui.mine

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.echo.phone.EchoApplication

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
