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
import com.echo.phone.domain.*
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

class QueryViewModel(private val repo: com.echo.phone.data.EchoRepository) : ViewModel() {
    var question by mutableStateOf("")
    var scope by mutableStateOf(QueryScope.GLOBAL_WORK)
    var result by mutableStateOf<QueryResult?>(null)
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)

    fun submit() {
        if (question.isBlank()) return
        viewModelScope.launch {
            loading = true; error = null
            try { result = repo.query(question, scope, null, null) }
            catch (e: Exception) { error = e.message }
            loading = false
        }
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

        OutlinedTextField(
            value = vm.question,
            onValueChange = { vm.question = it },
            modifier = Modifier.fillMaxWidth().shadow(if (vm.question.isNotEmpty()) 2.dp else 0.dp, RoundedCornerShape(10.dp)),
            placeholder = { Text("例如：张经理承诺了什么？") },
            leadingIcon = { Icon(Icons.Default.Search, null) },
            trailingIcon = { if (vm.question.isNotBlank()) IconButton(onClick = { vm.submit() }, enabled = !vm.loading) { Icon(Icons.Default.Send, "查询") } },
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
                "error" -> Box(Modifier.fillMaxWidth().shadow(4.dp, RoundedCornerShape(18.dp)).clip(RoundedCornerShape(18.dp)).background(GlassBg).border(1.dp, GlassBorder, RoundedCornerShape(18.dp)).padding(18.dp)) {
                    Text("查询失败: ${vm.error}", color = MaterialTheme.colorScheme.error)
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
