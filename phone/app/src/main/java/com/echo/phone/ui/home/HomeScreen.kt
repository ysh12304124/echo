package com.echo.phone.ui.home

import android.content.Context
import android.view.HapticFeedbackConstants
import androidx.compose.animation.*
import androidx.compose.animation.core.*
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
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
import androidx.compose.ui.platform.LocalView
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
    var revealNew by mutableStateOf(false)
        private set

    val deviceStatus = glasses.deviceStatus.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), DeviceStatus(false))
    init { refresh() }

    fun refresh() {
        viewModelScope.launch {
            isRefreshing = true
            try { memories = repo.listMemories(partitionFilter).sortedByDescending { it.startedAt }; error = null }
            catch (e: Exception) { error = e.message }
            delay(600); isRefreshing = false; loading = false
        }
    }

    fun refreshWithReveal() {
        viewModelScope.launch {
            isRefreshing = true; revealNew = true
            try { memories = repo.listMemories(partitionFilter).sortedByDescending { it.startedAt } }
            catch (e: Exception) { error = e.message }
            delay(800); isRefreshing = false; loading = false
            delay(600); revealNew = false
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
private val TimelineGray = Color(0xFFE5E7EB)

// ── 呼吸灯 — 录制指示器 ──
@Composable
private fun BreathingDot(isActive: Boolean) {
    val t = rememberInfiniteTransition(label = "breath")
    val scale by t.animateFloat(0.6f, 1.4f, infiniteRepeatable(tween(1200, easing = EaseInOutCubic), RepeatMode.Reverse), label = "s")
    val alpha by t.animateFloat(0.4f, 1f, infiniteRepeatable(tween(1200, easing = EaseInOutCubic), RepeatMode.Reverse), label = "a")
    Box(
        Modifier
            .size(8.dp)
            .scale(if (isActive) scale else 1f)
            .alpha(if (isActive) alpha else 0.3f)
            .clip(CircleShape)
            .background(if (isActive) Color(0xFFEF4444) else Color(0xFFD1D5DB))
    )
}

// ── 骨架 ──
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
    val view = LocalView.current

    // 录制完成 → 带揭晓动画的刷新
    LaunchedEffect(Unit) {
        app.recordingCompleted.collect { vm.refreshWithReveal() }
    }

    val isRec = ds.isRecordingTime || ds.isRecordingSpace

    // 录制开始 → 震动
    LaunchedEffect(isRec) {
        if (isRec) view.performHapticFeedback(HapticFeedbackConstants.LONG_PRESS)
    }

    Column(Modifier.fillMaxSize().padding(horizontal = 20.dp).padding(top = 20.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            Text(title, style = MaterialTheme.typography.headlineMedium, color = MaterialTheme.colorScheme.onSurface)
        }
        Spacer(Modifier.height(12.dp))

        // 设备状态
        Box(Modifier.fillMaxWidth().shadow(8.dp, RoundedCornerShape(18.dp)).clip(RoundedCornerShape(18.dp)).background(GlassBgElevated).border(1.dp, GlassBorderElevated, RoundedCornerShape(18.dp)).padding(16.dp)) {
            Column {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    BreathingDot(isRec)
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

        PullToRefreshBox(isRefreshing = vm.isRefreshing, onRefresh = { vm.refresh() }) {
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
                        }
                    }
                    "error" -> Column { Text("加载失败: ${vm.error}", color = MaterialTheme.colorScheme.error); TextButton(onClick = { vm.refresh() }) { Text("重试") } }
                    else -> LazyColumn(verticalArrangement = Arrangement.spacedBy(0.dp)) {
                        var lastDate = ""
                        vm.memories.forEachIndexed { i, memory ->
                            val thisDate = memory.startedAt?.substring(0, 10) ?: ""
                            val isNewDate = thisDate.isNotEmpty() && thisDate != lastDate
                            if (isNewDate) lastDate = thisDate
                            item(key = memory.memoryId) {
                                if (isNewDate) TimelineDateLabel(thisDate)
                                val isFirst = i == 0
                                TimelineItem(i, vm.memories.size, vm.revealNew && isFirst, isNewDate && isFirst) {
                                    MemoryCard(memory) { onNavigateMemory(memory.memoryId) }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

// ── 时间轴节点 + 揭晓动画 ──
@Composable
private fun TimelineItem(index: Int, total: Int, reveal: Boolean, isDateHead: Boolean, content: @Composable () -> Unit) {
    val isFirst = index == 0
    val isLast = index == total - 1
    Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min)) {
        // 时间轴线
        Box(Modifier.width(24.dp).fillMaxHeight(), contentAlignment = Alignment.TopCenter) {
            // 上方连线
            if (!isFirst && !isDateHead) {
                Box(Modifier.width(2.dp).height(12.dp).background(TimelineGray))
            }
            Spacer(Modifier.height(12.dp))
            // 节点圆点
            Box(Modifier.size(8.dp).clip(CircleShape).background(if (isFirst) sceneAccent(null) else TimelineGray))
            // 下方连线
            if (!isLast) {
                Box(Modifier.width(2.dp).fillMaxHeight().padding(top = 8.dp).background(TimelineGray))
            }
        }
        Spacer(Modifier.width(8.dp))
        // 卡片内容 — 揭晓动画
        Box(Modifier.weight(1f).padding(vertical = 6.dp)) {
            androidx.compose.animation.AnimatedVisibility(
                visible = true,
                enter = if (reveal) expandVertically(spring(dampingRatio = 0.6f, stiffness = 300f)) + fadeIn(tween(300)) else fadeIn(tween(200)),
            ) { content() }
        }
    }
}

@Composable
private fun TimelineDateLabel(date: String) {
    Row(Modifier.fillMaxWidth().padding(start = 24.dp).padding(top = 16.dp, bottom = 4.dp)) {
        Text(date, style = MaterialTheme.typography.labelMedium, color = Color(0xFF9CA3AF), fontWeight = FontWeight.Medium)
    }
}

@Composable
private fun MemoryCard(memory: MemorySummary, onClick: () -> Unit) {
    val accent = sceneAccent(memory.scene)
    Card(
        Modifier.fillMaxWidth().shadow(4.dp, RoundedCornerShape(18.dp)).clip(RoundedCornerShape(18.dp)).clickable { onClick() },
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
