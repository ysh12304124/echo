package com.echo.phone.ui.onboarding

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.echo.phone.data.PermissionManager

/**
 * 首次引导：介绍眼镜/记忆类型/场景/手动开启/LED/查询范围，并申请必要权限。
 */
@Composable
fun OnboardingScreen(onDone: () -> Unit) {
    val context = LocalContext.current
    var granted by remember { mutableStateOf(PermissionManager.allGranted(context)) }

    val launcher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { result ->
        granted = result.values.all { it } || PermissionManager.allGranted(context)
    }

    Column(
        Modifier.fillMaxSize().padding(24.dp).verticalScroll(rememberScrollState()),
    ) {
        Text("欢迎使用识境 Echo", style = MaterialTheme.typography.headlineMedium)
        Spacer(Modifier.height(16.dp))

        GuideItem("眼镜", "戴上 Rokid 眼镜并与手机配对，Echo 作为眼镜端应用运行。")
        GuideItem("记忆类型", "时间记忆记录“发生了什么”，空间记忆重建“在哪里”。")
        GuideItem("场景", "会议 / 现场拜访 / 陪伴时光，不同场景触发不同关键瞬间。")
        GuideItem("手动开启", "记录始终由你手动开启与结束，绝不自动录制。")
        GuideItem("LED 指示", "白灯待机、蓝灯录制中、呼吸灯上传/处理、红灯异常。")
        GuideItem("查询范围", "全局工作、指定记忆、指定空间；Quality Time 独立隔离。")

        Spacer(Modifier.height(24.dp))

        if (!granted) {
            Text("为连接眼镜与采集，需要相机、麦克风、蓝牙权限。", style = MaterialTheme.typography.bodyMedium)
            Spacer(Modifier.height(8.dp))
            Button(
                onClick = { launcher.launch(PermissionManager.requiredPermissions()) },
                modifier = Modifier.fillMaxWidth(),
            ) { Text("授予权限") }
        } else {
            Button(onClick = onDone, modifier = Modifier.fillMaxWidth()) { Text("开始使用") }
        }
    }
}

@Composable
private fun GuideItem(title: String, desc: String) {
    Card(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
        Column(Modifier.padding(16.dp)) {
            Text(title, style = MaterialTheme.typography.titleSmall)
            Text(desc, style = MaterialTheme.typography.bodySmall)
        }
    }
}
