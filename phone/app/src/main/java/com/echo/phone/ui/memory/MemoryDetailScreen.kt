package com.echo.phone.ui.memory

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.FavoriteBorder
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.LockOpen
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
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
                memory = m
                isFavorited = m.isFavorited
                bindings = repo.listMemoryBindings(memoryId)
            } catch (e: Exception) {
                error = e.message
            }
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
            } catch (e: Exception) { error = e.message }
        }
    }

    fun rejectBinding(id: String) {
        viewModelScope.launch {
            try {
                repo.rejectBinding(id)
                bindings = repo.listMemoryBindings(memoryId)
            } catch (e: Exception) { error = e.message }
        }
    }

    fun queryInMemory(preset: String? = null) {
        val q = preset ?: queryQuestion
        if (preset != null) queryQuestion = preset
        if (q.isBlank()) return
        viewModelScope.launch {
            try {
                queryResult = repo.query(q, QueryScope.MEMORY, memoryId)
            } catch (e: Exception) { error = e.message }
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

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(vm.memory?.title ?: "记忆详情") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, "返回")
                    }
                },
                actions = {
                    IconButton(onClick = { vm.toggleFavorite() }) {
                        Icon(
                            if (vm.isFavorited) Icons.Default.Favorite else Icons.Default.FavoriteBorder,
                            "收藏",
                        )
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
    ) { padding ->
        if (vm.loading) {
            Box(Modifier.fillMaxSize().padding(padding), contentAlignment = androidx.compose.ui.Alignment.Center) {
                CircularProgressIndicator()
            }
            return@Scaffold
        }

        val memory = vm.memory ?: return@Scaffold

        LazyColumn(Modifier.fillMaxSize().padding(padding).padding(16.dp)) {
            item {
                Text("${memory.scene.name} · ${memory.partition.name}", style = MaterialTheme.typography.labelMedium)
                Text(memory.identifyBrief, style = MaterialTheme.typography.bodyLarge)
                Spacer(Modifier.height(16.dp))
            }

            // 候选时空绑定：让用户确认/否定
            if (vm.bindings.isNotEmpty()) {
                item {
                    Text("关联空间", style = MaterialTheme.typography.titleMedium)
                }
                items(vm.bindings) { b ->
                    Card(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
                        Column(Modifier.padding(12.dp)) {
                            Text(
                                if (b.userConfirmed) "已确认关联空间" else "候选关联空间（并行采集）",
                                style = MaterialTheme.typography.bodyMedium,
                            )
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
                item { Spacer(Modifier.height(16.dp)) }
            }

            item {
                Text("导航型摘要", style = MaterialTheme.typography.titleMedium)
                memory.navigationSummary?.let { nav ->
                    if (nav.persons.isNotEmpty()) Text("人物: ${nav.persons.joinToString()}")
                    if (nav.topics.isNotEmpty()) Text("话题: ${nav.topics.joinToString()}")
                    nav.keyMoments.forEach { km ->
                        Text("· ${km.label} (${km.timeOffsetSeconds}s)")
                    }
                }
                Spacer(Modifier.height(16.dp))
            }

            item {
                Text("在此记忆中查询", style = MaterialTheme.typography.titleMedium)
                OutlinedTextField(
                    value = vm.queryQuestion,
                    onValueChange = { vm.queryQuestion = it },
                    modifier = Modifier.fillMaxWidth(),
                    placeholder = { Text("这段记忆里答应了什么？") },
                )
                Button(onClick = { vm.queryInMemory() }, modifier = Modifier.padding(top = 8.dp)) {
                    Text("查询")
                }
                vm.queryResult?.let { result ->
                    Spacer(Modifier.height(8.dp))
                    Text(
                        when (result.status) {
                            QueryResultStatus.CONFIRMED -> result.answer ?: ""
                            QueryResultStatus.POSSIBLE ->
                                "可能相关：${result.uncertaintyReason ?: "证据置信度不足"}"
                            QueryResultStatus.NOT_FOUND -> "没有找到相关信息"
                        },
                    )
                    result.evidences.forEach { ev ->
                        Card(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
                            Column(Modifier.padding(12.dp)) {
                                Text("[${ev.type.name}] ${ev.content}")
                                Text("置信: ${ev.confidence.name}", style = MaterialTheme.typography.labelSmall)
                            }
                        }
                    }
                }
                Spacer(Modifier.height(16.dp))
            }

            memory.navigationSummary?.suggestedQuestions?.let { questions ->
                item { Text("可问问题", style = MaterialTheme.typography.titleSmall) }
                items(questions) { q ->
                    SuggestionChip(onClick = { vm.queryInMemory(q) }, label = { Text(q) })
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
                TextButton(
                    enabled = !vm.isLocked,
                    onClick = {
                        showDeleteDialog = false
                        vm.delete(onBack)
                    },
                ) { Text("删除") }
            },
            dismissButton = {
                TextButton(onClick = { showDeleteDialog = false }) { Text("取消") }
            },
        )
    }
}
