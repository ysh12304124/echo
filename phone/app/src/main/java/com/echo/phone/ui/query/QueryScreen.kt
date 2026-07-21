package com.echo.phone.ui.query

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
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
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Image
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Notes
import androidx.compose.material.icons.filled.Send
import androidx.compose.material.icons.filled.TextFields
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material.icons.filled.ViewInAr
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
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
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.changedToUpIgnoreConsumed
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.LayoutCoordinates
import androidx.compose.ui.layout.boundsInRoot
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInRoot
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
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

enum class QueryInputSource { TYPED, VOICE_TRANSCRIPT }

class QueryViewModel(
    private val repo: com.echo.phone.data.EchoRepository,
    private val recorder: VoiceQueryRecorder = VoiceQueryRecorder(),
) : ViewModel() {
    var question by mutableStateOf("")
    var result by mutableStateOf<QueryResult?>(null)
    var submittedQuery by mutableStateOf<String?>(null)
    var submittedQuerySource by mutableStateOf<QueryInputSource?>(null)
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
        val query = question.trim()
        question = ""
        submittedQuery = query
        submittedQuerySource = QueryInputSource.TYPED
        viewModelScope.launch {
            loading = true
            error = null
            result = null
            try {
                result = repo.query(query, com.echo.phone.domain.QueryScope.GLOBAL_WORK)
            } catch (exception: Exception) {
                error = exception.message ?: "查询失败"
            } finally {
                loading = false
            }
        }
    }

    fun startVoiceRecording(): Boolean {
        if (loading || voicePhase != VoicePhase.IDLE || finishing) {
            if (voicePhase == VoicePhase.IDLE) error = "无法启动麦克风，请稍后重试"
            return false
        }
        val started = try {
            recorder.start()
        } catch (error: Throwable) {
            false
        }
        if (!started) {
            if (voicePhase == VoicePhase.IDLE) error = "无法启动麦克风，请检查录音权限"
            return false
        }
        error = null
        result = null
        submittedQuery = null
        submittedQuerySource = null
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
            voicePhase = VoicePhase.IDLE
            showVoiceFeedback("已取消录音")
            viewModelScope.launch {
                try {
                    recorder.cancelAndDiscard()
                } catch (_: Throwable) {
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
                    error = "没有采集到语音"
                    return@launch
                }
                if (audio.size < VoiceQueryRecorder.MIN_BYTES) {
                    error = "语音太短，请长按并说完整问题"
                    return@launch
                }

                val transcription = repo.transcribeVoice(audio)
                val query = transcription.transcript.trim()
                question = ""
                submittedQuery = query.ifBlank { null }
                submittedQuerySource = if (query.isBlank()) null else QueryInputSource.VOICE_TRANSCRIPT
                if (!transcription.asrAccepted) {
                    error = transcription.rejectionReason ?: "没听清，请再说一次"
                    return@launch
                }
                voicePhase = VoicePhase.SEARCHING
                result = repo.query(
                    query,
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
    var inputCoordinates by remember { mutableStateOf<LayoutCoordinates?>(null) }
    val density = LocalDensity.current
    val imeBottom = WindowInsets.ime.getBottom(density)
    val keyboardVisible = imeBottom > 0

    Box(Modifier.fillMaxSize()) {
        Column(
            Modifier
                .fillMaxSize()
                .padding(horizontal = 20.dp)
                .padding(top = 20.dp, bottom = 16.dp),
        ) {
            Text("查询", style = MaterialTheme.typography.headlineMedium)

            Column(
                Modifier
                    .weight(1f)
                    .fillMaxWidth()
                    .verticalScroll(rememberScrollState()),
            ) {
                Spacer(Modifier.height(16.dp))
                vm.submittedQuery?.let { submittedQuery ->
                    if (vm.voicePhase != VoicePhase.RECORDING) {
                        SubmittedQueryPreview(
                            query = submittedQuery,
                            source = vm.submittedQuerySource,
                        )
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
                Spacer(Modifier.height(if (keyboardVisible) 12.dp else 4.dp))
            }

            Spacer(Modifier.height(if (keyboardVisible) 8.dp else 12.dp))
            QueryInputBar(
                question = vm.question,
                onQuestionChange = { vm.question = it },
                enabled = !vm.loading && vm.voicePhase == VoicePhase.IDLE,
                sendEnabled = vm.question.isNotBlank() && !vm.loading && vm.voicePhase == VoicePhase.IDLE,
                feedback = vm.voiceFeedback,
                compact = keyboardVisible,
                onSend = { vm.submit() },
                inputModifier = Modifier
                    .onGloballyPositioned { inputCoordinates = it }
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
                                val rootPosition = inputCoordinates?.positionInRoot()?.plus(change.position)
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
            )
        }

        if (vm.voicePhase == VoicePhase.RECORDING) {
            VoiceRecordingOverlay(
                seconds = vm.recordingSeconds,
                cancelActive = vm.cancelTargetActive,
                onCancelTargetPositioned = { cancelTargetCoordinates = it },
            )
        }
    }
}

@Composable
private fun QueryInputBar(
    question: String,
    onQuestionChange: (String) -> Unit,
    enabled: Boolean,
    sendEnabled: Boolean,
    feedback: String?,
    compact: Boolean,
    onSend: () -> Unit,
    inputModifier: Modifier,
    modifier: Modifier = Modifier,
) {
    Column(modifier.fillMaxWidth()) {
        Row(
            Modifier
                .fillMaxWidth()
                .height(58.dp)
                .shadow(5.dp, RoundedCornerShape(29.dp))
                .clip(RoundedCornerShape(29.dp))
                .background(Color.White)
                .border(1.dp, Color(0xFFE4E7EC), RoundedCornerShape(29.dp))
                .padding(start = 18.dp, end = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                inputModifier
                    .weight(1f)
                    .height(48.dp),
                contentAlignment = Alignment.CenterStart,
            ) {
                BasicTextField(
                    value = question,
                    onValueChange = onQuestionChange,
                    modifier = Modifier.fillMaxWidth(),
                    enabled = enabled,
                    singleLine = true,
                    textStyle = MaterialTheme.typography.bodyLarge.copy(color = Color(0xFF111827)),
                )
                if (question.isBlank()) {
                    Text(
                        "输入问题，或长按说话...",
                        style = MaterialTheme.typography.bodyLarge,
                        color = Color(0xFF98A2B3),
                    )
                }
            }
            Spacer(Modifier.width(8.dp))
            IconButton(onClick = onSend, enabled = sendEnabled) {
                Icon(
                    Icons.Default.Send,
                    contentDescription = "发送查询",
                    tint = if (sendEnabled) MaterialTheme.colorScheme.primary else Color(0xFF98A2B3),
                )
            }
        }
        val prompt = feedback ?: "短按输入文字，长按输入框说话"
        if (!compact || feedback != null) {
            Spacer(Modifier.height(6.dp))
            Text(
                prompt,
                modifier = Modifier.align(Alignment.CenterHorizontally),
                style = MaterialTheme.typography.labelSmall,
                color = Color(0xFF98A2B3),
            )
        }
    }
}

@Composable
private fun VoiceRecordingOverlay(
    seconds: Int,
    cancelActive: Boolean,
    onCancelTargetPositioned: (LayoutCoordinates) -> Unit,
) {
    Box(
        Modifier
            .fillMaxSize()
            .background(Color.Black.copy(alpha = 0.68f)),
    ) {
        Box(
            Modifier
                .align(Alignment.BottomEnd)
                .padding(end = 26.dp, bottom = 176.dp)
                .size(width = 136.dp, height = 68.dp)
                .onGloballyPositioned(onCancelTargetPositioned)
                .clip(RoundedCornerShape(34.dp))
                .background(if (cancelActive) Color(0xFFFF4D4F) else Color.White.copy(alpha = 0.18f))
                .border(1.dp, Color.White.copy(alpha = 0.24f), RoundedCornerShape(34.dp)),
            contentAlignment = Alignment.Center,
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Default.Close, contentDescription = "取消录音", tint = Color.White, modifier = Modifier.size(22.dp))
                Spacer(Modifier.width(6.dp))
                Text(if (cancelActive) "松手取消" else "取消", color = Color.White, style = MaterialTheme.typography.labelLarge)
            }
        }

        Column(
            Modifier
                .align(Alignment.Center)
                .padding(bottom = 96.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            VoiceWaveBubble(cancelActive = cancelActive)
            Spacer(Modifier.height(12.dp))
            Text(
                "00:${seconds.toString().padStart(2, '0')}",
                color = Color.White.copy(alpha = 0.86f),
                style = MaterialTheme.typography.titleMedium,
            )
        }

        Box(
            Modifier
                .align(Alignment.BottomCenter)
                .fillMaxWidth()
                .height(168.dp)
                .clip(RoundedCornerShape(topStart = 220.dp, topEnd = 220.dp))
                .background(Color.White.copy(alpha = 0.78f)),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                if (cancelActive) "移出取消区可发送" else "松开 发送",
                color = Color(0xFF111827),
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.Bold,
            )
        }
    }
}

@Composable
private fun VoiceWaveBubble(cancelActive: Boolean) {
    val bubbleColor = if (cancelActive) Color(0xFFFF4D4F) else Color(0xFF91EF67)
    Canvas(Modifier.size(width = 232.dp, height = 110.dp)) {
        val bubbleHeight = size.height - 22f
        drawRoundRect(
            color = bubbleColor,
            size = androidx.compose.ui.geometry.Size(size.width, bubbleHeight),
            cornerRadius = CornerRadius(30f, 30f),
        )
        val tail = Path().apply {
            moveTo(size.width / 2f - 18f, bubbleHeight - 1f)
            lineTo(size.width / 2f, size.height)
            lineTo(size.width / 2f + 18f, bubbleHeight - 1f)
            close()
        }
        drawPath(tail, bubbleColor)

        val bars = listOf(9f, 12f, 8f, 14f, 22f, 34f, 17f, 13f, 28f, 12f, 9f)
        val centerY = bubbleHeight / 2f
        val startX = size.width / 2f - (bars.size - 1) * 5f
        bars.forEachIndexed { index, height ->
            val x = startX + index * 10f
            drawLine(
                color = Color(0xFF425466),
                start = Offset(x, centerY - height / 2f),
                end = Offset(x, centerY + height / 2f),
                strokeWidth = 4f,
            )
        }
    }
}

@Composable
private fun SubmittedQueryPreview(query: String, source: QueryInputSource?) {
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
                when (source) {
                    QueryInputSource.VOICE_TRANSCRIPT -> "本次查询 · 语音转录"
                    QueryInputSource.TYPED -> "本次查询 · 键盘输入"
                    null -> "本次查询"
                },
                style = MaterialTheme.typography.labelMedium,
                color = Color(0xFF667085),
            )
            Spacer(Modifier.height(4.dp))
            Text(query, style = MaterialTheme.typography.bodyMedium)
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
                    .filter {
                        it.type == EvidenceType.VISUAL &&
                            it.usedInAnswer &&
                            it.mediaUrl != null
                    }
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
                                    val confidenceText = when (evidence.confidence) {
                                        com.echo.phone.domain.ConfidenceLevel.HIGH -> "高"
                                        com.echo.phone.domain.ConfidenceLevel.MEDIUM -> "中"
                                        com.echo.phone.domain.ConfidenceLevel.LOW -> "低"
                                    }
                                    val evidenceStatus = if (evidence.usedInAnswer) "已用于回答" else "候选证据"
                                    val detail = if (evidence.retrievalScore != null) {
                                        val scorer = if (evidence.type == EvidenceType.VISUAL) "CLIP" else "Reranker"
                                        "相关性: $confidenceText · $scorer %.3f · $evidenceStatus"
                                            .format(evidence.retrievalScore)
                                    } else {
                                        "来源置信: $confidenceText · $evidenceStatus"
                                    }
                                    Text(detail, style = MaterialTheme.typography.labelSmall, color = Color(0xFF6B7280))
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
