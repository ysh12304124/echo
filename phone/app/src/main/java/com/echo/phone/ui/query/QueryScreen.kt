package com.echo.phone.ui.query

import androidx.compose.animation.*
import androidx.compose.animation.core.*
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.echo.phone.EchoApplication
import com.echo.phone.data.VoiceQueryRecorder
import com.echo.phone.domain.*
import com.echo.phone.util.EchoLog
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import retrofit2.HttpException
import java.io.IOException

enum class VoicePhase { IDLE, RECORDING, TRANSCRIBING, SEARCHING }

class QueryViewModel(
    private val repo: com.echo.phone.data.EchoRepository,
    private val recorder: VoiceQueryRecorder = VoiceQueryRecorder(),
) : ViewModel() {
    var question by mutableStateOf("")
    var scope by mutableStateOf(QueryScope.GLOBAL_WORK)
    var result by mutableStateOf<QueryResult?>(null)
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var notice by mutableStateOf<String?>(null)
    var voicePhase by mutableStateOf(VoicePhase.IDLE)
    var recordingSeconds by mutableStateOf(0)

    private var recordingJob: Job? = null
    private var finishing = false
    private var startedAtMs = 0L

    fun submit() {
        if (question.isBlank() || loading || voicePhase != VoicePhase.IDLE) return
        viewModelScope.launch {
            loading = true
            error = null
            notice = null
            try {
                result = repo.query(question.trim(), scope, null, null)
            } catch (e: Exception) {
                error = e.message
            } finally {
                loading = false
            }
        }
    }

    fun startVoiceRecording(): Boolean {
        if (loading || voicePhase != VoicePhase.IDLE || finishing) return false
        val started = try { recorder.start() } catch (error: Throwable) {
            EchoLog.e("语音查询录音启动异常: ${error.message}", error)
            false
        }
        if (!started) {
            error = "无法启动麦克风，请检查录音权限"
            return false
        }
        error = null
        notice = null
        result = null
        recordingSeconds = 0
        finishing = false
        startedAtMs = android.os.SystemClock.elapsedRealtime()
        voicePhase = VoicePhase.RECORDING
        recordingJob?.cancel()
        recordingJob = viewModelScope.launch {
            while (voicePhase == VoicePhase.RECORDING) {
                recordingSeconds = ((android.os.SystemClock.elapsedRealtime() - startedAtMs) / 1000L).toInt()
                if (recordingSeconds >= VoiceQueryRecorder.MAX_SECONDS) {
                    finishVoiceRecording(false)
                    break
                }
                delay(100)
            }
        }
        return true
    }

    fun finishVoiceRecording(cancel: Boolean) {
        if (voicePhase != VoicePhase.RECORDING || finishing) return
        finishing = true
        recordingJob?.cancel()
        recordingJob = null
        if (cancel) {
            voicePhase = VoicePhase.IDLE
            notice = null
            viewModelScope.launch {
                try { recorder.cancelAndDiscard() } catch (error: Throwable) {
                    EchoLog.e("语音查询取消清理异常: ${error.message}", error)
                } finally {
                    finishing = false
                }
            }
            return
        }

        voicePhase = VoicePhase.TRANSCRIBING
        loading = true
        viewModelScope.launch {
            try {
                val audio = recorder.stop()
                if (audio.isEmpty()) {
                    notice = "没有采集到语音，请重试"
                    return@launch
                }
                if (audio.size < VoiceQueryRecorder.MIN_BYTES) {
                    notice = "语音太短，请长按并说完整问题"
                    return@launch
                }
                val transcription = repo.transcribeVoice(audio)
                val query = transcription.transcript.trim()
                if (!transcription.asrAccepted || query.isBlank()) {
                    notice = transcription.rejectionReason ?: "没听清，请再说一次"
                    return@launch
                }
                question = query
                voicePhase = VoicePhase.SEARCHING
                result = repo.query(query, scope, null, null)
            } catch (exception: Exception) {
                EchoLog.e("语音查询失败: ${exception.message}", exception)
                error = userFacingQueryError(exception)
            } finally {
                voicePhase = VoicePhase.IDLE
                loading = false
                finishing = false
            }
        }
    }

    private fun userFacingQueryError(exception: Exception): String {
        if (exception is IOException) return "网络连接失败，请检查网络后重试"
        return when ((exception as? HttpException)?.code()) {
            400 -> "语音格式不正确，请重新录制"
            503 -> "语音识别服务暂时不可用，请稍后重试"
            504 -> "语音识别超时，请稍后重试"
            else -> exception.message ?: "语音查询失败，请稍后重试"
        }
    }

    override fun onCleared() {
        recordingJob?.cancel()
        recorder.cancel()
        super.onCleared()
    }
}

