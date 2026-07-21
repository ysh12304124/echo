package com.echo.phone.ui.memory

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.FavoriteBorder
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.LockOpen
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import coil.compose.AsyncImage
import com.echo.phone.EchoApplication
import com.echo.phone.data.EchoRepository
import com.echo.phone.domain.ConversationHighlight
import com.echo.phone.domain.EmotionalTone
import com.echo.phone.domain.Participant
import com.echo.phone.domain.QueryResult
import com.echo.phone.domain.QueryResultStatus
import com.echo.phone.domain.QueryScope
import com.echo.phone.domain.TimeMemoryDetail
import com.echo.phone.domain.TimeSpaceBinding
import com.echo.phone.domain.TranscriptSegment
import com.echo.phone.domain.displayName
import com.echo.phone.domain.displayParticipants
import com.echo.phone.domain.formatTimestamp
import com.echo.phone.domain.toPresentation
import kotlinx.coroutines.launch

class MemoryDetailViewModel(
    private val repo: EchoRepository,
    private val memoryId: String,
) : ViewModel() {
    var memory by mutableStateOf<TimeMemoryDetail?>(null)
    var bindings by mutableStateOf<List<TimeSpaceBinding>>(emptyList())
    var queryQuestion by mutableStateOf("")
    var queryResult by mutableStateOf<QueryResult?>(null)
    var loading by mutableStateOf(true)
    var isFavorited by mutableStateOf(false)
    var isLocked by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    private var speakerOverrides by mutableStateOf<Map<String, Participant>>(emptyMap())

    init { load() }

    fun load() {
        viewModelScope.launch {
            loading = true
            try {
                val loadedMemory = repo.getMemory(memoryId)
                memory = loadedMemory
                isFavorited = loadedMemory.isFavorited
                isLocked = loadedMemory.isLocked
                bindings = repo.listMemoryBindings(memoryId)
                error = null
            } catch (e: Exception) {
                error = e.message
            }
            loading = false
        }
    }

    fun transcriptParticipant(segment: TranscriptSegment): Participant? =
        speakerOverrides[segment.segmentId] ?: segment.participant

    /** 先让用户立即看到归属结果；服务端启用写回路由后再持久化该选择。 */
    fun assignSpeaker(segmentId: String, participant: Participant) {
        speakerOverrides = speakerOverrides + (segmentId to participant)
    }

    fun toggleFavorite() {
        viewModelScope.launch {
            isFavorited = !isFavorited
            try {
                repo.toggleFavorite(memoryId, isFavorited)
            } catch (e: Exception) {
                error = e.message
            }
        }
    }

    fun toggleLock() {
        viewModelScope.launch {
            isLocked = !isLocked
            try {
                repo.toggleLock(memoryId, isLocked)
            } catch (e: Exception) {
                error = e.message
            }
        }
    }

    fun delete(onDone: () -> Unit) {
        viewModelScope.launch {
            try {
                repo.deleteMemory(memoryId)
                onDone()
            } catch (e: Exception) {
                error = "删除失败: ${e.message}"
            }
        }
    }

    fun confirmBinding(id: String) {
        viewModelScope.launch {
            try {
                repo.confirmBinding(id)
                bindings = repo.listMemoryBindings(memoryId)
            } catch (e: Exception) {
                error = e.message
            }
        }
    }

    fun rejectBinding(id: String) {
        viewModelScope.launch {
            try {
                repo.rejectBinding(id)
                bindings = repo.listMemoryBindings(memoryId)
            } catch (e: Exception) {
                error = e.message
            }
        }
    }

    fun queryInMemory(preset: String? = null) {
        val question = preset ?: queryQuestion
        if (preset != null) queryQuestion = preset
        if (question.isBlank()) return
        viewModelScope.launch {
            try {
                queryResult = repo.query(question, QueryScope.MEMORY, memoryId)
            } catch (e: Exception) {
                error = e.message
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MemoryDetailScreen(memoryId: String, onBack: () -> Unit, onNavigateSpace: (String) -> Unit = {}) {
    val context = LocalContext.current
    val app = context.applicationContext as EchoApplication
    val viewModel: MemoryDetailViewModel = viewModel(
        factory = object : androidx.lifecycle.ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : ViewModel> create(cls: Class<T>): T =
                MemoryDetailViewModel(app.repository, memoryId) as T
        },
    )
    var showDeleteDialog by remember { mutableStateOf(false) }
    var pendingSpeakerSegment by remember { mutableStateOf<TranscriptSegment?>(null) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(viewModel.memory?.toPresentation()?.title ?: "记忆详情") },
                navigationIcon = {
                    IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "返回") }
                },
                actions = {
                    IconButton(onClick = viewModel::toggleFavorite) {
                        Icon(if (viewModel.isFavorited) Icons.Default.Favorite else Icons.Default.FavoriteBorder, "收藏")
                    }
                    IconButton(onClick = viewModel::toggleLock) {
                        Icon(if (viewModel.isLocked) Icons.Default.Lock else Icons.Default.LockOpen, "锁定")
                    }
                    IconButton(onClick = { showDeleteDialog = true }) { Icon(Icons.Default.Delete, "删除") }
                },
            )
        },
    ) { contentPadding ->
        if (viewModel.loading) {
            Box(
                modifier = Modifier.fillMaxSize().padding(contentPadding),
                contentAlignment = Alignment.Center,
            ) { CircularProgressIndicator() }
            return@Scaffold
        }

        val memory = viewModel.memory ?: return@Scaffold
        val presentation = memory.toPresentation()
        val participants = memory.displayParticipants()
        val speakerChoices = listOf(Participant("self", "我")) + participants

        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(contentPadding),
            contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 20.dp, vertical = 16.dp),
            verticalArrangement = Arrangement.spacedBy(20.dp),
        ) {
            item {
                MemoryContext(memory = memory, overview = presentation.overview)
            }

            item {
                MemorySection(title = if (memory.scene.displayName() == "会议") "与会人" else "同行人物") {
                    if (participants.isEmpty()) {
                        Text("尚未识别到人物", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    } else {
                        LazyRow(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                            items(participants, key = { it.participantId }) { participant ->
                                Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.width(56.dp)) {
                                    ParticipantAvatar(participant, app.repository::absoluteMediaUrl, 50.dp)
                                    Spacer(Modifier.height(5.dp))
                                    Text(participant.name, style = MaterialTheme.typography.labelSmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                }
                            }
                        }
                    }
                }
            }

            item {
                MemorySection(title = if (memory.scene.displayName() == "会议") "会议摘要" else "本次摘要") {
                    val highlights = memory.conversationHighlights
                    if (highlights.isEmpty()) {
                        Text(
                            presentation.overview.ifBlank { "后台完成分析后会显示人物和对话摘要。" },
                            style = MaterialTheme.typography.bodyLarge,
                        )
                    } else {
                        Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
                            highlights.forEach { highlight ->
                                ConversationHighlightRow(highlight, app.repository::absoluteMediaUrl)
                            }
                        }
                    }
                }
            }

            item {
                MemorySection(title = "完整记录") {
                    if (memory.transcriptSegments.isEmpty()) {
                        Text("暂未收到完整语音转写。", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    } else {
                        Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
                            memory.transcriptSegments.forEach { segment ->
                                TranscriptRow(
                                    segment = segment,
                                    participant = viewModel.transcriptParticipant(segment),
                                    avatarUrl = app.repository::absoluteMediaUrl,
                                    onChooseSpeaker = { pendingSpeakerSegment = segment },
                                )
                            }
                        }
                    }
                }
            }

            if (viewModel.bindings.isNotEmpty()) {
                item {
                    MemorySection(title = "关联空间") {
                        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            viewModel.bindings.forEach { binding ->
                                BindingRow(
                                    binding = binding,
                                    onNavigateSpace = onNavigateSpace,
                                    onConfirm = viewModel::confirmBinding,
                                    onReject = viewModel::rejectBinding,
                                )
                            }
                        }
                    }
                }
            }

            item {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        value = viewModel.queryQuestion,
                        onValueChange = { viewModel.queryQuestion = it },
                        modifier = Modifier.fillMaxWidth(),
                        placeholder = { Text("在这条记忆中查询") },
                        leadingIcon = { Icon(Icons.Default.Search, null) },
                        singleLine = true,
                    )
                    Button(onClick = { viewModel.queryInMemory() }, modifier = Modifier.fillMaxWidth()) { Text("查询") }
                }
            }

            viewModel.queryResult?.let { result ->
                item { QueryResultCard(result) }
                items(result.evidences, key = { it.evidenceId }) { evidence ->
                    Text("[${evidence.type.name}] ${evidence.content}", style = MaterialTheme.typography.bodySmall)
                }
            }

            viewModel.error?.let { message ->
                item { Text(message, color = MaterialTheme.colorScheme.error) }
            }
        }

        pendingSpeakerSegment?.let { segment ->
            SpeakerChooser(
                choices = speakerChoices,
                onChoose = { participant ->
                    viewModel.assignSpeaker(segment.segmentId, participant)
                    pendingSpeakerSegment = null
                },
                onDismiss = { pendingSpeakerSegment = null },
            )
        }
    }

    if (showDeleteDialog) {
        AlertDialog(
            onDismissRequest = { showDeleteDialog = false },
            title = { Text("删除记忆") },
            text = { Text(if (viewModel.isLocked) "记忆已锁定，请先解锁再删除。" else "删除后无法恢复，确定删除？") },
            confirmButton = {
                TextButton(
                    enabled = !viewModel.isLocked,
                    onClick = {
                        showDeleteDialog = false
                        app.notifyMemoryDeleted(memoryId)
                        viewModel.delete(onBack)
                    },
                ) { Text("删除") }
            },
            dismissButton = { TextButton(onClick = { showDeleteDialog = false }) { Text("取消") } },
        )
    }
}

