package com.echo.phone.ui.memory

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.clickable
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.FavoriteBorder
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.LockOpen
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import coil.compose.AsyncImage
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.foundation.layout.Column
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.echo.phone.EchoApplication
import com.echo.phone.data.EchoRepository
import com.echo.phone.domain.*
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

    init { load() }

    fun load() {
        viewModelScope.launch {
            loading = true
            try {
                val m = repo.getMemory(memoryId)
                memory = m; isFavorited = m.isFavorited; isLocked = m.isLocked
                bindings = repo.listMemoryBindings(memoryId)
            } catch (e: Exception) { error = e.message }
            loading = false
        }
    }

    fun toggleFavorite() {
        viewModelScope.launch {
            isFavorited = !isFavorited
            try { repo.toggleFavorite(memoryId, isFavorited) } catch (e: Exception) { error = e.message }
        }
    }

    fun toggleLock() {
        viewModelScope.launch {
            isLocked = !isLocked
            try { repo.toggleLock(memoryId, isLocked) } catch (e: Exception) { error = e.message }
        }
    }

    fun delete(onDone: () -> Unit) {
        viewModelScope.launch {
            try { repo.deleteMemory(memoryId); onDone() }
            catch (e: Exception) { error = "删除失败: ${e.message}" }
        }
    }

    fun confirmBinding(id: String) {
        viewModelScope.launch {
            try { repo.confirmBinding(id); bindings = repo.listMemoryBindings(memoryId) }
            catch (e: Exception) { error = e.message }
        }
    }

    fun rejectBinding(id: String) {
        viewModelScope.launch {
            try { repo.rejectBinding(id); bindings = repo.listMemoryBindings(memoryId) }
            catch (e: Exception) { error = e.message }
        }
    }

    fun queryInMemory(preset: String? = null) {
        val q = preset ?: queryQuestion
        if (preset != null) queryQuestion = preset
        if (q.isBlank()) return
        viewModelScope.launch {
            try { queryResult = repo.query(q, QueryScope.MEMORY, memoryId) }
            catch (e: Exception) { error = e.message }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MemoryDetailScreen(memoryId: String, onBack: () -> Unit, onNavigateSpace: (String) -> Unit = {}) {
    val context = LocalContext.current
    val app = context.applicationContext as EchoApplication
    val vm: MemoryDetailViewModel = viewModel(
        factory = object : androidx.lifecycle.ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : ViewModel> create(cls: Class<T>): T =
                MemoryDetailViewModel(app.repository, memoryId) as T
        }
    )
    var showDeleteDialog by remember { mutableStateOf(false) }
    val density = LocalDensity.current
    val keyboardVisible = WindowInsets.ime.getBottom(density) > 0
    val focusManager = LocalFocusManager.current

    val submitMemoryQuery = {
        vm.queryInMemory()
        focusManager.clearFocus()
    }

    Scaffold(
        modifier = Modifier
            .imePadding()
            .padding(bottom = if (keyboardVisible) 12.dp else 0.dp),
        contentWindowInsets = if (keyboardVisible) {
            WindowInsets.safeDrawing.only(WindowInsetsSides.Top + WindowInsetsSides.Horizontal)
        } else {
            ScaffoldDefaults.contentWindowInsets
        },
        topBar = {
            TopAppBar(
                title = { Text(vm.memory?.title ?: "记忆详情") },
                navigationIcon = {
                    IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "返回") }
                },
                actions = {
                    IconButton(onClick = { vm.toggleFavorite() }) {
                        Icon(if (vm.isFavorited) Icons.Default.Favorite else Icons.Default.FavoriteBorder, "收藏")
                    }
                    IconButton(onClick = { vm.toggleLock() }) {
                        Icon(if (vm.isLocked) Icons.Default.Lock else Icons.Default.LockOpen, "锁定")
                    }
                    IconButton(onClick = { showDeleteDialog = true }) {
                        Icon(Icons.Default.Delete, "删除")
                    }
                },
            )
        },
        bottomBar = {
            if (!vm.loading && vm.memory != null) {
                MemoryQueryInputRow(
                    question = vm.queryQuestion,
                    onQuestionChange = { vm.queryQuestion = it },
                    onSubmit = submitMemoryQuery,
                    modifier = Modifier.padding(horizontal = 16.dp),
                )
            }
        },
    ) { padding ->
        if (vm.loading) {
            Box(Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
            return@Scaffold
        }

        val memory = vm.memory ?: return@Scaffold
        val nav = memory.navigationSummary

        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding),
            contentPadding = PaddingValues(
                start = 16.dp,
                top = 16.dp,
                end = 16.dp,
                bottom = 16.dp,
            ),
        ) {
            // 基本信息
            item {
                Text("${memory.scene.name} · ${memory.partition.name} · ${memory.durationSeconds}s",
                    style = MaterialTheme.typography.labelMedium)
                Spacer(Modifier.height(8.dp))
            }

            // 总结
            item {
                DetailSection("总结") {
                    Text(memory.identifyBrief, style = MaterialTheme.typography.bodyLarge)
                }
            }

            // 人物
            if (nav?.persons?.isNotEmpty() == true) {
                item {
                    DetailSection("人物") {
                        Text(nav.persons.joinToString("、"), style = MaterialTheme.typography.bodyMedium)
                    }
                }
            }

            // 话题
            if (nav?.topics?.isNotEmpty() == true) {
                item {
                    DetailSection("话题") {
                        Text(nav.topics.joinToString("、"), style = MaterialTheme.typography.bodyMedium)
                    }
                }
            }

            // 关键帧图片
            if (memory.keyFrames.isNotEmpty()) {
                item {
                    DetailSection("关键瞬间") {
                        var selectedIndex by remember { mutableIntStateOf(-1) }
                        Column {
                            memory.keyFrames.forEachIndexed { idx, kf ->
                                val imgUrl = app.repository.absoluteMediaUrl(kf.mediaUrl)
                                AsyncImage(
                                    model = imgUrl,
                                    contentDescription = "关键帧",
                                    modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp).clip(RoundedCornerShape(12.dp)).clickable { selectedIndex = idx },
                                    contentScale = ContentScale.FillWidth,
                                )
                            }
                        }
                        if (selectedIndex >= 0) {
                            androidx.compose.ui.window.Dialog(onDismissRequest = { selectedIndex = -1 }) {
                                Box(Modifier.fillMaxSize().clickable { selectedIndex = -1 }, contentAlignment = Alignment.Center) {
                                    val pagerState = rememberPagerState(initialPage = selectedIndex, pageCount = { memory.keyFrames.size })
                                    HorizontalPager(state = pagerState, modifier = Modifier.fillMaxSize()) { page ->
                                        val imgUrl = app.repository.absoluteMediaUrl(memory.keyFrames[page].mediaUrl)
                                        AsyncImage(model = imgUrl, contentDescription = "关键帧", modifier = Modifier.fillMaxSize().padding(8.dp), contentScale = ContentScale.Fit)
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // 时间
            item {
                DetailSection("时间") {
                    val timeText = memory.startedAt?.let {
                        val date = it.substring(0, 10)
                        val t = it.substring(11, 16)
                        "$date $t"
                    } ?: "未知"
                    Text(timeText, style = MaterialTheme.typography.bodyMedium)
                }
            }

            // 可问问题
            nav?.suggestedQuestions?.let { questions ->
                if (questions.isNotEmpty()) {
                    item {
                        DetailSection("可问问题") {
                            Column { questions.forEach { q -> SuggestionChip(onClick = { vm.queryInMemory(q) }, label = { Text(q) }) } }
                        }
                    }
                }
            }

            // 时空绑定
            if (vm.bindings.isNotEmpty()) {
                item { DetailSection("关联空间") {} }
                items(vm.bindings) { b ->
                    Card(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
                        Column(Modifier.padding(12.dp)) {
                            Text(if (b.userConfirmed) "已确认" else "候选（并行采集）", style = MaterialTheme.typography.bodySmall)
                            b.spaceMemoryId?.let { sid ->
                                TextButton(onClick = { onNavigateSpace(sid) }) { Text("查看空间") }
                            }
                            if (!b.userConfirmed) {
                                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                    Button(onClick = { vm.confirmBinding(b.bindingId) }) { Text("确认") }
                                    OutlinedButton(onClick = { vm.rejectBinding(b.bindingId) }) { Text("否定") }
                                }
                            }
                        }
                    }
                }
            }

            // 查询结果
            vm.queryResult?.let { result ->
                item {
                    Spacer(Modifier.height(8.dp))
                    Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(
                        containerColor = when (result.status) {
                            QueryResultStatus.CONFIRMED -> MaterialTheme.colorScheme.primaryContainer
                            QueryResultStatus.POSSIBLE -> MaterialTheme.colorScheme.secondaryContainer
                            QueryResultStatus.NOT_FOUND -> MaterialTheme.colorScheme.surfaceVariant
                        }
                    )) {
                        Column(Modifier.padding(16.dp)) {
                            Text(
                                when (result.status) {
                                    QueryResultStatus.CONFIRMED -> result.answer ?: ""
                                    QueryResultStatus.POSSIBLE -> "可能相关：${result.uncertaintyReason ?: "证据置信度不足"}"
                                    QueryResultStatus.NOT_FOUND -> "没有找到相关信息"
                                },
                            )
                        }
                    }
                }
                items(result.evidences) { ev ->
                    Card(Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
                        Column(Modifier.padding(12.dp)) {
                            Text("[${ev.type.name}] ${ev.content}", style = MaterialTheme.typography.bodySmall)
                        }
                    }
                }
            }

            vm.error?.let { item { Text(it, color = MaterialTheme.colorScheme.error) } }
        }
    }

    if (showDeleteDialog) {
        AlertDialog(
            onDismissRequest = { showDeleteDialog = false },
            title = { Text("删除记忆") },
            text = { Text(if (vm.isLocked) "记忆已锁定，请先解锁再删除。" else "删除后无法恢复，确定删除？") },
            confirmButton = {
                TextButton(enabled = !vm.isLocked, onClick = { showDeleteDialog = false; app.notifyMemoryDeleted(memoryId); vm.delete(onBack) }) { Text("删除") }
            },
            dismissButton = { TextButton(onClick = { showDeleteDialog = false }) { Text("取消") } },
        )
    }
}

@Composable
private fun MemoryQueryInputRow(
    question: String,
    onQuestionChange: (String) -> Unit,
    onSubmit: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        OutlinedTextField(
            value = question,
            onValueChange = onQuestionChange,
            modifier = Modifier.weight(1f),
            placeholder = { Text("在此记忆中查询…") },
            leadingIcon = { Icon(Icons.Default.Search, null) },
            singleLine = true,
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
            keyboardActions = KeyboardActions(onSearch = { onSubmit() }),
        )
        Box(
            modifier = Modifier
                .width(60.dp)
                .height(48.dp)
                .clip(RoundedCornerShape(24.dp))
                .clickable(
                    enabled = question.isNotBlank(),
                    role = Role.Button,
                    onClick = onSubmit,
                ),
            contentAlignment = Alignment.Center,
        ) {
            Box(
                modifier = Modifier
                    .width(56.dp)
                    .height(36.dp)
                    .clip(RoundedCornerShape(18.dp))
                    .background(
                        if (question.isNotBlank()) MaterialTheme.colorScheme.primary
                        else MaterialTheme.colorScheme.primary.copy(alpha = 0.38f),
                    ),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    Icons.Default.ArrowUpward,
                    contentDescription = "发送查询",
                    tint = MaterialTheme.colorScheme.onPrimary.copy(
                        alpha = if (question.isNotBlank()) 1f else 0.72f,
                    ),
                    modifier = Modifier.size(19.dp),
                )
            }
        }
    }
}

@Composable
private fun DetailSection(title: String, content: @Composable ColumnScope.() -> Unit) {
    Card(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
        Column(Modifier.padding(16.dp)) {
            Text(title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(4.dp))
            content()
        }
    }
}
