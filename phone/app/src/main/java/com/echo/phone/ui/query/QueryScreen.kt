package com.echo.phone.ui.query

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Image
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Notes
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Send
import androidx.compose.material.icons.filled.TextFields
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material.icons.filled.ViewInAr
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.changedToUpIgnoreConsumed
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.LayoutCoordinates
import androidx.compose.ui.layout.boundsInRoot
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInRoot
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.echo.phone.EchoApplication
import com.echo.phone.data.VoiceQueryRecorder
import com.echo.phone.domain.EvidenceType
import com.echo.phone.domain.QueryResult
import com.echo.phone.domain.QueryResultStatus
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import coil.compose.SubcomposeAsyncImage
import coil.compose.SubcomposeAsyncImageContent
import retrofit2.HttpException
import java.io.IOException

enum class VoicePhase { IDLE, RECORDING, TRANSCRIBING, SEARCHING }

class QueryViewModel(
    private val repo: com.echo.phone.data.EchoRepository,
    private val recorder: VoiceQueryRecorder = VoiceQueryRecorder(),
) : ViewModel() {
    var question by mutableStateOf("")
    var result by mutableStateOf<QueryResult?>(null)
    var transcript by mutableStateOf<String?>(null)
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var voicePhase by mutableStateOf(VoicePhase.IDLE)
    var recordingSeconds by mutableStateOf(0)
    var cancelTargetActive by mutableStateOf(false)
    var voiceFeedback by mutableStateOf<String?>(null)

    private var recordingJob: Job? = null
    private var feedbackJob: Job? = null
    private var finishing = false
    private var startedAtMs = 0L

    fun submit() {
        if (question.isBlank() || loading || voicePhase != VoicePhase.IDLE) return
        viewModelScope.launch {
            loading = true
            error = null
            transcript = null
            result = null
            try {
                result = repo.query(question.trim(), com.echo.phone.domain.QueryScope.GLOBAL_WORK)
            } catch (exception: Exception) {
                error = exception.message ?: "查询失败"
            } finally {
                loading = false
            }
        }
    }

    fun startVoiceRecording(): Boolean {
        if (loading || voicePhase != VoicePhase.IDLE || !recorder.start()) {
            if (voicePhase == VoicePhase.IDLE) error = "无法启动麦克风，请检查录音权限"
            return false
        }
        error = null
        result = null
        transcript = null
        recordingSeconds = 0
        cancelTargetActive = false
        voiceFeedback = null
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

    fun updateCancelTarget(active: Boolean) {
        if (voicePhase == VoicePhase.RECORDING) cancelTargetActive = active
    }

    fun finishVoiceRecording(cancel: Boolean) {
        if (voicePhase != VoicePhase.RECORDING || finishing) return
        finishing = true
        recordingJob?.cancel()
        recordingJob = null
        cancelTargetActive = false
        if (cancel) {
            recorder.cancel()
            voicePhase = VoicePhase.IDLE
            finishing = false
            showVoiceFeedback("已取消录音")
            return
        }

        voicePhase = VoicePhase.TRANSCRIBING
        loading = true
        viewModelScope.launch {
            try {
                val audio = recorder.stop()
                if (audio.isEmpty()) {
                    error = "没有采集到语音"
                    return@launch
                }
                if (audio.size < VoiceQueryRecorder.MIN_BYTES) {
                    error = "语音太短，请长按并说完整问题"
                    return@launch
                }

                val transcription = repo.transcribeVoice(audio)
                transcript = transcription.transcript.ifBlank { null }
                question = transcription.transcript
                if (!transcription.asrAccepted) {
                    error = transcription.rejectionReason ?: "没听清，请再说一次"
                    return@launch
                }
                voicePhase = VoicePhase.SEARCHING
                result = repo.query(
                    transcription.transcript,
                    com.echo.phone.domain.QueryScope.GLOBAL_WORK,
                )
            } catch (exception: Exception) {
                error = userFacingQueryError(exception)
            } finally {
                voicePhase = VoicePhase.IDLE
                loading = false
                finishing = false
            }
        }
    }

    private fun showVoiceFeedback(message: String) {
        feedbackJob?.cancel()
        voiceFeedback = message
        feedbackJob = viewModelScope.launch {
            delay(1400)
            if (voiceFeedback == message) voiceFeedback = null
        }
    }

    private fun userFacingQueryError(exception: Exception): String {
        if (exception is IOException) return "网络连接失败，请检查网络后重试"
        return when ((exception as? HttpException)?.code()) {
            400 -> "语音格式不正确，请重新录制"
            503 -> if (voicePhase == VoicePhase.TRANSCRIBING) {
                "语音识别服务暂时不可用，请稍后重试"
            } else {
                "查询服务暂时不可用，请稍后重试"
            }
            504 -> "语音识别超时，请稍后重试"
            else -> exception.message ?: "语音查询失败，请稍后重试"
        }
    }

    override fun onCleared() {
        recordingJob?.cancel()
        feedbackJob?.cancel()
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

@Composable
private fun StaggeredItem(index: Int, content: @Composable () -> Unit) {
    var visible by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) {
        delay(index * 50L)
        visible = true
    }
    AnimatedVisibility(
        visible,
        enter = fadeIn(tween(400)) + slideInVertically(tween(400)) { it / 3 },
    ) { content() }
}

@Composable
fun QueryScreen(onNavigateMemory: (String) -> Unit) {
    val context = LocalContext.current
    val app = context.applicationContext as EchoApplication
    val vm: QueryViewModel = viewModel(factory = object : androidx.lifecycle.ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(cls: Class<T>): T = QueryViewModel(app.repository) as T
    })
    var cancelTargetCoordinates by remember { mutableStateOf<LayoutCoordinates?>(null) }
    var micCoordinates by remember { mutableStateOf<LayoutCoordinates?>(null) }

    Column(
        Modifier
            .fillMaxSize()
            .padding(horizontal = 20.dp)
            .padding(top = 20.dp, bottom = 16.dp),
    ) {
        Text("查询", style = MaterialTheme.typography.headlineMedium)
        Spacer(Modifier.height(14.dp))

        OutlinedTextField(
            value = vm.question,
            onValueChange = { vm.question = it },
            modifier = Modifier
                .fillMaxWidth()
                .shadow(if (vm.question.isNotEmpty()) 2.dp else 0.dp, RoundedCornerShape(10.dp)),
            placeholder = { Text("例如：张经理承诺了什么？") },
            leadingIcon = { Icon(Icons.Default.Search, null) },
            trailingIcon = {
                if (vm.question.isNotBlank()) {
                    IconButton(onClick = { vm.submit() }, enabled = !vm.loading) {
                        Icon(Icons.Default.Send, "查询")
                    }
                }
            },
            singleLine = true,
            shape = MaterialTheme.shapes.small,
            colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = MaterialTheme.colorScheme.primary),
        )

        Column(
            Modifier
                .weight(1f)
                .fillMaxWidth()
                .verticalScroll(rememberScrollState()),
        ) {
            Spacer(Modifier.height(16.dp))
            vm.transcript?.let { transcript ->
                if (vm.voicePhase != VoicePhase.RECORDING) {
                    TranscriptPreview(transcript)
                    Spacer(Modifier.height(12.dp))
                }
            }
            val currentError = vm.error
            val currentResult = vm.result
            when {
                vm.voicePhase == VoicePhase.TRANSCRIBING -> StatusView("正在转写", true)
                vm.voicePhase == VoicePhase.SEARCHING -> StatusView("正在检索", true)
                vm.loading -> StatusView("查询中", true)
                currentError != null -> {
                    Box(
                        Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(10.dp))
                            .background(Color(0xFFFFF1F0))
                            .border(1.dp, Color(0xFFFECACA), RoundedCornerShape(10.dp))
                            .padding(16.dp),
                    ) { Text(currentError, color = MaterialTheme.colorScheme.error) }
                }
                currentResult != null -> {
                    QueryResultView(currentResult, app.repository::absoluteMediaUrl)
                }
            }
        }

        Spacer(Modifier.height(10.dp))
        Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
            AnimatedVisibility(visible = vm.voicePhase == VoicePhase.RECORDING) {
                Box(Modifier.fillMaxWidth().height(104.dp), contentAlignment = Alignment.Center) {
                    Box(
                        Modifier
                            .size(88.dp)
                            .onGloballyPositioned { cancelTargetCoordinates = it }
                            .clip(CircleShape)
                            .background(if (vm.cancelTargetActive) Color(0xFFD92D20) else Color(0xFFFFE4E1))
                            .border(2.dp, Color(0xFFD92D20), CircleShape),
                        contentAlignment = Alignment.Center,
                    ) {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            Icon(
                                Icons.Default.Close,
                                contentDescription = "取消录音",
                                tint = if (vm.cancelTargetActive) Color.White else Color(0xFFD92D20),
                                modifier = Modifier.size(30.dp),
                            )
                            Text(
                                if (vm.cancelTargetActive) "松开取消" else "移入取消",
                                style = MaterialTheme.typography.labelSmall,
                                color = if (vm.cancelTargetActive) Color.White else Color(0xFFD92D20),
                            )
                        }
                    }
                }
            }

            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(
                    Modifier
                        .size(72.dp)
                        .onGloballyPositioned { micCoordinates = it }
                        .clip(CircleShape)
                        .background(if (vm.voicePhase == VoicePhase.RECORDING) Color(0xFF1D4ED8) else MaterialTheme.colorScheme.primary)
                        .pointerInput(Unit) {
                            awaitEachGesture {
                                awaitFirstDown(requireUnconsumed = false)
                                val held = withTimeoutOrNull(LONG_PRESS_MS) {
                                    while (true) {
                                        val event = awaitPointerEvent(PointerEventPass.Main)
                                        val change = event.changes.firstOrNull() ?: continue
                                        if (!change.pressed) return@withTimeoutOrNull false
                                    }
                                }
                                if (held != null || !vm.startVoiceRecording()) return@awaitEachGesture

                                while (vm.voicePhase == VoicePhase.RECORDING) {
                                    val event = awaitPointerEvent(PointerEventPass.Main)
                                    val change = event.changes.firstOrNull() ?: continue
                                    val rootPosition = micCoordinates?.positionInRoot()?.plus(change.position)
                                    val inTarget = rootPosition != null &&
                                        cancelTargetCoordinates?.boundsInRoot()?.contains(rootPosition) == true
                                    vm.updateCancelTarget(inTarget)
                                    if (change.changedToUpIgnoreConsumed() || !change.pressed) {
                                        vm.finishVoiceRecording(inTarget)
                                        change.consume()
                                        break
                                    }
                                    change.consume()
                                }
                            }
                        },
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        Icons.Default.Mic,
                        contentDescription = "长按语音查询",
                        tint = Color.White,
                        modifier = Modifier.size(32.dp),
                    )
                }
                if (vm.voicePhase == VoicePhase.RECORDING) {
                    Spacer(Modifier.width(12.dp))
                    Text("00:${vm.recordingSeconds.toString().padStart(2, '0')}", style = MaterialTheme.typography.titleMedium)
                }
            }
            val prompt = when {
                vm.voicePhase == VoicePhase.RECORDING && vm.cancelTargetActive -> "松开后取消"
                vm.voicePhase == VoicePhase.RECORDING -> "松开完成，上滑到红色区域取消"
                vm.voiceFeedback != null -> vm.voiceFeedback
                else -> "长按说话"
            }
            Spacer(Modifier.height(8.dp))
            Text(
                prompt ?: "",
                style = MaterialTheme.typography.labelMedium,
                color = when {
                    vm.voicePhase == VoicePhase.RECORDING && vm.cancelTargetActive -> Color(0xFFD92D20)
                    vm.voiceFeedback != null -> Color(0xFF667085)
                    else -> Color(0xFF667085)
                },
            )
        }
    }
}

