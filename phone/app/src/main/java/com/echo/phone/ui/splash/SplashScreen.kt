package com.echo.phone.ui.splash

import androidx.compose.animation.core.*
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay

@Composable
fun SplashScreen(onDone: () -> Unit) {
    val infinite = rememberInfiniteTransition(label = "splash")
    val rotation by infinite.animateFloat(0f, 360f, infiniteRepeatable(tween(3000, easing = LinearEasing)), label = "rotate")
    val alpha by infinite.animateFloat(0.3f, 0.7f, infiniteRepeatable(tween(1500, easing = EaseInOutCubic), RepeatMode.Reverse), label = "fade")

    LaunchedEffect(Unit) { delay(1000); onDone() }

    Box(Modifier.fillMaxSize().background(Color.White), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            // Geometric logo — 3 overlapping diamonds
            Canvas(Modifier.size(80.dp)) {
                val cx = size.width / 2; val cy = size.height / 2
                val r = size.width * 0.4f
                val colors = listOf(
                    Color(0xFF3B82F6).copy(alpha = alpha),
                    Color(0xFF10B981).copy(alpha = alpha * 0.8f),
                    Color(0xFF8B5CF6).copy(alpha = alpha * 0.6f),
                )
                colors.forEachIndexed { i, c ->
                    rotate(rotation + i * 30f, pivot = Offset(cx, cy)) {
                        drawRect(c, topLeft = Offset(cx - r, cy - r * 0.6f), size = Size(r * 2, r * 1.2f))
                    }
                }
            }
            Spacer(Modifier.height(20.dp))
            Text("识境", fontSize = 28.sp, fontWeight = FontWeight.Bold, color = Color(0xFF111827))
            Spacer(Modifier.height(4.dp))
            Text("ShiJing · 随身 AI 智能秘书", fontSize = 12.sp, color = Color(0xFF9CA3AF))
        }
    }
}
