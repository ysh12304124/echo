package com.echo.phone.ui.capture

import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Stop
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
import com.echo.phone.data.RecordingController
import com.echo.phone.data.glasses.GlassesConnection
import com.echo.phone.domain.*
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch

/**
 * 采集页 ViewModel：使用 [RecordingController] 边采边传。
 * 支持时间记忆与空间采集并行（双录制），各自对应独立后台 session。
 */
class CaptureViewModel(
    private val repo: EchoRepository,
    private val glasses: GlassesConnection,
) : ViewModel() {
    private val timeController = RecordingController(repo, glasses, viewModelScope)
    private val spaceController = RecordingController(repo, glasses, viewModelScope)

    var selectedScene by mutableStateOf(TimeScene.MEETING)
    var isRecording by mutableStateOf(false)
    var isPaused by mutableStateOf(false)
    var isSpaceRecording by mutableStateOf(false)
    var statusMessage by mutableStateOf("")
    var uploading by mutableStateOf(false)

    val deviceStatus = glasses.deviceStatus.stateIn(
        viewModelScope, SharingStarted.WhileSubscribed(5000), DeviceStatus(false),
    )

    init {
        // 眼镜物理按键驱动录制：单击=开始/结束切换，双击=标记关键时刻，长按=结束。
        viewModelScope.launch {
            glasses.keyEvents.collect { action ->
                when (action) {
                    GlassKeyAction.CLICK -> if (!isRecording) startTimeRecording() else stopAndUpload()
                    GlassKeyAction.DOUBLE_CLICK -> if (isRecording) markMoment()
                    GlassKeyAction.LONG_PRESS -> if (isRecording) stopAndUpload()
                    else -> {}
                }
            }
        }
    }

    private fun currentPartition() =
        if (selectedScene == TimeScene.QUALITY_TIME) DataPartition.QUALITY_TIME else DataPartition.WORK

    fun startTimeRecording() {
        viewModelScope.launch {
            try {
                timeController.startTime(selectedScene, currentPartition(), "${selectedScene.name} 记录")
                isRecording = true
                isPaused = false
                statusMessage = "时间记忆录制中，正在边采边传..."
            } catch (e: Exception) {
                statusMessage = "无法开始录制: ${e.message}"
            }
        }
    }

    fun startSpaceRecording() {
        viewModelScope.launch {
            try {
                // 空间采集与工作分区一致，Quality Time 场景不做空间建模
                spaceController.startSpace(DataPartition.WORK, "空间采集")
                isSpaceRecording = true
                statusMessage = "空间采集中..."
            } catch (e: Exception) {
                statusMessage = "无法开始空间采集: ${e.message}"
            }
        }
    }

    fun pause() {
        viewModelScope.launch {
            timeController.pause()
            isPaused = true
        }
    }

    fun resume() {
        viewModelScope.launch {
            timeController.resume()
            isPaused = false
        }
    }

    fun stopAndUpload() {
        viewModelScope.launch {
            uploading = true
            try {
                timeController.stopAndComplete()
                isRecording = false
                if (isSpaceRecording) {
                    spaceController.stopAndComplete()
                    isSpaceRecording = false
                }
                statusMessage = "上传完成，后台处理中..."
            } catch (e: Exception) {
                statusMessage = "结束/上传失败: ${e.message}"
            }
            uploading = false
        }
    }

    fun markMoment() {
        viewModelScope.launch { timeController.markKeyMoment() }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CaptureScreen(onBack: () -> Unit) {
    val context = LocalContext.current
    val app = context.applicationContext as EchoApplication
    val vm: CaptureViewModel = viewModel(
        factory = object : androidx.lifecycle.ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : ViewModel> create(cls: Class<T>): T =
                CaptureViewModel(app.repository, app.glassesConnection) as T
        }
    )
    val deviceStatus by vm.deviceStatus.collectAsState()

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("开始记录") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, "返回")
                    }
                },
            )
        },
    ) { padding ->
        Column(
            Modifier.fillMaxSize().padding(padding).padding(16.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text("选择场景", style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                TimeScene.entries.forEach { scene ->
                    FilterChip(
                        selected = vm.selectedScene == scene,
                        onClick = { if (!vm.isRecording) vm.selectedScene = scene },
                        label = { Text(scene.name) },
                        enabled = !vm.isRecording,
                    )
                }
            }

            Spacer(Modifier.height(24.dp))

            if (deviceStatus.isRecordingTime || deviceStatus.isRecordingSpace) {
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp)) {
                        if (deviceStatus.isRecordingTime) Text("时间录制中", color = MaterialTheme.colorScheme.primary)
                        if (deviceStatus.isRecordingSpace) Text("空间采集中", color = MaterialTheme.colorScheme.tertiary)
                    }
                }
            }

            Spacer(Modifier.height(24.dp))

            if (!vm.isRecording) {
                Button(onClick = { vm.startTimeRecording() }, modifier = Modifier.fillMaxWidth()) {
                    Icon(Icons.Default.PlayArrow, null)
                    Spacer(Modifier.width(8.dp))
                    Text("开始时间记忆")
                }
                Spacer(Modifier.height(8.dp))
                OutlinedButton(onClick = { vm.startSpaceRecording() }, modifier = Modifier.fillMaxWidth()) {
                    Text("同时开始空间采集")
                }
            } else {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    if (vm.isPaused) {
                        Button(onClick = { vm.resume() }) { Icon(Icons.Default.PlayArrow, null) }
                    } else {
                        Button(onClick = { vm.pause() }) { Icon(Icons.Default.Pause, null) }
                    }
                    Button(onClick = { vm.markMoment() }) { Text("标记") }
                    Button(
                        onClick = { vm.stopAndUpload() },
                        colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error),
                        enabled = !vm.uploading,
                    ) {
                        Icon(Icons.Default.Stop, null)
                        Spacer(Modifier.width(4.dp))
                        Text("结束")
                    }
                }
            }

            if (vm.uploading) {
                Spacer(Modifier.height(16.dp))
                CircularProgressIndicator()
            }
            if (vm.statusMessage.isNotEmpty()) {
                Spacer(Modifier.height(8.dp))
                Text(vm.statusMessage)
            }
        }
    }
}
