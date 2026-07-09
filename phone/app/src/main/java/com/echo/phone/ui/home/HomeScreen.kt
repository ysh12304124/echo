package com.echo.phone.ui.home

import androidx.compose.animation.*
import androidx.compose.animation.core.*
import androidx.compose.foundation.background
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
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
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
            } catch (e: Exception) { error = e.message }
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

// Scene gradient accents
private fun sceneGradient(scene: TimeScene?): Brush = when (scene) {
    TimeScene.MEETING -> Brush.verticalGradient(listOf(Color(0xFF4C8DFF), Color(0xFF22D3EE)))
    TimeScene.ONSITE -> Brush.verticalGradient(listOf(Color(0xFF34D399), Color(0xFF06B6D4)))
    TimeScene.QUALITY_TIME -> Brush.verticalGradient(listOf(Color(0xFF8B7BFF), Color(0xFFEC4899)))
    null -> Brush.verticalGradient(listOf(Color(0xFF9FB0CC), Color(0xFFBCC7D0)))
}

private val MonoFont = FontFamily.Monospace

// ── Breathing pulse animation for recording indicator ──
@Composable
private fun RecordingPulse(isActive: Boolean) {
    val infiniteTransition = rememberInfiniteTransition(label = "pulse")
    val alpha by infiniteTransition.animateFloat(
        initialValue = 0.4f, targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(800, easing = EaseInOutCubic),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "pulseAlpha",
    )
    Box(
        Modifier
            .size(8.dp)
            .alpha(if (isActive) alpha else 0.4f)
            .clip(CircleShape)
            .background(if (isActive) Color(0xFFEF4444) else Color(0xFF9FB0CC))
    )
}

// ── Skeleton shimmer ──
@Composable
private fun SkeletonCard() {
    val shimmer = rememberInfiniteTransition(label = "shimmer")
    val translateAnim by shimmer.animateFloat(
        initialValue = 0f, targetValue = 1000f,
        animationSpec = infiniteRepeatable(tween(1200, easing = LinearEasing), RepeatMode.Restart),
        label = "shimmerX",
    )
    val brush = Brush.linearGradient(
        colors = listOf(
            MaterialTheme.colorScheme.surfaceContainer,
            MaterialTheme.colorScheme.surfaceContainerHigh,
            MaterialTheme.colorScheme.surfaceContainer,
        ),
        start = Offset(translateAnim - 200f, 0f),
        end = Offset(translateAnim, 0f),
    )
    Card(Modifier.fillMaxWidth().height(100.dp)) {
        Box(Modifier.fillMaxSize().background(brush))
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

    LaunchedEffect(Unit) { app.recordingCompleted.collect { vm.refresh() } }

    Column(Modifier.fillMaxSize().padding(horizontal = 16.dp).padding(top = 16.dp)) {
        // Header
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            Text(title, style = MaterialTheme.typography.headlineMedium)
            IconButton(onClick = { vm.refresh() }) { Icon(Icons.Default.Refresh, "刷新") }
        }
        Spacer(Modifier.height(12.dp))

        // Device status card with pulse
        Card(
            Modifier.fillMaxWidth().shadow(2.dp, RoundedCornerShape(16.dp)),
            colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerHigh),
        ) {
            Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                RecordingPulse(deviceStatus.isRecordingTime || deviceStatus.isRecordingSpace)
                Spacer(Modifier.width(10.dp))
                Column(Modifier.weight(1f)) {
                    Text("设备状态", style = MaterialTheme.typography.titleSmall)
                    Text(
                        if (deviceStatus.connected) "已连接 · 电量 ${deviceStatus.batteryPercent}%"
                        else "未连接",
                        style = MaterialTheme.typography.bodyMedium,
                    )
                }
                if (!deviceStatus.connected) {
                    TextButton(onClick = { vm.connectGlasses() }) { Text("连接") }
                }
            }
            AnimatedVisibility(
                deviceStatus.isRecordingTime || deviceStatus.isRecordingSpace,
                enter = expandVertically() + fadeIn(),
                exit = shrinkVertically() + fadeOut(),
            ) {
                Column(Modifier.padding(start = 16.dp, end = 16.dp, bottom = 12.dp)) {
                    if (deviceStatus.isRecordingTime) {
                        Text("● 时间录制中", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
                    }
                    if (deviceStatus.isRecordingSpace) {
                        Text("◆ 空间采集中", style = MaterialTheme.typography.labelMedium, color = Color(0xFF34D399))
                    }
                }
            }
        }

        Spacer(Modifier.height(20.dp))
        Text("最近记忆", style = MaterialTheme.typography.titleMedium)

        AnimatedContent(
            targetState = when {
                vm.loading -> "loading"
                vm.memories.isEmpty() -> "empty"
                vm.error != null -> "error"
                else -> "list"
            },
            transitionSpec = { fadeIn(tween(300)) + scaleIn(tween(300)) togetherWith fadeOut(tween(200)) },
            label = "homeContent",
        ) { state ->
            when (state) {
                "loading" -> Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    repeat(3) { SkeletonCard() }
                }
                "empty" -> Box(Modifier.fillMaxWidth().padding(40.dp), contentAlignment = Alignment.Center) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Text("⏳", style = MaterialTheme.typography.headlineLarge)
                        Spacer(Modifier.height(8.dp))
                        Text("暂无记忆", style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        Text("戴上眼镜，选择场景后开始记录", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
                "error" -> Column {
                    Text("加载失败: ${vm.error}", color = MaterialTheme.colorScheme.error)
                    TextButton(onClick = { vm.refresh() }) { Text("重试") }
                }
                else -> LazyColumn(verticalArrangement = Arrangement.spacedBy(12.dp)) {
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
    val accent = sceneGradient(memory.scene)
    Card(
        Modifier
            .fillMaxWidth()
            .shadow(1.dp, RoundedCornerShape(16.dp))
            .clickable(onClick = onClick),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerHigh),
    ) {
        Row {
            Box(
                Modifier
                    .width(4.dp)
                    .fillMaxHeight()
                    .defaultMinSize(minHeight = 84.dp)
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
                        modifier = Modifier.weight(1f),
                    )
                    if (memory.isFavorited) {
                        Icon(Icons.Default.Star, null, tint = Color(0xFFFFB300), modifier = Modifier.size(18.dp))
                    }
                }
                Spacer(Modifier.height(6.dp))
                // Timestamp in monospace font
                Text(
                    buildString {
                        memory.startedAt?.let {
                            val date = it.substringBefore("T")
                            val t = it.substringAfter("T").substringBefore(".").substring(0, 5)
                            append("$date $t")
                        }
                        memory.scene?.let { append("  ${it.name}") }
                        if (memory.durationSeconds > 0) append("  ${memory.durationSeconds}s")
                    },
                    style = MaterialTheme.typography.labelMedium.copy(fontFamily = MonoFont),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (memory.identifyBrief.isNotEmpty()) {
                    Spacer(Modifier.height(6.dp))
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
