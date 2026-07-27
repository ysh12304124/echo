package com.echo.phone.ui.mine

import android.content.Context
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

private const val PREFS_NAME = "echo_settings"
private const val KEY_BACKEND = "selected_backend"

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DevOptionsScreen(onBack: () -> Unit) {
    val context = LocalContext.current
    val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
    var selectedBackend by remember { mutableStateOf(prefs.getString(KEY_BACKEND, "153") ?: "153") }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("开发者选项") },
                navigationIcon = {
                    IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "返回") }
                },
            )
        }
    ) { padding ->
        Column(
            Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(20.dp)
        ) {
            Text("后端地址", style = MaterialTheme.typography.labelLarge, color = Color(0xFF6B7280))
            Spacer(Modifier.height(8.dp))
            BackendRadio(
                label = "153 后端 (psh)",
                url = "http://192.168.0.153:8001/api/v1/",
                selected = selectedBackend == "153",
                onClick = { selectBackend(context, "153"); selectedBackend = "153" }
            )
            Spacer(Modifier.height(8.dp))
            BackendRadio(
                label = "200 后端 (本机)",
                url = "http://192.168.0.200:8081/api/v1/",
                selected = selectedBackend == "200",
                onClick = { selectBackend(context, "200"); selectedBackend = "200" }
            )
            Spacer(Modifier.height(24.dp))
            Card(colors = CardDefaults.cardColors(containerColor = Color(0xFFFFF3CD))) {
                Text(
                    "⚠ 切换后端后请重启 App 生效",
                    modifier = Modifier.padding(16.dp),
                    color = Color(0xFF856404),
                    style = MaterialTheme.typography.bodyMedium
                )
            }
        }
    }
}

@Composable
private fun BackendRadio(label: String, url: String, selected: Boolean, onClick: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = if (selected) Color(0xFFE3F2FD) else MaterialTheme.colorScheme.surface
        ),
        onClick = onClick
    ) {
        Row(
            modifier = Modifier.padding(16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            RadioButton(selected = selected, onClick = null)
            Spacer(Modifier.width(12.dp))
            Column {
                Text(label, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.Medium)
                Text(url, style = MaterialTheme.typography.bodySmall, color = Color(0xFF6B7280))
            }
        }
    }
}

private fun selectBackend(context: Context, backend: String) {
    context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        .edit().putString(KEY_BACKEND, backend).apply()
}