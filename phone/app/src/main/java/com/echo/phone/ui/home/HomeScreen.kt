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

// ── Glass card gradient backgrounds ──
private val GlassBg = Brush.verticalGradient(
    listOf(
        Color.White.copy(alpha = 0.10f),
        Color.White.copy(alpha = 0.06f),
        Color.White.copy(alpha = 0.03f),
    )
)

private val GlassBgElevated = Brush.verticalGradient(
    listOf(
        Color.White.copy(alpha = 0.14f),
        Color.White.copy(alpha = 0.08f),
        Color.White.copy(alpha = 0.05f),
    )
)

private val GlassBorder = Color.White.copy(alpha = 0.10f)
private val GlassBorderElevated = Color.White.copy(alpha = 0.18f)

// Scene gradient accents
private fun sceneAccent(scene: TimeScene?): Color = when (scene) {
    TimeScene.MEETING -> Color(0xFF60A5FA)
    TimeScene.ONSITE -> Color(0xFF34D399)
    TimeScene.QUALITY_TIME -> Color(0xFFA78BFA)
    null -> Color(0xFF64748B)
}

private val MonoFont = FontFamily.Monospace

// ── Recording pulse ──
@Composable
private fun RecordingPulse(isActive: Boolean) {
    val transition = rememberInfiniteTransition(label = "pulse")
    val alpha by transition.animateFloat(
        initialValue = 0.3f, targetValue = 1f,
        animationSpec = infiniteRepeatable(tween(900, easing = EaseInOutCubic), RepeatMode.Reverse),
        label = "pulseA",
    )
    Box(
        Modifier
            .size(8.dp)
            .alpha(if (isActive) alpha else 0.3f)
            .clip(CircleShape)
            .background(if (isActive) Color(0xFFEF4444) else Color(0xFF475569))
    )
}

// ── Skeleton shimmer ──
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SkeletonCard() {
    val shimmer = rememberInfiniteTransition(label = "shimmer")
    val tx by shimmer.animateFloat(
        initialValue = 0f, targetValue = 800f,
        animationSpec = infiniteRepeatable(tween(1400, easing = LinearEasing), RepeatMode.Restart),
        label = "shimmerX",
    )
    Card(
        Modifier.fillMaxWidth().height(100.dp).border(1.dp, GlassBorder, RoundedCornerShape(18.dp)),
        colors = CardDefaults.cardColors(containerColor = Color.Transparent),
    ) {
        Box(
            Modifier.fillMaxSize().background(
                Brush.linearGradient(
                    listOf(
                        Color.White.copy(alpha = 0.04f),
                        Color.White.copy(alpha = 0.10f),
                        Color.White.copy(alpha = 0.04f),
                    ),
                    start = Offset(tx - 200f, 0f), end = Offset(tx, 0f),
                )
            )
        )
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

    Column(Modifier.fillMaxSize().padding(horizontal = 20.dp).padding(top = 20.dp)) {
        // Header
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            Text(title, style = MaterialTheme.typography.headlineMedium, color = MaterialTheme.colorScheme.onSurface)
            IconButton(onClick = { vm.refresh() }) { Icon(Icons.Default.Refresh, "刷新", tint = MaterialTheme.colorScheme.onSurfaceVariant) }
        }
        Spacer(Modifier.height(16.dp))

        // Device status — glass card
        Box(
            Modifier
                .fillMaxWidth()
                .shadow(8.dp, RoundedCornerShape(18.dp))
                .clip(RoundedCornerShape(18.dp))
                .background(GlassBgElevated)
                .border(1.dp, GlassBorderElevated, RoundedCornerShape(18.dp))
                .padding(18.dp)
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                RecordingPulse(deviceStatus.isRecordingTime || deviceStatus.isRecordingSpace)
                Spacer(Modifier.width(12.dp))
                Column(Modifier.weight(1f)) {
                    Text("设备状态", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Spacer(Modifier.height(2.dp))
                    Text(
                        if (deviceStatus.connected) "已连接 · 电量 ${deviceStatus.batteryPercent}%"
                        else "未连接",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                }
                if (!deviceStatus.connected) {
                    FilledTonalButton(onClick = { vm.connectGlasses() }, modifier = Modifier.height(36.dp)) { Text("连接") }
                }
            }
            AnimatedVisibility(
                deviceStatus.isRecordingTime || deviceStatus.isRecordingSpace,
                enter = expandVertically() + fadeIn(),
                exit = shrinkVertically() + fadeOut(),
            ) {
                Column(Modifier.padding(top = 10.dp)) {
                    if (deviceStatus.isRecordingTime)
                        Text("● 时间录制中", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary)
                    if (deviceStatus.isRecordingSpace)
                        Text("◆ 空间采集中", style = MaterialTheme.typography.labelSmall, color = Color(0xFF34D399))
                }
            }
        }

        Spacer(Modifier.height(24.dp))
        Text("最近记忆", style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.onSurface)

        AnimatedContent(
            targetState = when { vm.loading -> "loading"; vm.memories.isEmpty() -> "empty"; vm.error != null -> "error"; else -> "list" },
            transitionSpec = { fadeIn(tween(300)) + scaleIn(tween(300), initialScale = 0.96f) togetherWith fadeOut(tween(150)) },
            label = "home",
        ) { state ->
            when (state) {
                "loading" -> Column(verticalArrangement = Arrangement.spacedBy(12.dp)) { repeat(3) { SkeletonCard() } }
                "empty" -> Box(Modifier.fillMaxWidth().padding(48.dp), contentAlignment = Alignment.Center) {
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
                else -> LazyColumn(verticalArrangement = Arrangement.spacedBy(14.dp)) {
                    items(vm.memories) { m -> MemoryCard(m, onClick = { onNavigateMemory(m.memoryId) }) }
                }
            }
        }
    }
}

@Composable
private fun MemoryCard(memory: MemorySummary, onClick: () -> Unit) {
    val accent = sceneAccent(memory.scene)
    Card(
        Modifier
            .fillMaxWidth()
            .shadow(4.dp, RoundedCornerShape(18.dp))
            .clip(RoundedCornerShape(18.dp))
            .clickable(onClick = onClick),
        colors = CardDefaults.cardColors(containerColor = Color.Transparent),
    ) {
        Box(Modifier.background(GlassBg).border(1.dp, GlassBorder, RoundedCornerShape(18.dp))) {
            Row {
                // Left accent strip
                Box(
                    Modifier
                        .width(3.dp)
                        .fillMaxHeight()
                        .defaultMinSize(minHeight = 88.dp)
                        .clip(RoundedCornerShape(topStart = 18.dp, bottomStart = 18.dp))
                        .background(accent.copy(alpha = 0.7f))
                )
                Column(Modifier.padding(18.dp).weight(1f)) {
                    Row(
                        Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            memory.title.ifEmpty { memory.identifyBrief }.ifEmpty { "未命名记忆" },
                            style = MaterialTheme.typography.titleSmall,
                            fontWeight = FontWeight.SemiBold,
                            color = MaterialTheme.colorScheme.onSurface,
                            modifier = Modifier.weight(1f),
                        )
                        if (memory.isFavorited)
                            Icon(Icons.Default.Star, null, tint = Color(0xFFFFB300), modifier = Modifier.size(16.dp))
                    }
                    Spacer(Modifier.height(6.dp))
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
                        Spacer(Modifier.height(8.dp))
                        Text(
                            memory.identifyBrief,
                            style = MaterialTheme.typography.bodyMedium,
                            maxLines = 2,
                            color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.85f),
                        )
                    }
                }
            }
        }
    }
}
