package com.echo.phone.ui.query

import androidx.compose.animation.*
import androidx.compose.animation.core.*
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
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

private val GlassBg = Brush.verticalGradient(
    listOf(Color.White.copy(alpha = 0.08f), Color.White.copy(alpha = 0.04f))
)
private val GlassBorder = Color.White.copy(alpha = 0.10f)

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

    Column(Modifier.fillMaxSize().padding(horizontal = 20.dp).padding(top = 20.dp)) {
        Text("查询", style = MaterialTheme.typography.headlineMedium, color = MaterialTheme.colorScheme.onSurface)
        Spacer(Modifier.height(14.dp))

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            QueryScope.entries.forEach { s ->
                FilterChip(
                    selected = vm.scope == s,
                    onClick = { vm.scope = s },
                    label = { Text(when(s) { QueryScope.GLOBAL_WORK -> "全局工作"; QueryScope.MEMORY -> "当前记忆"; QueryScope.SPACE -> "当前空间" }) },
                )
            }
        }
        Spacer(Modifier.height(14.dp))

        OutlinedTextField(
            value = vm.question,
            onValueChange = { vm.question = it },
            modifier = Modifier.fillMaxWidth().shadow(if (vm.question.isNotEmpty()) 4.dp else 0.dp, RoundedCornerShape(10.dp)),
            placeholder = { Text("例如：张经理承诺了什么？") },
            leadingIcon = { Icon(Icons.Default.Search, null) },
            trailingIcon = {
                if (vm.question.isNotBlank()) IconButton(onClick = { vm.submit() }, enabled = !vm.loading) { Icon(Icons.Default.Send, "查询") }
            },
            singleLine = true,
            shape = MaterialTheme.shapes.small,
            colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = MaterialTheme.colorScheme.primary),
        )
        Spacer(Modifier.height(20.dp))

        AnimatedContent(
            targetState = when { vm.loading -> "loading"; vm.error != null -> "error"; vm.result != null -> "result"; else -> "idle" },
            transitionSpec = { fadeIn(tween(250)) + slideInVertically(tween(250)) { it / 4 } togetherWith fadeOut(tween(150)) },
            label = "result",
        ) { state ->
            when (state) {
                "loading" -> CircularProgressIndicator()
                "error" -> Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = Color.Transparent)) {
                    Box(Modifier.background(GlassBg).border(1.dp, GlassBorder, RoundedCornerShape(18.dp)).padding(16.dp)) {
                        Text("查询失败: ${vm.error}", color = MaterialTheme.colorScheme.error)
                    }
                }
                "result" -> QueryResultView(vm.result!!)
            }
        }
    }
}

@Composable
private fun QueryResultView(result: QueryResult) {
    when (result.status) {
        QueryResultStatus.CONFIRMED -> {
            Box(
                Modifier.fillMaxWidth().shadow(4.dp, RoundedCornerShape(18.dp)).clip(RoundedCornerShape(18.dp))
                    .background(GlassBg).border(1.dp, GlassBorder, RoundedCornerShape(18.dp)).padding(18.dp)
            ) {
                Column {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Default.CheckCircle, null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(20.dp))
                        Spacer(Modifier.width(8.dp))
                        Text("确定答案", style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.primary)
                    }
                    Spacer(Modifier.height(10.dp))
                    Text(result.answer ?: "", style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.onSurface)
                }
            }
        }
        QueryResultStatus.POSSIBLE -> {
            Box(
                Modifier.fillMaxWidth().shadow(4.dp, RoundedCornerShape(18.dp)).clip(RoundedCornerShape(18.dp))
                    .background(GlassBg).border(1.dp, GlassBorder, RoundedCornerShape(18.dp)).padding(18.dp)
            ) {
                Column {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Default.Warning, null, tint = Color(0xFFF59E0B), modifier = Modifier.size(20.dp))
                        Spacer(Modifier.width(8.dp))
                        Text("可能相关", style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.Bold, color = Color(0xFFF59E0B))
                    }
                    Spacer(Modifier.height(8.dp))
                    Text("没有找到确定答案，但找到可能相关证据", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurface)
                    result.uncertaintyReason?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                }
            }
        }
        QueryResultStatus.NOT_FOUND -> Box(
            Modifier.fillMaxWidth().shadow(4.dp, RoundedCornerShape(18.dp)).clip(RoundedCornerShape(18.dp))
                .background(GlassBg).border(1.dp, GlassBorder, RoundedCornerShape(18.dp)).padding(18.dp)
        ) {
            Text("没有找到相关信息", style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.onSurface)
        }
    }

    if (result.evidences.isNotEmpty()) {
        Spacer(Modifier.height(16.dp))
        Text("证据", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.onSurface)
        Spacer(Modifier.height(8.dp))
        LazyColumn { items(result.evidences) { ev ->
            Card(
                Modifier.fillMaxWidth().padding(vertical = 4.dp).shadow(2.dp, RoundedCornerShape(14.dp)),
                colors = CardDefaults.cardColors(containerColor = Color.Transparent),
            ) {
                Box(Modifier.background(GlassBg).border(1.dp, GlassBorder, RoundedCornerShape(14.dp)).padding(14.dp)) {
                    Row(verticalAlignment = Alignment.Top) {
                        Icon(evidenceIcon(ev.type), null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(10.dp))
                        Column {
                            Text(ev.content, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurface)
                            Text("置信: ${ev.confidence.name}", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                }
            }
        } }
    }
}
