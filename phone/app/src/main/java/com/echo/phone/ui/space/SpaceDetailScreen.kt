package com.echo.phone.ui.space

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.FavoriteBorder
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.echo.phone.EchoApplication
import com.echo.phone.data.EchoRepository
import com.echo.phone.domain.*
import com.echo.phone.ui.common.PointCloudViewer
import kotlinx.coroutines.launch

class SpaceDetailViewModel(
    private val repo: EchoRepository,
    private val spaceId: String,
) : ViewModel() {
    var space by mutableStateOf<SpaceMemoryDetail?>(null)
    var modelAbsoluteUrl by mutableStateOf<String?>(null)
    var queryQuestion by mutableStateOf("")
    var queryResult by mutableStateOf<QueryResult?>(null)
    var loading by mutableStateOf(true)
    var isFavorited by mutableStateOf(false)
    var deleted by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)

    init { load() }

    fun load() {
        viewModelScope.launch {
            loading = true
            try {
                val s = repo.getSpace(spaceId)
                space = s
                isFavorited = s.isFavorited
                modelAbsoluteUrl = repo.absoluteMediaUrl(s.modelUrl)
            } catch (e: Exception) {
                error = e.message
            }
            loading = false
        }
    }

    fun toggleFavorite() {
        viewModelScope.launch {
            try {
                isFavorited = !isFavorited
                repo.toggleSpaceFavorite(spaceId, isFavorited)
            } catch (e: Exception) {
                error = e.message
            }
        }
    }

    fun delete(onDone: () -> Unit) {
        viewModelScope.launch {
            try {
                repo.deleteSpace(spaceId)
                deleted = true
                onDone()
            } catch (e: Exception) {
                error = "删除失败: ${e.message}"
            }
        }
    }

    fun queryInSpace() {
        if (queryQuestion.isBlank()) return
        viewModelScope.launch {
            try {
                queryResult = repo.query(queryQuestion, QueryScope.SPACE, spaceId = spaceId)
            } catch (e: Exception) {
                error = e.message
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SpaceDetailScreen(spaceId: String, onBack: () -> Unit) {
    val context = LocalContext.current
    val app = context.applicationContext as EchoApplication
    val vm: SpaceDetailViewModel = viewModel(
        factory = object : androidx.lifecycle.ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : ViewModel> create(cls: Class<T>): T =
                SpaceDetailViewModel(app.repository, spaceId) as T
        }
    )
    var showDeleteDialog by remember { mutableStateOf(false) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(vm.space?.title ?: "空间详情") },
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
                    IconButton(onClick = { showDeleteDialog = true }) {
                        Icon(Icons.Default.Delete, "删除")
                    }
                },
            )
        },
    ) { padding ->
        if (vm.loading) {
            Box(Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
            return@Scaffold
        }

        Column(
            Modifier.fillMaxSize().padding(padding).padding(16.dp)
                .verticalScroll(rememberScrollState()),
        ) {
            vm.space?.let { space ->
                val qualityLabel = when (space.quality) {
                    "excellent" -> "质量：优秀"
                    "good" -> "质量：良好"
                    "retry_required" -> "质量：建议重拍"
                    else -> "质量：未知"
                }
                Text(qualityLabel, style = MaterialTheme.typography.labelLarge)
                Text(space.identifyBrief, style = MaterialTheme.typography.bodyLarge)

                Spacer(Modifier.height(16.dp))

                Text("3D 空间模型", style = MaterialTheme.typography.titleMedium)
                
                Card(Modifier.fillMaxWidth().height(360.dp)) {
                    PointCloudViewer(vm.modelAbsoluteUrl, Modifier.fillMaxSize())
                }

                Spacer(Modifier.height(16.dp))

                if (space.anchors.isNotEmpty()) {
                    Text("空间锚点", style = MaterialTheme.typography.titleMedium)
                    space.anchors.forEach { a ->
                        ListItem(
                            headlineContent = { Text(a.name) },
                            supportingContent = { Text(a.anchorType) },
                        )
                    }
                    Spacer(Modifier.height(16.dp))
                }

                Text("当前空间内查询", style = MaterialTheme.typography.titleMedium)
                OutlinedTextField(
                    value = vm.queryQuestion,
                    onValueChange = { vm.queryQuestion = it },
                    modifier = Modifier.fillMaxWidth(),
                    placeholder = { Text("这个区域有什么设备？") },
                )
                Button(onClick = { vm.queryInSpace() }, modifier = Modifier.padding(top = 8.dp)) {
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
                }
                vm.error?.let {
                    Spacer(Modifier.height(8.dp))
                    Text(it, color = MaterialTheme.colorScheme.error)
                }
            }
        }
    }

    if (showDeleteDialog) {
        AlertDialog(
            onDismissRequest = { showDeleteDialog = false },
            title = { Text("删除空间记忆") },
            text = { Text("删除后无法恢复，包含模型与关联证据。确定删除？") },
            confirmButton = {
                TextButton(onClick = {
                    showDeleteDialog = false
                    vm.delete(onBack)
                }) { Text("删除") }
            },
            dismissButton = {
                TextButton(onClick = { showDeleteDialog = false }) { Text("取消") }
            },
        )
    }
}