@Composable
private fun MemoryContext(memory: TimeMemoryDetail, overview: String) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(memory.toPresentation().title, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.SemiBold)
        Text("时间：${memory.startedAt?.replace('T', ' ')?.take(16) ?: "未标注"}", style = MaterialTheme.typography.bodyMedium)
        Text("地点：${memory.location.ifBlank { "未标注" }}", style = MaterialTheme.typography.bodyMedium)
        if (overview.isNotBlank()) {
            Spacer(Modifier.height(4.dp))
            Text(overview, style = MaterialTheme.typography.bodyLarge)
        }
    }
}

@Composable
private fun MemorySection(title: String, content: @Composable ColumnScope.() -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
        content()
    }
}

@Composable
private fun ConversationHighlightRow(highlight: ConversationHighlight, avatarUrl: (String?) -> String?) {
    Row(verticalAlignment = Alignment.Top) {
        ParticipantAvatar(highlight.participant, avatarUrl, 52.dp)
        Spacer(Modifier.width(10.dp))
        EmotionBadge(highlight.emotion)
        Spacer(Modifier.width(10.dp))
        Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
            Text(highlight.participant?.name ?: "未识别人物", style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.Medium)
            Text(highlight.content, style = MaterialTheme.typography.bodyLarge)
        }
    }
}

