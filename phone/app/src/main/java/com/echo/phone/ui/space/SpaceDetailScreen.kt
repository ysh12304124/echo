package com.echo.phone.ui.space

import androidx.compose.foundation.background
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
import com.echo.phone.ui.common.PathTraversal
import com.echo.phone.ui.common.PointCloudViewer
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlin.math.sqrt

class SpaceDetailViewModel(
    private val repo: EchoRepository,
    private val spaceId: String,
) : ViewModel() {
    var space by mutableStateOf<SpaceMemoryDetail?>(null)
    var modelAbsoluteUrl by mutableStateOf<String?>(null)
    var poses by mutableStateOf<List<CameraPose>>(emptyList())
    var orbitCircle by mutableStateOf<OrbitCircle?>(null)
    var baseSpeed by mutableStateOf(1f)
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
                if (s.status == MemoryStatus.PROCESSING) refreshUntilReady()
                if (s.posesUrl != null) loadPoses(s)
            } catch (e: Exception) {
                error = e.message
            }
            loading = false
        }
    }

    private suspend fun loadPoses(s: SpaceMemoryDetail) {
        try {
            val text = repo.downloadText(s.posesUrl!!)
            val lines = text.trim().split("\n").filter { it.isNotBlank() }
            val parsed = lines.map { line ->
                val v = line.trim().split("\\s+".toRegex()).map { it.toFloat() }
                val pos = floatArrayOf(v[3], v[7], v[11])
                val rot = floatArrayOf(
                    v[0], v[1], v[2],
                    v[4], v[5], v[6],
                    v[8], v[9], v[10],
                )
                val forward = floatArrayOf(-v[2], -v[6], -v[10])
                CameraPose(pos, rot, forward)
            }
            poses = parsed

            baseSpeed = PathTraversal.speedForTenSecondLoop(parsed)

            if (s.sceneType == "object") {
                orbitCircle = fitCircle3D(parsed)
            }
        } catch (e: Exception) {
            error = "位姿加载失败: ${e.message}"
        }
    }

    private fun fitCircle3D(poses: List<CameraPose>): OrbitCircle {
        val n = poses.size
        val cx = poses.map { it.position[0] }.average().toFloat()
        val cy = poses.map { it.position[1] }.average().toFloat()
        val cz = poses.map { it.position[2] }.average().toFloat()

        val pts = Array(n) { i ->
            doubleArrayOf(
                (poses[i].position[0] - cx).toDouble(),
                (poses[i].position[1] - cy).toDouble(),
                (poses[i].position[2] - cz).toDouble(),
            )
        }

        // SVD for plane normal
        val u = DoubleArray(n)
        val v = DoubleArray(n)
        val w = DoubleArray(n)
        val a = Array(n) { DoubleArray(3) }
        for (i in 0 until n) { a[i][0] = pts[i][0]; a[i][1] = pts[i][1]; a[i][2] = pts[i][2] }

        // Power iteration for largest singular value of A^T A
        var normal = doubleArrayOf(0.0, 1.0, 0.0)
        repeat(20) {
            val x = normal[0]; val y = normal[1]; val z = normal[2]
            var nx = 0.0; var ny = 0.0; var nz = 0.0
            for (i in 0 until n) {
                val dot = a[i][0] * x + a[i][1] * y + a[i][2] * z
                nx += a[i][0] * dot; ny += a[i][1] * dot; nz += a[i][2] * dot
            }
            val len = sqrt(nx * nx + ny * ny + nz * nz)
            if (len < 1e-10) return@repeat
            normal = doubleArrayOf(nx / len, ny / len, nz / len)
        }

        // Find two perpendicular vectors in the plane
        val ux: Double; val uy: Double; val uz: Double
        val vxx: Double; val vy: Double; val vz: Double
        if (kotlin.math.abs(normal[0]) < 0.9) {
            ux = normal[1]; uy = -normal[0]; uz = 0.0
        } else {
            ux = 0.0; uy = normal[2]; uz = -normal[1]
        }
        val ulen = sqrt(ux * ux + uy * uy + uz * uz)
        val uxn = ux / ulen; val uyn = uy / ulen; val uzn = uz / ulen
        vxx = uyn * normal[2] - uzn * normal[1]
        vy = uzn * normal[0] - uxn * normal[2]
        vz = uxn * normal[1] - uyn * normal[0]

        // Project points to 2D
        val x2d = DoubleArray(n); val y2d = DoubleArray(n)
        for (i in 0 until n) {
            x2d[i] = a[i][0] * uxn + a[i][1] * uyn + a[i][2] * uzn
            y2d[i] = a[i][0] * vxx + a[i][1] * vy + a[i][2] * vz
        }

        // Kasa circle fit: minimize Σ[(xi² + yi² - B*xi - C*yi - D)]²
        // Solve: [Σxi²  Σxiyi  Σxi] [B]   [Σxi(xi²+yi²)]
        //        [Σxiyi Σyi²   Σyi] [C] = [Σyi(xi²+yi²)]
        //        [Σxi   Σyi    n  ] [D]   [Σ(xi²+yi²)   ]
        var sxx = 0.0; var sxy = 0.0; var sx = 0.0
        var syy = 0.0; var sy = 0.0
        var sxz = 0.0; var syz = 0.0; var sz = 0.0
        for (i in 0 until n) {
            val xi = x2d[i]; val yi = y2d[i]
            val zi = xi * xi + yi * yi
            sxx += xi * xi; sxy += xi * yi; sx += xi
            syy += yi * yi; sy += yi
            sxz += xi * zi; syz += yi * zi; sz += zi
        }

        // Cramer's rule for 3x3
        val det = sxx * (syy * n - sy * sy) - sxy * (sxy * n - sx * sy) + sx * (sxy * sy - syy * sx)
        if (kotlin.math.abs(det) < 1e-12) {
            return OrbitCircle(floatArrayOf(cx, cy, cz), 1f, floatArrayOf(normal[0].toFloat(), normal[1].toFloat(), normal[2].toFloat()))
        }
        val b = (sxz * (syy * n - sy * sy) - sxy * (syz * n - sy * sz) + sx * (syz * sy - syy * sz)) / det
        val c = (sxx * (syz * n - sy * sz) - sxz * (sxy * n - sx * sy) + sx * (sxy * sz - syz * sx)) / det
        val d = (sxx * (syy * sz - sy * syz) - sxy * (sxy * sz - sx * syz) + sxz * (sxy * sy - syy * sx)) / det

        val r2d = sqrt(b * b / 4 + c * c / 4 + d)
        val c2dx = b / 2; val c2dy = c / 2

        val center3d = floatArrayOf(
            (cx + c2dx * uxn + c2dy * vxx).toFloat(),
            (cy + c2dx * uyn + c2dy * vy).toFloat(),
            (cz + c2dx * uzn + c2dy * vz).toFloat(),
        )

        return OrbitCircle(
            center3d,
            r2d.toFloat(),
            floatArrayOf(normal[0].toFloat(), normal[1].toFloat(), normal[2].toFloat()),
        )
    }

    private fun refreshUntilReady() {
        viewModelScope.launch {
            repeat(60) {
                delay(5000)
                try {
                    val current = repo.getSpace(spaceId)
                    space = current
                    modelAbsoluteUrl = repo.absoluteMediaUrl(current.modelUrl)
                    if (current.status != MemoryStatus.PROCESSING) {
                        if (current.posesUrl != null) loadPoses(current)
                        return@launch
                    }
                } catch (e: Exception) {
                    error = e.message
                    return@launch
                }
            }
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

                when {
                    space.status == MemoryStatus.PROCESSING -> {
                        Card(Modifier.fillMaxWidth().height(180.dp)) {
                            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                    CircularProgressIndicator()
                                    Spacer(Modifier.height(12.dp))
                                    Text("正在进行 3DGS 重建，请稍候")
                                }
                            }
                        }
                    }
                    space.status == MemoryStatus.FAILED -> {
                        Card(Modifier.fillMaxWidth().height(180.dp)) {
                            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                                Text("3DGS 重建失败，请重新录制", color = MaterialTheme.colorScheme.error)
                            }
                        }
                    }
                    space.status == MemoryStatus.COMPLETED && vm.modelAbsoluteUrl != null -> {
                        Card(Modifier.fillMaxWidth().height(360.dp)) {
                            PointCloudViewer(
                                pointCloudUrl = vm.modelAbsoluteUrl,
                                poses = vm.poses,
                                orbitCircle = vm.orbitCircle,
                                baseSpeed = vm.baseSpeed,
                                sceneType = space.sceneType ?: "large",
                                modifier = Modifier.fillMaxSize(),
                            )
                        }
                    }
                    else -> {
                        Card(Modifier.fillMaxWidth().height(180.dp)) {
                            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                                Text("暂无可用的 3D 模型")
                            }
                        }
                    }
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
                    app.notifyMemoryDeleted(spaceId); vm.delete(onBack)
                }) { Text("删除") }
            },
            dismissButton = {
                TextButton(onClick = { showDeleteDialog = false }) { Text("取消") }
            },
        )
    }
}
