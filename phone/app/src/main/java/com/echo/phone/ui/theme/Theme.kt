package com.echo.phone.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

// ── Light palette: white surfaces + blue accents ──
private val White = Color(0xFFFFFFFF)
private val PrimaryBlue = Color(0xFF2563EB)

private val EchoLightScheme = lightColorScheme(
    primary = PrimaryBlue, onPrimary = White,
    primaryContainer = Color(0xFFDBEAFE), onPrimaryContainer = Color(0xFF1E3A5F),
    secondary = Color(0xFF0D9488), onSecondary = White,
    secondaryContainer = Color(0xFFCCFBF1), onSecondaryContainer = Color(0xFF134E4A),
    surface = White, onSurface = Color(0xFF111827),
    surfaceVariant = Color(0xFFF8F9FC), onSurfaceVariant = Color(0xFF6B7280),
    surfaceContainer = Color(0xFFF0F2F8), surfaceContainerHigh = Color(0xFFEBEDF3),
    outline = Color(0xFFE5E7EB), outlineVariant = Color(0xFFE5E7EB),
    error = Color(0xFFDC2626), onError = White,
)

private val EchoDarkScheme = darkColorScheme(
    primary = Color(0xFF60A5FA), onPrimary = Color(0xFF0A1628),
    primaryContainer = Color(0xFF1E3A5F), onPrimaryContainer = Color(0xFFD6E4FF),
    secondary = Color(0xFF22D3EE), onSecondary = Color(0xFF002020),
    surface = Color(0xFF080B12), onSurface = Color(0xFFF1F5F9),
    surfaceVariant = Color(0xFF111827), onSurfaceVariant = Color(0xFF94A3B8),
    surfaceContainer = Color(0xFF1A2235), surfaceContainerHigh = Color(0xFF1F2A3D),
    outline = Color(0xFF334155), outlineVariant = Color(0xFF1E293B),
    error = Color(0xFFFF6B6B), onError = Color(0xFF2A0709),
)

private val EchoShapes = Shapes(
    extraSmall = RoundedCornerShape(6.dp), small = RoundedCornerShape(10.dp),
    medium = RoundedCornerShape(18.dp), large = RoundedCornerShape(24.dp), extraLarge = RoundedCornerShape(32.dp),
)

private val EchoTypography = Typography().run {
    val f = FontFamily.Default
    copy(
        headlineMedium = headlineMedium.copy(fontFamily = f, fontWeight = FontWeight.SemiBold, letterSpacing = 0.3.sp),
        titleLarge = titleLarge.copy(fontFamily = f, fontWeight = FontWeight.SemiBold),
        titleMedium = titleMedium.copy(fontFamily = f, fontWeight = FontWeight.Medium),
        titleSmall = titleSmall.copy(fontFamily = f, fontWeight = FontWeight.Bold),
        bodyLarge = bodyLarge.copy(fontFamily = f, letterSpacing = 0.2.sp),
        bodyMedium = bodyMedium.copy(fontFamily = f, letterSpacing = 0.1.sp),
        bodySmall = bodySmall.copy(fontFamily = f, letterSpacing = 0.1.sp),
        labelMedium = labelMedium.copy(fontFamily = f, fontWeight = FontWeight.Medium, letterSpacing = 0.8.sp),
    )
}

@Composable
fun EchoTheme(darkTheme: Boolean = false, content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = if (darkTheme) EchoDarkScheme else EchoLightScheme,
        typography = EchoTypography,
        shapes = EchoShapes,
        content = content,
    )
}