@Composable
private fun EmotionBadge(emotion: EmotionalTone) {
    val (label, color) = when (emotion) {
        EmotionalTone.HAPPY -> "开心" to Color(0xFF2E7D32)
        EmotionalTone.ANGRY -> "愤怒" to Color(0xFFC62828)
        EmotionalTone.SAD -> "难过" to Color(0xFF546E7A)
        EmotionalTone.EXCITED -> "兴奋" to Color(0xFFF57C00)
        EmotionalTone.NEUTRAL -> "平静" to Color(0xFF607D8B)
    }
    Box(
        modifier = Modifier.size(38.dp).clip(androidx.compose.foundation.shape.RoundedCornerShape(8.dp)).background(color),
        contentAlignment = Alignment.Center,
    ) {
        Text(label, color = Color.White, style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.Bold)
    }
}

@Composable
private fun TranscriptRow(
    segment: TranscriptSegment,
    participant: Participant?,
    avatarUrl: (String?) -> String?,
    onChooseSpeaker: () -> Unit,
) {
    Row(verticalAlignment = Alignment.Top) {
        Text(segment.timestampMs.formatTimestamp(), modifier = Modifier.width(48.dp), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        if (participant == null) {
            OutlinedButton(onClick = onChooseSpeaker, modifier = Modifier.height(38.dp)) {
                Icon(Icons.Default.Person, null, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(4.dp))
                Text("选择", style = MaterialTheme.typography.labelSmall)
            }
        } else {
            ParticipantAvatar(participant, avatarUrl, 38.dp)
        }
        Spacer(Modifier.width(10.dp))
        Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            participant?.let { Text(it.name, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant) }
            Text(segment.content, style = MaterialTheme.typography.bodyLarge)
        }
    }
}