private fun evIcon(t: EvidenceType): ImageVector = when (t) {
    EvidenceType.VISUAL -> Icons.Default.Image
    EvidenceType.TRANSCRIPT -> Icons.Default.Mic
    EvidenceType.OCR -> Icons.Default.TextFields
    EvidenceType.SPATIAL -> Icons.Default.ViewInAr
    EvidenceType.USER_NOTE -> Icons.Default.Notes
}

private val GlassBg = Brush.verticalGradient(listOf(Color(0xFFFFFFFF), Color(0xFFF8F9FC)))
private val GlassBorder = Color(0xFFE2E4EA)

// ── Staggered evidence items ──
@Composable
private fun StaggeredItem(index: Int, content: @Composable () -> Unit) {
    var visible by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { delay(index * 50L); visible = true }
    AnimatedVisibility(visible, enter = fadeIn(tween(400)) + slideInVertically(tween(400)) { it / 3 }) { content() }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun QueryScreen(onNavigateMemory: (String) -> Unit) {
    val context = LocalContext.current
    val app = context.applicationContext as EchoApplication
    val vm: QueryViewModel = viewModel(factory = object : androidx.lifecycle.ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(cls: Class<T>): T = QueryViewModel(app.repository) as T
    })

    Column(Modifier.fillMaxSize().padding(horizontal = 20.dp).padding(top = 20.dp)) {
        Text("查询", style = MaterialTheme.typography.headlineMedium)
        Spacer(Modifier.height(14.dp))

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            FilterChip(selected = vm.scope == QueryScope.GLOBAL_WORK, onClick = { vm.scope = QueryScope.GLOBAL_WORK }, label = { Text("全局工作") })
            FilterChip(selected = vm.scope == QueryScope.MEMORY, onClick = { vm.scope = QueryScope.MEMORY }, label = { Text("当前记忆") })
            FilterChip(selected = vm.scope == QueryScope.SPACE, onClick = { vm.scope = QueryScope.SPACE }, label = { Text("当前空间") })
        }
        Spacer(Modifier.height(14.dp))

        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            OutlinedTextField(
                value = vm.question,
                onValueChange = { vm.question = it },
                modifier = Modifier.weight(1f).shadow(if (vm.question.isNotEmpty()) 2.dp else 0.dp, RoundedCornerShape(10.dp)),
                placeholder = { Text("例如：张经理承诺了什么？") },
                leadingIcon = { Icon(Icons.Default.Search, null) },
                trailingIcon = {
                    if (vm.question.isNotBlank()) {
                        IconButton(onClick = { vm.submit() }, enabled = !vm.loading) {
                            Icon(Icons.Default.Send, "查询")
                        }
                    }
                },
                enabled = vm.voicePhase == VoicePhase.IDLE && !vm.loading,
                singleLine = true,
                shape = MaterialTheme.shapes.small,
                colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = MaterialTheme.colorScheme.primary),
            )
            IconButton(
                onClick = {
                    if (vm.voicePhase == VoicePhase.RECORDING) vm.finishVoiceRecording(false)
                    else vm.startVoiceRecording()
                },
                enabled = !vm.loading || vm.voicePhase == VoicePhase.RECORDING,
            ) {
                Icon(
                    if (vm.voicePhase == VoicePhase.RECORDING) Icons.Default.Stop else Icons.Default.Mic,
                    contentDescription = if (vm.voicePhase == VoicePhase.RECORDING) "结束语音查询" else "语音查询",
                )
            }
        }
        if (vm.voicePhase == VoicePhase.RECORDING) {
            Row(
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text("正在录音 ${vm.recordingSeconds}s，点击麦克风结束", color = MaterialTheme.colorScheme.primary)
                TextButton(onClick = { vm.finishVoiceRecording(true) }) { Text("取消") }
            }
        }
        Spacer(Modifier.height(20.dp))

        AnimatedContent(
            targetState = when {
                vm.voicePhase == VoicePhase.TRANSCRIBING -> "transcribing"
                vm.voicePhase == VoicePhase.SEARCHING -> "searching"
                vm.loading -> "loading"
                vm.error != null -> "error"
                vm.notice != null -> "notice"
                vm.result != null -> "result"
                else -> "idle"
            },
            transitionSpec = { fadeIn(tween(250)) + slideInVertically(tween(250)) { it / 4 } togetherWith fadeOut(tween(150)) },
            label = "result",
        ) { state ->
            when (state) {
                "loading", "transcribing", "searching" -> Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    CircularProgressIndicator()
                    Spacer(Modifier.height(8.dp))
                    Text(
                        when (state) {
                            "transcribing" -> "正在转写语音"
                            "searching" -> "正在检索记忆"
                            else -> "查询中"
                        },
                    )
                }
                "error" -> Box(Modifier.fillMaxWidth().shadow(4.dp, RoundedCornerShape(18.dp)).clip(RoundedCornerShape(18.dp)).background(GlassBg).border(1.dp, GlassBorder, RoundedCornerShape(18.dp)).padding(18.dp)) {
                    Text("查询失败: ${vm.error}", color = MaterialTheme.colorScheme.error)
                }
                "notice" -> Box(Modifier.fillMaxWidth().shadow(4.dp, RoundedCornerShape(18.dp)).clip(RoundedCornerShape(18.dp)).background(GlassBg).border(1.dp, GlassBorder, RoundedCornerShape(18.dp)).padding(18.dp)) {
                    Text(vm.notice ?: "", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                "result" -> QueryResultView(vm.result!!)
            }
        }
    }
}