@Composable
private fun TranscriptPreview(transcript: String) {
    Box(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(Color(0xFFF3F6FA))
            .border(1.dp, Color(0xFFD7DEE8), RoundedCornerShape(8.dp))
            .padding(horizontal = 14.dp, vertical = 12.dp),
    ) {
        Column {
            Text(
                "本次查询",
                style = MaterialTheme.typography.labelMedium,
                color = Color(0xFF667085),
            )
            Spacer(Modifier.height(4.dp))
            Text(transcript, style = MaterialTheme.typography.bodyMedium)
        }
    }
}

@Composable
private fun StatusView(label: String, spinning: Boolean) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        if (spinning) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
        Spacer(Modifier.width(10.dp))
        Text(label, style = MaterialTheme.typography.bodyMedium)
    }
}

@Composable
private fun QueryResultView(
    result: QueryResult,
    resolveMediaUrl: (String?) -> String?,
) {
    var enlargedImage by remember(result.queryId) { mutableStateOf<String?>(null) }
    val bg = when (result.status) {
        QueryResultStatus.CONFIRMED -> Color(0xFFDBEAFE)
        QueryResultStatus.POSSIBLE -> Color(0xFFFEF3C7)
        QueryResultStatus.NOT_FOUND -> Color(0xFFF3F4F6)
    }
    val icon = when (result.status) {
        QueryResultStatus.CONFIRMED -> Icons.Default.CheckCircle
        QueryResultStatus.POSSIBLE -> Icons.Default.Warning
        QueryResultStatus.NOT_FOUND -> Icons.Default.Info
    }
    val label = when (result.status) {
        QueryResultStatus.CONFIRMED -> "确定答案"
        QueryResultStatus.POSSIBLE -> "可能相关"
        QueryResultStatus.NOT_FOUND -> "没有找到"
    }
    val iconTint = when (result.status) {
        QueryResultStatus.CONFIRMED -> Color(0xFF2563EB)
        QueryResultStatus.POSSIBLE -> Color(0xFFD97706)
        QueryResultStatus.NOT_FOUND -> Color(0xFF9CA3AF)
    }

    Box(
        Modifier
            .fillMaxWidth()
            .shadow(4.dp, RoundedCornerShape(10.dp))
            .clip(RoundedCornerShape(10.dp))
            .background(bg)
            .border(1.dp, GlassBorder, RoundedCornerShape(10.dp))
            .padding(18.dp),
    ) {
        Column {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(icon, null, tint = iconTint, modifier = Modifier.size(20.dp))
                Spacer(Modifier.width(8.dp))
                Text(label, style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.Bold, color = iconTint)
            }
            if (result.status != QueryResultStatus.NOT_FOUND) {
                Spacer(Modifier.height(10.dp))
                Text(result.answer ?: "", style = MaterialTheme.typography.bodyLarge)
                result.evidences
                    .filter { it.type == EvidenceType.VISUAL && it.mediaUrl != null }
                    .forEach { evidence ->
                        resolveMediaUrl(evidence.mediaUrl)?.let { imageUrl ->
                            Spacer(Modifier.height(10.dp))
                            KeyframeImage(
                                imageUrl = imageUrl,
                                description = evidence.content,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .height(180.dp)
                                    .clip(RoundedCornerShape(8.dp)),
                                onClick = { enlargedImage = imageUrl },
                            )
                        }
                    }
            }
            result.uncertaintyReason?.let {
                Spacer(Modifier.height(4.dp))
                Text(it, style = MaterialTheme.typography.bodySmall, color = Color(0xFF6B7280))
            }
        }
    }

    if (result.evidences.isNotEmpty()) {
        Spacer(Modifier.height(16.dp))
        Text("证据", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(8.dp))
        Column {
            result.evidences.forEachIndexed { index, evidence ->
                StaggeredItem(index) {
                    Box(
                        Modifier
                            .fillMaxWidth()
                            .padding(vertical = 3.dp)
                            .shadow(2.dp, RoundedCornerShape(8.dp))
                            .clip(RoundedCornerShape(8.dp))
                            .background(GlassBg)
                            .border(1.dp, GlassBorder, RoundedCornerShape(8.dp))
                            .padding(14.dp),
                    ) {
                        Column {
                            if (evidence.type == EvidenceType.VISUAL) {
                                resolveMediaUrl(evidence.mediaUrl)?.let { imageUrl ->
                                    KeyframeImage(
                                        imageUrl = imageUrl,
                                        description = evidence.content,
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .height(150.dp)
                                            .clip(RoundedCornerShape(6.dp)),
                                        onClick = { enlargedImage = imageUrl },
                                    )
                                    Spacer(Modifier.height(8.dp))
                                }
                            }
                            Row(verticalAlignment = Alignment.Top) {
                                Icon(evidence.type.let(::evIcon), null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(18.dp))
                                Spacer(Modifier.width(10.dp))
                                Column {
                                    Text(evidence.content, style = MaterialTheme.typography.bodySmall)
                                    Text("置信: ${evidence.confidence.name}", style = MaterialTheme.typography.labelSmall, color = Color(0xFF6B7280))
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    enlargedImage?.let { imageUrl ->
        androidx.compose.ui.window.Dialog(onDismissRequest = { enlargedImage = null }) {
            Box(
                Modifier
                    .fillMaxSize()
                    .background(Color.Black)
                    .clickable { enlargedImage = null },
                contentAlignment = Alignment.Center,
            ) {
                KeyframeImage(
                    imageUrl = imageUrl,
                    description = "关键帧大图",
                    modifier = Modifier.fillMaxWidth().padding(12.dp),
                )
            }
        }
    }
}

@Composable
private fun KeyframeImage(
    imageUrl: String,
    description: String,
    modifier: Modifier,
    onClick: (() -> Unit)? = null,
) {
    SubcomposeAsyncImage(
        model = imageUrl,
        contentDescription = description,
        modifier = modifier.then(
            if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier
        ),
        contentScale = ContentScale.Fit,
        loading = {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(Modifier.size(24.dp), strokeWidth = 2.dp)
            }
        },
        error = {
            Box(
                Modifier.fillMaxSize().background(Color(0xFFF2F4F7)),
                contentAlignment = Alignment.Center,
            ) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Icon(Icons.Default.Image, null, tint = Color(0xFF98A2B3))
                    Spacer(Modifier.height(6.dp))
                    Text(
                        "图片加载失败",
                        style = MaterialTheme.typography.labelSmall,
                        color = Color(0xFF667085),
                    )
                }
            }
        },
        success = { SubcomposeAsyncImageContent() },
    )
}

private const val LONG_PRESS_MS = 250L