@Composable
private fun ParticipantAvatar(participant: Participant?, avatarUrl: (String?) -> String?, size: Dp) {
    val shape = androidx.compose.foundation.shape.CircleShape
    val resolvedUrl = participant?.avatarUrl?.let(avatarUrl)
    if (resolvedUrl != null) {
        AsyncImage(
            model = resolvedUrl,
            contentDescription = participant.name,
            modifier = Modifier.size(size).clip(shape).border(1.dp, MaterialTheme.colorScheme.outlineVariant, shape),
            contentScale = ContentScale.Crop,
        )
    } else {
        Box(
            modifier = Modifier.size(size).clip(shape).background(MaterialTheme.colorScheme.secondaryContainer),
            contentAlignment = Alignment.Center,
        ) {
            Text(participant?.name?.firstOrNull()?.toString() ?: "?", style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.onSecondaryContainer)
        }
    }
}

@Composable
private fun BindingRow(
    binding: TimeSpaceBinding,
    onNavigateSpace: (String) -> Unit,
    onConfirm: (String) -> Unit,
    onReject: (String) -> Unit,
) {
    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
        Text(if (binding.userConfirmed) "已关联" else "候选关联", modifier = Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium)
        binding.spaceMemoryId?.let { spaceId -> TextButton(onClick = { onNavigateSpace(spaceId) }) { Text("查看") } }
        if (!binding.userConfirmed) {
            TextButton(onClick = { onConfirm(binding.bindingId) }) { Text("确认") }
            TextButton(onClick = { onReject(binding.bindingId) }) { Text("否定") }
        }
    }
}

@Composable
private fun QueryResultCard(result: QueryResult) {
    val color = when (result.status) {
        QueryResultStatus.CONFIRMED -> MaterialTheme.colorScheme.primaryContainer
        QueryResultStatus.POSSIBLE -> MaterialTheme.colorScheme.secondaryContainer
        QueryResultStatus.NOT_FOUND -> MaterialTheme.colorScheme.surfaceVariant
    }
    Card(modifier = Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = color)) {
        Text(
            when (result.status) {
                QueryResultStatus.CONFIRMED -> result.answer.orEmpty()
                QueryResultStatus.POSSIBLE -> "可能相关：${result.uncertaintyReason ?: "证据置信度不足"}"
                QueryResultStatus.NOT_FOUND -> "没有找到相关信息"
            },
            modifier = Modifier.padding(16.dp),
        )
    }
}

@Composable
private fun SpeakerChooser(choices: List<Participant>, onChoose: (Participant) -> Unit, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("这是谁在说话？") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                choices.distinctBy { it.participantId }.forEach { participant ->
                    TextButton(onClick = { onChoose(participant) }, modifier = Modifier.fillMaxWidth()) {
                        Text(participant.name, modifier = Modifier.weight(1f))
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("取消") } },
    )
}
