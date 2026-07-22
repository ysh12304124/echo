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
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.StarBorder
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

fun SpaceMemoryDetail.toMemorySummary() = MemorySummary(
    memoryId = spaceId,
    memoryType = MemoryType.SPACE,
    status = if (modelUrl.isNullOrBlank() || modelUrl.contains("placeholder")) MemoryStatus.PROCESSING else MemoryStatus.COMPLETED,
    identifyBrief = identifyBrief,
    title = title.ifBlank { "空间记忆" },
    scene = null,
    partition = partition,
    startedAt = capturedAt,
    durationSeconds = 0,
    evidenceStatus = quality ?: "pending",
    isFavorited = isFavorited,
)

class HomeViewModel(
    private val repo: com.echo.phone.data.EchoRepository,
    private val glasses: GlassesConnection,
    private val partitionFilter: DataPartition? = null,
) : ViewModel() {
    var memories by mutableStateOf<List<MemorySummary>>(emptyList())
    var loading by mutableStateOf(true)
        
    var error by mutableStateOf<String?>(null)
        
    var isRefreshing by mutableStateOf(false)
        
    var revealNew by mutableStateOf(false)
    var animatingDeleteId by mutableStateOf<String?>(null)
    var pendingDeleteId by mutableStateOf<String?>(null)  
        

    val deviceStatus = glasses.deviceStatus.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), DeviceStatus(false))
    init { refresh() }

    fun refresh() {
        viewModelScope.launch {
            isRefreshing = true
            try {
                val timeMemories = repo.listMemories(partitionFilter)
                val spaceMemories = repo.listSpaces(partitionFilter).map { it.toMemorySummary() }
                memories = (timeMemories + spaceMemories).sortedByDescending { it.startedAt ?: "" }
                error = null
            }
            catch (e: Exception) { error = e.message }
            delay(600); isRefreshing = false; loading = false
        }
    }

    fun refreshWithReveal() {
        viewModelScope.launch {
            isRefreshing = true; revealNew = true
            try {
                val timeMemories = repo.listMemories(partitionFilter)
                val spaceMemories = repo.listSpaces(partitionFilter).map { it.toMemorySummary() }
                memories = (timeMemories + spaceMemories).sortedByDescending { it.startedAt ?: "" }
            }
            catch (e: Exception) { error = e.message }
            delay(800); isRefreshing = false; loading = false
            delay(600); revealNew = false
        }
    }

    fun toggleFavorite(memoryId: String) {
        viewModelScope.launch {
            try {
                val mem = memories.find { it.memoryId == memoryId } ?: return@launch
                val newFav = !mem.isFavorited
                if (mem.memoryType == MemoryType.SPACE) {
                    repo.toggleSpaceFavorite(memoryId, newFav)
                } else {
                    repo.toggleFavorite(memoryId, newFav)
                }
                memories = memories.map { if (it.memoryId == memoryId) it.copy(isFavorited = newFav) else it }
            } catch (e: Exception) { error = e.message }
        }
    }

    fun deleteMemory(memoryId: String) {
        viewModelScope.launch {
            try {
                val mem = memories.find { it.memoryId == memoryId } ?: return@launch
                if (mem.memoryType == MemoryType.SPACE) {
                    repo.deleteSpace(memoryId)
                } else {
                    repo.deleteMemory(memoryId)
                }
                animatingDeleteId = memoryId
                delay(400)
                memories = memories.filter { it.memoryId != memoryId }
                animatingDeleteId = null
            } catch (e: Exception) { error = e.message }
        }
    }

    fun connectGlasses() {
        viewModelScope.launch {
            // 眼镜连接与记忆库读取相互独立；离线查看已完成记忆不能被连接失败遮住。
            try { glasses.connect() }
            catch (_: Exception) { }
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

private fun sceneLabel(scene: TimeScene?): String = when (scene) {
    TimeScene.MEETING -> "Meeting"
    TimeScene.ONSITE -> "Onsite"
    TimeScene.QUALITY_TIME -> "Quality Time"
    null -> ""
}
private val MonoFont = FontFamily.Monospace
private val TimelineGray = Color(0xFFE5E7EB)

// ── 呼吸灯 — 录制指示器 ──
@Composable
private fun BreathingDot(isActive: Boolean, color: Color = Color(0xFFEF4444)) {
    val t = rememberInfiniteTransition(label = "breath")
    val scale by t.animateFloat(0.6f, 1.4f, infiniteRepeatable(tween(1200, easing = EaseInOutCubic), RepeatMode.Reverse), label = "s")
    val alpha by t.animateFloat(0.4f, 1f, infiniteRepeatable(tween(1200, easing = EaseInOutCubic), RepeatMode.Reverse), label = "a")
    Box(
        Modifier
            .size(8.dp)
            .scale(if (isActive) scale else 1f)
            .alpha(if (isActive) alpha else 0.3f)
            .clip(CircleShape)
            .background(if (isActive) color else Color(0xFFD1D5DB))
    )
}

// ── 上传状态小标签：视频/音频/IMU 上传中 → 上传结束 ──
@Composable
private fun UploadChip(label: String, done: Boolean) {
    val bg = if (done) Color(0xFFECFDF5) else Color(0xFFEFF6FF)
    val fg = if (done) Color(0xFF059669) else Color(0xFF2563EB)
    Box(
        Modifier
            .clip(RoundedCornerShape(999.dp))
            .background(bg)
            .padding(horizontal = 10.dp, vertical = 5.dp)
    ) {
        Text(
            "$label${if (done) "上传结束" else "上传中"}",
            style = MaterialTheme.typography.labelSmall,
            color = fg,
        )
    }
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
    partitionFilter: DataPartition? = null,
    favoritesOnly: Boolean = false,
    title: String = "识境 Echo",
    onNavigateMemory: (String) -> Unit,
    onNavigateSpace: (String) -> Unit,
) {
    val context = LocalContext.current
    val app = context.applicationContext as EchoApplication
    val vm: HomeViewModel = viewModel(factory = object : androidx.lifecycle.ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(cls: Class<T>): T = HomeViewModel(app.repository, app.glassesConnection, partitionFilter) as T
    })
    val ds by vm.deviceStatus.collectAsState()
    val uploadStatus by app.recordingController.uploadStatus.collectAsState()
    val rawMemories = vm.memories
    val displayMemories = remember(rawMemories, favoritesOnly) {
        if (favoritesOnly) rawMemories.filter { it.isFavorited } else rawMemories
    }
    val view = LocalView.current

    // 录制完成 → 带揭晓动画的刷新
    LaunchedEffect(Unit) {
        app.recordingCompleted.collect { vm.refreshWithReveal() }
        app.deletedMemoryId.collect { id -> vm.pendingDeleteId = id }
    }

    // 自动重连: app 启动时如果蓝牙/眼镜可能已连, 尝试建 CXR 会话
    LaunchedEffect(Unit) { vm.connectGlasses() }
    val activeScene by app.activeScene.collectAsState()
    val justCompletedScene by app.justCompletedScene.collectAsState()
    val isRec = activeScene != null

    // 录制开始 → 震动
    LaunchedEffect(isRec) {
        if (isRec) view.performHapticFeedback(HapticFeedbackConstants.LONG_PRESS)
    }

    LaunchedEffect(vm.pendingDeleteId) {
        val id = vm.pendingDeleteId ?: return@LaunchedEffect
        vm.animatingDeleteId = id
        delay(400)
        vm.memories = vm.memories.filter { it.memoryId != id }
        vm.animatingDeleteId = null
        vm.pendingDeleteId = null
    }

    Column(Modifier.fillMaxSize().padding(horizontal = 20.dp).padding(top = 20.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            Text(title, style = MaterialTheme.typography.headlineMedium, color = MaterialTheme.colorScheme.onSurface)
        }
        Spacer(Modifier.height(12.dp))

        // 设备状态：连接状态 / 记忆场景状态 / 上传状态栏，三段独立展示，互不覆盖。
        Box(Modifier.fillMaxWidth().shadow(8.dp, RoundedCornerShape(18.dp)).clip(RoundedCornerShape(18.dp)).background(GlassBgElevated).border(1.dp, GlassBorderElevated, RoundedCornerShape(18.dp)).padding(16.dp)) {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                // 1. 眼镜连接状态
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(8.dp).clip(CircleShape).background(if (ds.connected) Color(0xFF10B981) else Color(0xFFD1D5DB)))
                    Spacer(Modifier.width(10.dp))
                    val connText = if (ds.connected) "眼镜已连接 · 电量 ${ds.batteryPercent}%" else "未连接"
                    Text(connText, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
                    if (!ds.connected) FilledTonalButton(onClick = { vm.connectGlasses() }, modifier = Modifier.height(34.dp)) { Text("连接眼镜") }
                }

                // 2. 记忆场景状态
                Row(verticalAlignment = Alignment.CenterVertically) {
                    BreathingDot(isRec, sceneAccent(activeScene).takeIf { isRec } ?: Color(0xFFEF4444))
                    Spacer(Modifier.width(10.dp))
                    val sceneText = when {
                        activeScene != null && ds.isRecordingSpace -> "${sceneLabel(activeScene)}时间记忆中，3D记忆已开启"
                        activeScene != null -> "${sceneLabel(activeScene)}时间记忆中"
                        justCompletedScene != null -> "${sceneLabel(justCompletedScene)}记忆结束"
                        else -> "记忆未开启"
                    }
                    Text(sceneText, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.85f))
                }

                // 3. 上传状态栏：仅记忆进行中(含收尾上传)时展示，全部完成后延迟隐藏。
                AnimatedVisibility(visible = uploadStatus.visible) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        UploadChip("视频", uploadStatus.videoDone)
                        UploadChip("音频", uploadStatus.audioDone)
                        if (uploadStatus.spaceEnabled) UploadChip("IMU", uploadStatus.imuDone)
                    }
                }
            }
        }

        Spacer(Modifier.height(24.dp))
        Text("最近记忆", style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.onSurface)

        PullToRefreshBox(isRefreshing = vm.isRefreshing, onRefresh = { vm.refresh() }) {
            AnimatedContent(
                targetState = when { vm.loading && !vm.isRefreshing -> "loading"; displayMemories.isEmpty() && !vm.isRefreshing -> "empty"; vm.error != null -> "error"; else -> "list" },
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
                        displayMemories.forEachIndexed { i, memory ->
                            val thisDate = memory.startedAt?.substring(0, 10) ?: ""
                            val isNewDate = thisDate.isNotEmpty() && thisDate != lastDate
                            if (isNewDate) lastDate = thisDate
                            item(key = memory.memoryId) {
                                if (isNewDate) TimelineDateLabel(thisDate)
                                val isFirst = i == 0
                                TimelineItem(i, displayMemories.size, false, isNewDate && isFirst) {
                                    val isDeleting = vm.animatingDeleteId == memory.memoryId
                                    val isReveal = vm.revealNew && i == 0
                                    androidx.compose.animation.AnimatedVisibility(
                                        visible = !isDeleting,
                                        enter = if (isReveal) expandVertically(spring(dampingRatio = 0.6f, stiffness = 300f)) + fadeIn(tween(300)) else fadeIn(tween(400)) + scaleIn(tween(400)),
                                        exit = fadeOut(tween(400)) + scaleOut(targetScale = 0.9f, animationSpec = tween(400))
                                    ) {
                                    MemoryCard(
                                memory = memory,
                                onClick = {
                            if (memory.memoryType == MemoryType.SPACE) onNavigateSpace(memory.memoryId)
                            else onNavigateMemory(memory.memoryId)
                        },
                                onFavorite = { vm.toggleFavorite(memory.memoryId) },
                                onDelete = { vm.deleteMemory(memory.memoryId) }
                            )
                            }
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
            content()
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
private fun MemoryCard(
    memory: MemorySummary,
    onClick: () -> Unit,
    onFavorite: (() -> Unit)? = null,
    onDelete: (() -> Unit)? = null,
    showActions: Boolean = true,
) {
    val accent = if (memory.memoryType == MemoryType.SPACE) Color(0xFFF59E0B) else sceneAccent(memory.scene)
    val presentation = memory.toPresentation()
    Card(
        Modifier.fillMaxWidth().shadow(4.dp, RoundedCornerShape(18.dp)).clip(RoundedCornerShape(18.dp)).clickable { onClick() },
        colors = CardDefaults.cardColors(containerColor = Color.Transparent),
    ) {
        Box(Modifier.background(GlassBg).border(1.dp, GlassBorder, RoundedCornerShape(18.dp))) {
            Row {
                Box(Modifier.width(3.dp).fillMaxHeight().defaultMinSize(minHeight = 72.dp).clip(RoundedCornerShape(topStart = 18.dp, bottomStart = 18.dp)).background(accent.copy(alpha = 0.6f)))
                Column(Modifier.padding(horizontal = 12.dp, vertical = 8.dp).weight(1f)) {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                        Text(presentation.title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                    }
                    Spacer(Modifier.height(6.dp))
                    Text(
                        presentation.metadata,
                        style = MaterialTheme.typography.labelMedium.copy(fontFamily = MonoFont), color = Color(0xFF6B7280),
                    )
                    if (presentation.overview.isNotBlank()) {
                        Spacer(Modifier.height(8.dp))
                        Text(presentation.overview, style = MaterialTheme.typography.bodyMedium, maxLines = 2, color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.85f))
                    }
                    if (showActions && onFavorite != null) {
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End, verticalAlignment = Alignment.CenterVertically) {
                            IconButton(onClick = onFavorite, modifier = Modifier.size(28.dp)) {
                                Icon(
                                    if (memory.isFavorited) Icons.Default.Star else Icons.Default.StarBorder,
                                    "收藏",
                                    tint = if (memory.isFavorited) Color(0xFFF59E0B) else Color(0xFF9CA3AF),
                                    modifier = Modifier.size(18.dp)
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}
