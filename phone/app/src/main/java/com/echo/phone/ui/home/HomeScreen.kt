package com.echo.phone.ui.home

import androidx.compose.animation.*
import androidx.compose.animation.core.*
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.FiberManualRecord
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.*
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.echo.phone.EchoApplication
import com.echo.phone.data.glasses.GlassesConnection
import com.echo.phone.domain.*
import kotlinx.coroutines.delay
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

    val deviceStatus = glasses.deviceStatus.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), DeviceStatus(false))

    init { refresh() }

    fun refresh() {
        viewModelScope.launch {
            isRefreshing = true
            try { memories = repo.listMemories(partitionFilter).sortedByDescending { it.startedAt }; error = null }
            catch (e: Exception) { error = e.message }
            // 最小刷新动画时长 600ms，让用户感知到刷新
            delay(600)
            isRefreshing = false
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

private val GlassBg = Brush.verticalGradient(listOf(Color(0xFFFFFFFF), Color(0xFFF8F9FC), Color(0xFFF3F4F8)))
private val GlassBgElevated = Brush.verticalGradient(listOf(Color(0xFFF9FAFC), Color(0xFFF2F4F9), Color(0xFFEEF1F6)))
private val GlassBorder = Color(0xFFE2E4EA)
private val GlassBorderElevated = Color(0xFFD1D5DC)

private fun sceneAccent(scene: TimeScene?): Color = when (scene) {
    TimeScene.MEETING -> Color(0xFF3B82F6)
    TimeScene.ONSITE -> Color(0xFF10B981)
    TimeScene.QUALITY_TIME -> Color(0xFF8B5CF6)
    null -> Color(0xFF9CA3AF)
}
private val MonoFont = FontFamily.Monospace

@Composable
private fun RecordingDot(isActive: Boolean) {
    val t = rememberInfiniteTransition(label = "pulse")
    val a by t.animateFloat(0.3f, 1f, infiniteRepeatable(tween(900, easing = EaseInOutCubic), RepeatMode.Reverse), label = "pulseA")
    Box(Modifier.size(6.dp).alpha(if (isActive) a else 0.3f).clip(CircleShape).background(if (isActive) Color(0xFFEF4444) else Color(0xFFD1D5DB)))
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SkeletonCard() {
    val t = rememberInfiniteTransition(label = "shimmer")
    val tx by t.animateFloat(0f, 800f, infiniteRepeatable(tween(1400, easing = LinearEasing), RepeatMode.Restart), label = "sx")
    Card(Modifier.fillMaxWidth().height(100.dp).border(1.dp, GlassBorder, RoundedCornerShape(18.dp)), colors = CardDefaults.cardColors(containerColor = Color.Transparent)) {
        Box(Modifier.fillMaxSize().background(Brush.linearGradient(listOf(Color(0xFFF8F9FC), Color(0xFFE8EAF0), Color(0xFFF8F9FC)), start = Offset(tx - 200f, 0f), end = Offset(tx, 0f))))
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(
    partitionFilter: DataPartition? = null, title: String = "识境 Echo",
    onNavigateMemory: (String) -> Unit, onNavigateSpace: (String) -> Unit,
) {
    val context = LocalContext.current
    val app = context.applicationContext as EchoApplication
    val vm: HomeViewModel = viewModel(factory = object : androidx.lifecycle.ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(cls: Class<T>): T = HomeViewModel(app.repository, app.glassesConnection, partitionFilter) as T
    })
    val ds by vm.deviceStatus.collectAsState()
    // 录制完成自动刷新
    LaunchedEffect(Unit) { app.recordingCompleted.collect { vm.refresh() } }

    val isRec = ds.isRecordingTime || ds.isRecordingSpace

    Column(Modifier.fillMaxSize().padding(horizontal = 20.dp).padding(top = 20.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            Text(title, style = MaterialTheme.typography.headlineMedium, color = MaterialTheme.colorScheme.onSurface)
        }
        Spacer(Modifier.height(12.dp))

        // 设备状态 — 眼镜连接状态自动通过 StateFlow 刷新
        Box(Modifier.fillMaxWidth().shadow(8.dp, RoundedCornerShape(18.dp)).clip(RoundedCornerShape(18.dp)).background(GlassBgElevated).border(1.dp, GlassBorderElevated, RoundedCornerShape(18.dp)).padding(16.dp)) {
            Column {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    RecordingDot(isRec)
                    Spacer(Modifier.width(10.dp))
                    Text(if (ds.connected) "眼镜已连接 · 电量 ${ds.batteryPercent}%" else "未连接", style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
                    if (!ds.connected) FilledTonalButton(onClick = { vm.connectGlasses() }, modifier = Modifier.height(34.dp)) { Text("连接") }
                }
                if (isRec) {
                    Spacer(Modifier.height(8.dp))
                    if (ds.isRecordingTime) Text("● 时间录制中", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary)
                    if (ds.isRecordingSpace) Text("◆ 空间采集中", style = MaterialTheme.typography.labelSmall, color = Color(0xFF10B981))
                }
            }
        }

        Spacer(Modifier.height(24.dp))
        Text("最近记忆", style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.onSurface)

        // 下拉刷新
        PullToRefreshBox(
            isRefreshing = vm.isRefreshing,
            onRefresh = { vm.refresh() },
        ) {
            AnimatedContent(
                targetState = when { vm.loading && !vm.isRefreshing -> "loading"; vm.memories.isEmpty() && !vm.isRefreshing -> "empty"; vm.error != null -> "error"; else -> "list" },
                transitionSpec = { fadeIn(tween(200)) togetherWith fadeOut(tween(150)) },
                label = "home",
            ) { state ->
                when (state) {
                    "loading" -> Column(verticalArrangement = Arrangement.spacedBy(12.dp)) { repeat(3) { SkeletonCard() } }
                    "empty" -> Box(Modifier.fillMaxWidth().padding(48.dp), contentAlignment = Alignment.Center) {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            Text("⏳", style = MaterialTheme.typography.headlineLarge)
                            Text("暂无记忆", style = MaterialTheme.typography.bodyLarge, color = Color(0xFF6B7280))
                            Text("戴上眼镜，选择场景后开始记录", style = MaterialTheme.typography.bodySmall, color = Color(0xFF6B7280))
                        }
                    }
                    "error" -> Column {
                        Text("加载失败: ${vm.error}", color = MaterialTheme.colorScheme.error)
                        TextButton(onClick = { vm.refresh() }) { Text("重试") }
                    }
                    else -> LazyColumn(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                        items(vm.memories) { memory -> MemoryCard(memory) { onNavigateMemory(memory.memoryId) } }
                    }
                }
            }
        }
    }
}

@Composable
private fun MemoryCard(memory: MemorySummary, onClick: () -> Unit) {
    var pressed by remember { mutableStateOf(false) }
    val scale by animateFloatAsState(if (pressed) 0.98f else 1f, tween(120), label = "cardScale")
    val accent = sceneAccent(memory.scene)
    Card(
        Modifier.fillMaxWidth().scale(scale).shadow(4.dp, RoundedCornerShape(18.dp)).clip(RoundedCornerShape(18.dp)).clickable { onClick() },
        colors = CardDefaults.cardColors(containerColor = Color.Transparent),
    ) {
        Box(Modifier.background(GlassBg).border(1.dp, GlassBorder, RoundedCornerShape(18.dp))) {
            Row {
                Box(Modifier.width(3.dp).fillMaxHeight().defaultMinSize(minHeight = 88.dp).clip(RoundedCornerShape(topStart = 18.dp, bottomStart = 18.dp)).background(accent.copy(alpha = 0.6f)))
                Column(Modifier.padding(16.dp).weight(1f)) {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                        Text(memory.title.ifEmpty { memory.identifyBrief }.ifEmpty { "未命名记忆" }, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                        if (memory.isFavorited) Icon(Icons.Default.Star, null, tint = Color(0xFFF59E0B), modifier = Modifier.size(16.dp))
                    }
                    Spacer(Modifier.height(6.dp))
                    Text(
                        buildString {
                            memory.startedAt?.let { append(it.substring(0, 10) + " " + it.substring(11, 16)) }
                            memory.scene?.let { append("  ${it.name}") }
                            if (memory.durationSeconds > 0) append("  ${memory.durationSeconds}s")
                        },
                        style = MaterialTheme.typography.labelMedium.copy(fontFamily = MonoFont), color = Color(0xFF6B7280),
                    )
                    if (memory.identifyBrief.isNotEmpty()) {
                        Spacer(Modifier.height(8.dp))
                        Text(memory.identifyBrief, style = MaterialTheme.typography.bodyMedium, maxLines = 2, color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.85f))
                    }
                }
            }
        }
    }
}
