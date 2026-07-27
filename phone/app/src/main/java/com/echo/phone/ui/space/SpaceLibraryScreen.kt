package com.echo.phone.ui.space

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.echo.phone.EchoApplication
import com.echo.phone.data.EchoRepository
import com.echo.phone.domain.DataPartition
import com.echo.phone.domain.SpaceMemoryDetail
import kotlinx.coroutines.launch

class SpaceLibraryViewModel(private val repo: EchoRepository) : ViewModel() {
    var spaces by mutableStateOf<List<SpaceMemoryDetail>>(emptyList())
    var loading by mutableStateOf(true)

    init {
        viewModelScope.launch {
            try { spaces = repo.listSpaces(DataPartition.WORK) } catch (_: Exception) {}
            loading = false
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SpaceLibraryScreen(onBack: () -> Unit, onOpenSpace: (String) -> Unit) {
    val context = LocalContext.current
    val app = context.applicationContext as EchoApplication
    val vm: SpaceLibraryViewModel = viewModel(
        factory = object : androidx.lifecycle.ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : ViewModel> create(cls: Class<T>): T = SpaceLibraryViewModel(app.repository) as T
        }
    )

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("空间库") },
                navigationIcon = {
                    IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "返回") }
                },
            )
        },
    ) { padding ->
        when {
            vm.loading -> Box(Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
            vm.spaces.isEmpty() -> Box(Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.Center) {
                Text("暂无空间记忆")
            }
            else -> LazyColumn(Modifier.fillMaxSize().padding(padding).padding(16.dp)) {
                items(vm.spaces) { space ->
                    Card(
                        Modifier.fillMaxWidth().padding(vertical = 4.dp)
                            .clickable { onOpenSpace(space.spaceId) },
                    ) {
                        Column(Modifier.padding(16.dp)) {
                            Text(
                                space.sceneSummary.ifBlank { space.title.ifBlank { space.identifyBrief } },
                                style = MaterialTheme.typography.titleSmall,
                            )
                            Text("质量: ${space.quality ?: "未知"}", style = MaterialTheme.typography.labelSmall)
                        }
                    }
                }
            }
        }
    }
}