@Composable
private fun QueryResultView(result: QueryResult) {
    val bg = when (result.status) {
        QueryResultStatus.CONFIRMED -> Color(0xFFDBEAFE)
        QueryResultStatus.POSSIBLE -> Color(0xFFFEF3C7)
        QueryResultStatus.NOT_FOUND -> Color(0xFFF3F4F6)
    }
    val icon = when (result.status) { QueryResultStatus.CONFIRMED -> Icons.Default.CheckCircle; QueryResultStatus.POSSIBLE -> Icons.Default.Warning; QueryResultStatus.NOT_FOUND -> Icons.Default.Info }
    val label = when (result.status) { QueryResultStatus.CONFIRMED -> "确定答案"; QueryResultStatus.POSSIBLE -> "可能相关"; QueryResultStatus.NOT_FOUND -> "没有找到" }
    val iconTint = when (result.status) { QueryResultStatus.CONFIRMED -> Color(0xFF2563EB); QueryResultStatus.POSSIBLE -> Color(0xFFD97706); QueryResultStatus.NOT_FOUND -> Color(0xFF9CA3AF) }

    Box(Modifier.fillMaxWidth().shadow(4.dp, RoundedCornerShape(18.dp)).clip(RoundedCornerShape(18.dp)).background(bg).border(1.dp, GlassBorder, RoundedCornerShape(18.dp)).padding(18.dp)) {
        Column {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(icon, null, tint = iconTint, modifier = Modifier.size(20.dp))
                Spacer(Modifier.width(8.dp))
                Text(label, style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.Bold, color = iconTint)
            }
            if (result.status != QueryResultStatus.NOT_FOUND) {
                Spacer(Modifier.height(10.dp))
                Text(result.answer ?: "", style = MaterialTheme.typography.bodyLarge)
            }
            result.uncertaintyReason?.let { Spacer(Modifier.height(4.dp)); Text(it, style = MaterialTheme.typography.bodySmall, color = Color(0xFF6B7280)) }
        }
    }

    if (result.evidences.isNotEmpty()) {
        Spacer(Modifier.height(16.dp))
        Text("证据", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(8.dp))
        LazyColumn {
            itemsIndexed(result.evidences) { i, ev ->
                StaggeredItem(i) {
                    Box(Modifier.fillMaxWidth().padding(vertical = 3.dp).shadow(2.dp, RoundedCornerShape(14.dp)).clip(RoundedCornerShape(14.dp)).background(GlassBg).border(1.dp, GlassBorder, RoundedCornerShape(14.dp)).padding(14.dp)) {
                        Row(verticalAlignment = Alignment.Top) {
                            Icon(evIcon(ev.type), null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(18.dp))
                            Spacer(Modifier.width(10.dp))
                            Column {
                                Text(ev.content, style = MaterialTheme.typography.bodySmall)
                                Text("置信: ${ev.confidence.name}", style = MaterialTheme.typography.labelSmall, color = Color(0xFF6B7280))
                            }
                        }
                    }
                }
            }
        }
    }
}
