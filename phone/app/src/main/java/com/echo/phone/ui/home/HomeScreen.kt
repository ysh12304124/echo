package com.echo.phone.ui.home

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.FiberManualRecord
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.*
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
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
    var isRefreshing by mutableStateOf(false)
        private set

    val deviceStatus = glasses.deviceStatus.stateIn(
        viewModelScope, SharingStarted.WhileSubscribed(5000),
        DeviceStatus(false),
    )

    init {
        refresh()
        observeRecordingCompleted()
    }


    fun refresh() {
        viewModelScope.launch {
            loading = true
            isRefreshing = true
            try {
                memories = repo.listMemories(partitionFilter).sortedByDescending { it.startedAt }
                error = null
            } catch (e: Exception) {
                error = e.message
            }
            loading = false
            isRefreshing = false
        }
    }

    fun connectGlasses() {
        viewModelScope.launch {
            try {
                glasses.connect()
                error = null
            } catch (e: Exception) {
                error = "连接失败: ${e.message}"
            }
        }
    }
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

    // 录制完成后自动刷新
    LaunchedEffect(Unit) {
        app.recordingCompleted.collect { vm.refresh() }
    }

    Column(Modifier.fillMaxSize().padding(16.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text(title, style = MaterialTheme.typography.headlineMedium)
            IconButton(onClick = { vm.refresh() }) {
                Icon(Icons.Default.Refresh, "刷新")
            }
        }
        Spacer(Modifier.height(12.dp))

        // 设备状态
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp)) {
                Text("设备状态", style = MaterialTheme.typography.titleMedium)
                Text(
                    if (deviceStatus.connected) "已连接 · 电量 ${deviceStatus.batteryPercent}%"
                    else "未连接",
                )
                if (deviceStatus.isRecordingTime || deviceStatus.isRecordingSpace) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Default.FiberManualRecord, null, tint = MaterialTheme.colorScheme.error)
                        Spacer(Modifier.width(4.dp))
                        val states = buildList {
                            if (deviceStatus.isRecordingTime) add("时间录制中")
                            if (deviceStatus.isRecordingSpace) add("空间采集中")
                        }
                        Text(states.joinToString(" · "))
                    }
                }
                if (!deviceStatus.connected) {
                    TextButton(onClick = { vm.connectGlasses() }) { Text("连接眼镜") }
                }
                Spacer(Modifier.height(4.dp))
                Text(
                    "记忆的开始/结束由眼镜端控制：在眼镜内选择场景后启动，再次点击退出。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }

        Spacer(Modifier.height(16.dp))
        Text("最近记忆", style = MaterialTheme.typography.titleMedium)

        when {
            vm.loading && !vm.isRefreshing -> CircularProgressIndicator()
            vm.error != null -> Text("加载失败: ${vm.error}", color = MaterialTheme.colorScheme.error)
            vm.memories.isEmpty() -> Text("暂无记忆", color = MaterialTheme.colorScheme.onSurfaceVariant)
            else -> PullToRefreshBox(
                isRefreshing = vm.isRefreshing,
                onRefresh = { vm.refresh() },
            ) {
                LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    items(vm.memories) { memory ->
                        MemoryCard(memory, onClick = { onNavigateMemory(memory.memoryId) })
                    }
                }
            }
        }
    }
}

@Composable
private fun MemoryCard(memory: MemorySummary, onClick: () -> Unit) {
    Card(Modifier.fillMaxWidth().clickable(onClick = onClick)) {
        Column(Modifier.padding(16.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text(
                    memory.title.ifEmpty { memory.identifyBrief }.ifEmpty { "未命名记忆" },
                    style = MaterialTheme.typography.titleSmall,
                )
                if (memory.isFavorited) Icon(Icons.Default.Star, null, tint = MaterialTheme.colorScheme.primary)
            }
            Spacer(Modifier.height(4.dp))
            Text(
                buildString {
                    memory.startedAt?.let {
                        val date = it.substringBefore("T").substring(5); val t = it.substringAfter("T").substringBefore(".")
                        append(date + " "); if (t.length >= 5) append(t.substring(0, 5))
                    }
                    memory.scene?.let { append(" " + it.name) }
                    append(" · ")
                    append(memory.status.name)
                    if (memory.durationSeconds > 0) append(" · ${memory.durationSeconds}s")
                },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            if (memory.identifyBrief.isNotEmpty()) {
                Text(memory.identifyBrief, style = MaterialTheme.typography.bodyMedium)
            }
            Text("证据: ${memory.evidenceStatus}", style = MaterialTheme.typography.labelSmall)
        }
    }
}
