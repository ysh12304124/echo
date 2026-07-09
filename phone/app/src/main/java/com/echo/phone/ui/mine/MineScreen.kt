package com.echo.phone.ui.mine

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.echo.phone.EchoApplication

private val GlassBg = Brush.verticalGradient(
    listOf(Color.White.copy(alpha = 0.08f), Color.White.copy(alpha = 0.04f))
)
private val GlassBorder = Color.White.copy(alpha = 0.10f)

@Composable
fun MineScreen(
    onNavigatePersons: () -> Unit,
    onNavigateSpaces: () -> Unit,
    onNavigateQualityTime: () -> Unit,
    onNavigateDevice: () -> Unit,
    onNavigateStorage: () -> Unit,
    onNavigateHelp: () -> Unit,
) {
    val context = LocalContext.current
    val app = context.applicationContext as EchoApplication
    val deviceStatus by app.glassesConnection.deviceStatus.collectAsState()

    Column(Modifier.fillMaxSize().padding(horizontal = 20.dp).padding(top = 20.dp)) {
        Text("我的", style = MaterialTheme.typography.headlineMedium, color = MaterialTheme.colorScheme.onSurface)
        Spacer(Modifier.height(18.dp))

        GlassSection {
            MineItem(Icons.Default.Devices, "设备管理", if (deviceStatus.connected) "已连接 · ${deviceStatus.batteryPercent}%" else "未连接", onClick = onNavigateDevice)
            HorizontalDivider(color = GlassBorder)
            MineItem(Icons.Default.Person, "人物库", "跨记忆人物管理", onClick = onNavigatePersons)
            HorizontalDivider(color = GlassBorder)
            MineItem(Icons.Default.ViewInAr, "空间库", "空间记忆与 3D 查看", onClick = onNavigateSpaces)
            HorizontalDivider(color = GlassBorder)
            MineItem(Icons.Default.Folder, "时间记忆分区", "Quality Time 独立数据", onClick = onNavigateQualityTime)
        }

        Spacer(Modifier.height(16.dp))

        GlassSection {
            MineItem(Icons.Default.Storage, "存储与隐私", "删除、导出、权限管理", onClick = onNavigateStorage)
            HorizontalDivider(color = GlassBorder)
            MineItem(Icons.Default.Help, "帮助说明", "LED 含义、查询范围说明", onClick = onNavigateHelp)
        }
    }
}

@Composable
private fun GlassSection(content: @Composable ColumnScope.() -> Unit) {
    Box(
        Modifier.fillMaxWidth().shadow(4.dp, RoundedCornerShape(18.dp)).clip(RoundedCornerShape(18.dp))
            .background(GlassBg).border(1.dp, GlassBorder, RoundedCornerShape(18.dp))
    ) {
        Column(Modifier.padding(4.dp), content = content)
    }
}

@Composable
private fun MineItem(icon: ImageVector, title: String, subtitle: String, onClick: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 18.dp, vertical = 16.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(icon, null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(22.dp))
        Spacer(Modifier.width(16.dp))
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.onSurface)
            Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null, tint = Color.White.copy(alpha = 0.3f), modifier = Modifier.size(18.dp))
    }
}
