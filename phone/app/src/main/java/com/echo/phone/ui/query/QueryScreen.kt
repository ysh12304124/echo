package com.echo.phone.ui.query

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.echo.phone.EchoApplication
import com.echo.phone.domain.*
import kotlinx.coroutines.launch

class QueryViewModel(private val repo: com.echo.phone.data.EchoRepository) : ViewModel() {
    var question by mutableStateOf("")
    var scope by mutableStateOf(QueryScope.GLOBAL_WORK)
    var result by mutableStateOf<QueryResult?>(null)
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var selectedMemoryId by mutableStateOf<String?>(null)
    var selectedSpaceId by mutableStateOf<String?>(null)

    fun submit() {
        if (question.isBlank()) return
        viewModelScope.launch {
            loading = true; error = null
            try { result = repo.query(question, scope, selectedMemoryId, selectedSpaceId) }
            catch (e: Exception) { error = e.message }
            loading = false
        }
    }
}

private fun evidenceIcon(type: EvidenceType): ImageVector = when (type) {
    EvidenceType.VISUAL -> Icons.Default.Image
    EvidenceType.TRANSCRIPT -> Icons.Default.Mic
    EvidenceType.OCR -> Icons.Default.TextFields
    EvidenceType.SPATIAL -> Icons.Default.ViewInAr
    EvidenceType.USER_NOTE -> Icons.Default.Notes
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun QueryScreen(onNavigateMemory: (String) -> Unit) {
    val context = LocalContext.current
    val app = context.applicationContext as EchoApplication
    val vm: QueryViewModel = viewModel(
        factory = object : androidx.lifecycle.ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : ViewModel> create(cls: Class<T>): T =
                QueryViewModel(app.repository) as T
        }
    )

    Column(Modifier.fillMaxSize().padding(16.dp)) {
        Text("查询", style = MaterialTheme.typography.headlineMedium)
        Spacer(Modifier.height(12.dp))

        // 范围筛选
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            FilterChip(selected = vm.scope == QueryScope.GLOBAL_WORK, onClick = { vm.scope = QueryScope.GLOBAL_WORK }, label = { Text("全局工作") })
            FilterChip(selected = vm.scope == QueryScope.MEMORY, onClick = { vm.scope = QueryScope.MEMORY }, label = { Text("当前记忆") })
            FilterChip(selected = vm.scope == QueryScope.SPACE, onClick = { vm.scope = QueryScope.SPACE }, label = { Text("当前空间") })
        }
        Spacer(Modifier.height(12.dp))

        // 查询框
        OutlinedTextField(
            value = vm.question,
            onValueChange = { vm.question = it },
            modifier = Modifier.fillMaxWidth(),
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
            shape = MaterialTheme.shapes.medium,
        )
        Spacer(Modifier.height(16.dp))

        when {
            vm.loading -> CircularProgressIndicator()
            vm.error != null -> Text("查询失败: ${vm.error}", color = MaterialTheme.colorScheme.error)
            vm.result != null -> QueryResultView(vm.result!!)
        }
    }
}

@Composable
private fun QueryResultView(result: QueryResult) {
    when (result.status) {
        QueryResultStatus.CONFIRMED -> {
            Card(
                Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer),
            ) {
                Column(Modifier.padding(16.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Default.CheckCircle, null, tint = MaterialTheme.colorScheme.primary)
                        Spacer(Modifier.width(8.dp))
                        Text("确定答案", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onPrimaryContainer)
                    }
                    Spacer(Modifier.height(8.dp))
                    Text(result.answer ?: "", style = MaterialTheme.typography.bodyLarge)
                }
            }
        }
        QueryResultStatus.POSSIBLE -> {
            Card(
                Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.secondaryContainer),
            ) {
                Column(Modifier.padding(16.dp)) {
                    Text("没有找到确定答案，但找到可能相关证据", style = MaterialTheme.typography.bodyMedium)
                    result.uncertaintyReason?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                }
            }
        }
        QueryResultStatus.NOT_FOUND -> {
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp)) {
                    Text("没有找到相关信息", style = MaterialTheme.typography.bodyLarge)
                }
            }
        }
    }

    if (result.evidences.isNotEmpty()) {
        Spacer(Modifier.height(12.dp))
        Text("证据", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
        LazyColumn {
            items(result.evidences) { ev ->
                Card(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
                    Row(Modifier.padding(12.dp), verticalAlignment = Alignment.Top) {
                        Icon(
                            evidenceIcon(ev.type), null,
                            tint = MaterialTheme.colorScheme.primary,
                            modifier = Modifier.size(20.dp),
                        )
                        Spacer(Modifier.width(10.dp))
                        Column {
                            Text(ev.content, style = MaterialTheme.typography.bodySmall)
                            Text("置信: ${ev.confidence.name}", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                }
            }
        }
    }
}
