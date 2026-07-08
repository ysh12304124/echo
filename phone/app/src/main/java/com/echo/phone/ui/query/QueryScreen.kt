package com.echo.phone.ui.query

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Send
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

class QueryViewModel(private val repo: EchoRepository) : ViewModel() {
    var question by mutableStateOf("")
    var scope by mutableStateOf(QueryScope.GLOBAL_WORK)
    var result by mutableStateOf<QueryResult?>(null)
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)

    // 范围目标选择
    var memories by mutableStateOf<List<MemorySummary>>(emptyList())
    var spaces by mutableStateOf<List<SpaceMemoryDetail>>(emptyList())
    var selectedMemoryId by mutableStateOf<String?>(null)
    var selectedSpaceId by mutableStateOf<String?>(null)

    init {
        viewModelScope.launch {
            try {
                memories = repo.listMemories(DataPartition.WORK)
                spaces = repo.listSpaces(DataPartition.WORK)
            } catch (_: Exception) {}
        }
    }

    fun submit() {
        if (question.isBlank()) return
        // 范围目标校验
        if (scope == QueryScope.MEMORY && selectedMemoryId == null) {
            error = "请先选择要查询的记忆"; result = null; return
        }
        if (scope == QueryScope.SPACE && selectedSpaceId == null) {
            error = "请先选择要查询的空间"; result = null; return
        }
        viewModelScope.launch {
            loading = true
            error = null
            try {
                result = repo.query(question, scope, selectedMemoryId, selectedSpaceId)
            } catch (e: Exception) {
                error = e.message
            }
            loading = false
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun QueryScreen(onNavigateMemory: (String) -> Unit) {
    val context = LocalContext.current
    val app = context.applicationContext as EchoApplication
    val vm: QueryViewModel = viewModel(
        factory = object : androidx.lifecycle.ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : ViewModel> create(cls: Class<T>): T = QueryViewModel(app.repository) as T
        }
    )

    Column(Modifier.fillMaxSize().padding(16.dp).verticalScroll(rememberScrollState())) {
        Text("查询", style = MaterialTheme.typography.headlineMedium)
        Spacer(Modifier.height(12.dp))

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            FilterChip(
                selected = vm.scope == QueryScope.GLOBAL_WORK,
                onClick = { vm.scope = QueryScope.GLOBAL_WORK },
                label = { Text("全局工作") },
            )
            FilterChip(
                selected = vm.scope == QueryScope.MEMORY,
                onClick = { vm.scope = QueryScope.MEMORY },
                label = { Text("指定记忆") },
            )
            FilterChip(
                selected = vm.scope == QueryScope.SPACE,
                onClick = { vm.scope = QueryScope.SPACE },
                label = { Text("指定空间") },
            )
        }

        // 范围目标选择器
        if (vm.scope == QueryScope.MEMORY) {
            TargetSelector(
                label = "选择记忆",
                options = vm.memories.map { it.memoryId to (it.title.ifBlank { it.identifyBrief }) },
                selectedId = vm.selectedMemoryId,
                onSelect = { vm.selectedMemoryId = it },
            )
        }
        if (vm.scope == QueryScope.SPACE) {
            TargetSelector(
                label = "选择空间",
                options = vm.spaces.map { it.spaceId to (it.title.ifBlank { it.identifyBrief }) },
                selectedId = vm.selectedSpaceId,
                onSelect = { vm.selectedSpaceId = it },
            )
        }

        Spacer(Modifier.height(12.dp))

        OutlinedTextField(
            value = vm.question,
            onValueChange = { vm.question = it },
            modifier = Modifier.fillMaxWidth(),
            placeholder = { Text("输入问题，例如：会议里有没有明确的交付承诺？") },
            trailingIcon = {
                IconButton(onClick = { vm.submit() }, enabled = !vm.loading) {
                    Icon(Icons.Default.Send, "查询")
                }
            },
        )

        Spacer(Modifier.height(16.dp))

        when {
            vm.loading -> CircularProgressIndicator()
            vm.error != null -> Text("查询失败: ${vm.error}", color = MaterialTheme.colorScheme.error)
            vm.result != null -> QueryResultView(vm.result!!, onNavigateMemory)
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun TargetSelector(
    label: String,
    options: List<Pair<String, String>>,
    selectedId: String?,
    onSelect: (String) -> Unit,
) {
    var expanded by remember { mutableStateOf(false) }
    val selectedLabel = options.firstOrNull { it.first == selectedId }?.second ?: "未选择"
    ExposedDropdownMenuBox(expanded = expanded, onExpandedChange = { expanded = it }) {
        OutlinedTextField(
            value = selectedLabel,
            onValueChange = {},
            readOnly = true,
            label = { Text(label) },
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = expanded) },
            modifier = Modifier.fillMaxWidth().menuAnchor(),
        )
        ExposedDropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            if (options.isEmpty()) {
                DropdownMenuItem(text = { Text("暂无可选项") }, onClick = { expanded = false })
            }
            options.forEach { (id, name) ->
                DropdownMenuItem(
                    text = { Text(name) },
                    onClick = { onSelect(id); expanded = false },
                )
            }
        }
    }
}

@Composable
private fun QueryResultView(result: QueryResult, onNavigateMemory: (String) -> Unit) {
    when (result.status) {
        QueryResultStatus.CONFIRMED -> {
            Card(
                Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer),
            ) {
                Column(Modifier.padding(16.dp)) {
                    Text("确定答案", style = MaterialTheme.typography.labelMedium)
                    Text(result.answer ?: "", style = MaterialTheme.typography.bodyLarge)
                }
            }
        }
        QueryResultStatus.POSSIBLE -> {
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp)) {
                    Text("没有确定答案，但找到可能相关的证据", style = MaterialTheme.typography.bodyMedium)
                    result.answer?.let { Text(it, style = MaterialTheme.typography.bodyLarge) }
                    result.uncertaintyReason?.let {
                        Text(it, style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
        }
        QueryResultStatus.NOT_FOUND -> {
            Text("没有找到相关信息", style = MaterialTheme.typography.bodyLarge)
        }
    }

    if (result.sources.isNotEmpty()) {
        Spacer(Modifier.height(12.dp))
        Text("来源记忆", style = MaterialTheme.typography.titleSmall)
        result.sources.forEach { src ->
            Card(
                Modifier.fillMaxWidth().padding(vertical = 4.dp),
            ) {
                Column(Modifier.padding(12.dp)) {
                    Text(src.memoryTitle, style = MaterialTheme.typography.bodyMedium)
                    Text("${src.scene?.name ?: ""} · ${src.timeOffsetSeconds}s", style = MaterialTheme.typography.labelSmall)
                    TextButton(onClick = { onNavigateMemory(src.memoryId) }) { Text("跳转到记忆") }
                }
            }
        }
    }

    if (result.evidences.isNotEmpty()) {
        Spacer(Modifier.height(12.dp))
        Text("证据", style = MaterialTheme.typography.titleSmall)
        result.evidences.forEach { ev ->
            Card(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
                Column(Modifier.padding(12.dp)) {
                    Text("[${ev.type.name}] ${ev.content}")
                    Text("置信: ${ev.confidence.name}", style = MaterialTheme.typography.labelSmall)
                }
            }
        }
    }
}
