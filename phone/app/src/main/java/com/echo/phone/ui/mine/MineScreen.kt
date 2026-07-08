package com.echo.phone.ui.mine

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.echo.phone.EchoApplication

@Composable
fun MineScreen(
    onNavigatePersons: () -> Unit,
    onNavigateQualityTime: () -> Unit,
    onNavigateSpaces: () -> Unit = {},
    onNavigateDevice: () -> Unit = {},
    onNavigateStorage: () -> Unit = {},
    onNavigateHelp: () -> Unit = {},
) {
    val context = LocalContext.current
    val app = context.applicationContext as EchoApplication
    val deviceStatus by app.glassesConnection.deviceStatus.collectAsState()

    Column(Modifier.fillMaxSize().padding(16.dp)) {
        Text("我的", style = MaterialTheme.typography.headlineMedium)
        Spacer(Modifier.height(16.dp))

        MineItem("设备管理", if (deviceStatus.connected) "已连接" else "未连接") { onNavigateDevice() }
        MineItem("人物库", "跨记忆人物") { onNavigatePersons() }
        MineItem("空间库", "空间记忆列表") { onNavigateSpaces() }
        MineItem("时间记忆分区", "Quality Time 独立数据") { onNavigateQualityTime() }
        MineItem("存储与隐私", "删除、导出、权限") { onNavigateStorage() }
        MineItem("帮助说明", "LED 含义、查询范围") { onNavigateHelp() }
    }
}

@Composable
private fun MineItem(title: String, subtitle: String, onClick: () -> Unit) {
    Card(
        Modifier.fillMaxWidth().padding(vertical = 4.dp).clickable(onClick = onClick),
    ) {
        Row(
            Modifier.padding(16.dp).fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Column {
                Text(title, style = MaterialTheme.typography.titleSmall)
                Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null)
        }
    }
}
