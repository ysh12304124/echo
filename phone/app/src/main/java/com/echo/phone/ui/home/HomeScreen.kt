package com.echo.phone.ui.home

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.FiberManualRecord
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.echo.phone.EchoApplication
import com.echo.phone.data.glasses.GlassesConnection
import com.echo.phone.domain.*
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

class HomeViewModel(
    private val repo: com.echo.phone.data.EchoRepository,
    private val glasses: GlassesConnection,
    private val partitionFilter: DataPartition? = null,
) : ViewModel() {
    var memories by mutableStateOf<List<MemorySummary>>(emptyList())
        private set
    var loading by mutableStateOf(true)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    val deviceStatus = glasses.deviceStatus.stateIn(
        viewModelScope, SharingStarted.WhileSubscribed(5000),
        DeviceStatus(false),
    )

    init { refresh() }

    fun refresh() {
        viewModelScope.launch {
            loading = true
            try {
                memories = repo.listMemories(partitionFilter).sortedByDescending { it.startedAt }
                error = null
            } catch (e: Exception) {
                error = e.message
            }
            loading = false
        }
    }

    fun connectGlasses() {
        viewModelScope.launch {
            try { glasses.connect(); error = null }
            catch (e: Exception) { error = "连接失败: ${e.message}" }
        }
    }
}

private fun sceneColor(scene: TimeScene?): Color = when (scene) {
    TimeScene.MEETING -> Color(0xFF4C8DFF)
    TimeScene.ONSITE -> Color(0xFF34D399)
    TimeScene.QUALITY_TIME -> Color(0xFF8B7BFF)
    null -> Color(0xFF9FB0CC)
}

@Composable
fun HomeScreen(
    partitionFilter: DataPartition? = null,
    title: String = "识境 Echo",
    onNavigateMemory: (String) -> Unit,
    onNavigateSpace: (String) -> Unit,
) {
    val context = LocalContext.current
    val app = context.applicationContext as EchoApplication
    val vm: HomeViewModel = viewModel(
        factory = object : androidx.lifecycle.ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : ViewModel> create(cls: Class<T>): T =
                HomeViewModel(app.repository, app.glassesConnection, partitionFilter) as T
        }
    )
    val deviceStatus by vm.deviceStatus.collectAsState()

    LaunchedEffect(Unit) { app.recordingCompleted.collect { vm.refresh() } }

    Column(Modifier.fillMaxSize().padding(16.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text(title, style = MaterialTheme.typography.headlineMedium)
            IconButton(onClick = { vm.refresh() }) { Icon(Icons.Default.Refresh, "刷新") }
        }
        Spacer(Modifier.height(12.dp))

        // 设备状态
        Card(
            Modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer),
        ) {
            Column(Modifier.padding(16.dp)) {
                Text("设备状态", style = MaterialTheme.typography.titleSmall)
                Spacer(Modifier.height(4.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(
                        Icons.Default.FiberManualRecord, null,
                        tint = if (deviceStatus.connected) Color(0xFF34D399) else Color(0xFF9FB0CC),
                        modifier = Modifier.size(10.dp),
                    )
                    Spacer(Modifier.width(6.dp))
                    Text(
                        if (deviceStatus.connected) "已连接 · 电量 ${deviceStatus.batteryPercent}%"
                        else "未连接",
                        style = MaterialTheme.typography.bodyMedium,
                    )
                }
                if (deviceStatus.isRecordingTime || deviceStatus.isRecordingSpace) {
                    Spacer(Modifier.height(4.dp))
                    Text(
                        buildString {
                            if (deviceStatus.isRecordingTime) append("● 时间录制中  ")
                            if (deviceStatus.isRecordingSpace) append("◆ 空间采集中")
                        },
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.primary,
                    )
                }
                if (!deviceStatus.connected) {
                    Spacer(Modifier.height(8.dp))
                    TextButton(onClick = { vm.connectGlasses() }) { Text("连接眼镜") }
                }
            }
        }

        Spacer(Modifier.height(20.dp))
        Text("最近记忆", style = MaterialTheme.typography.titleMedium)

        when {
            vm.loading -> CircularProgressIndicator()
            vm.error != null -> Text("加载失败: ${vm.error}", color = MaterialTheme.colorScheme.error)
            vm.memories.isEmpty() -> Text("暂无记忆", color = MaterialTheme.colorScheme.onSurfaceVariant)
            else -> LazyColumn(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                items(vm.memories) { memory ->
                    MemoryCard(memory, onClick = { onNavigateMemory(memory.memoryId) })
                }
            }
        }
    }
}

@Composable
private fun MemoryCard(memory: MemorySummary, onClick: () -> Unit) {
    val accent = sceneColor(memory.scene)
    Card(
        Modifier.fillMaxWidth().clickable(onClick = onClick),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer),
    ) {
        Row {
            // 左侧场景色带
            Box(
                Modifier
                    .width(4.dp)
                    .fillMaxHeight()
                    .defaultMinSize(minHeight = 80.dp)
                    .clip(RoundedCornerShape(topStart = 16.dp, bottomStart = 16.dp))
                    .background(accent)
            )
            Column(Modifier.padding(16.dp).weight(1f)) {
                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        memory.title.ifEmpty { memory.identifyBrief }.ifEmpty { "未命名记忆" },
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.SemiBold,
                    )
                    if (memory.isFavorited) {
                        Icon(Icons.Default.Star, null, tint = Color(0xFFFFB300), modifier = Modifier.size(18.dp))
                    }
                }
                Spacer(Modifier.height(6.dp))
                Text(
                    buildString {
                        memory.startedAt?.let {
                            val date = it.substringBefore("T")
                            val t = it.substringAfter("T").substringBefore(".").substring(0, 5)
                            append("$date $t")
                        }
                        memory.scene?.let { append(" · ${it.name}") }
                        if (memory.durationSeconds > 0) append(" · ${memory.durationSeconds}s")
                    },
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (memory.identifyBrief.isNotEmpty()) {
                    Spacer(Modifier.height(4.dp))
                    Text(
                        memory.identifyBrief,
                        style = MaterialTheme.typography.bodyMedium,
                        maxLines = 2,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                }
            }
        }
    }
}
