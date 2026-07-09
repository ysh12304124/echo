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

// ── Dark tech palette (only dark — more immersive) ──
private val DeepBackground = Color(0xFF080B12)
private val SurfaceBg = Color(0xFF111827)
private val CardBg = Color(0xFF1A2235)
private val CardBgLighter = Color(0xFF1F2A3D)
private val PrimaryBlue = Color(0xFF60A5FA)
private val AccentCyan = Color(0xFF22D3EE)
private val AccentGreen = Color(0xFF34D399)
private val AccentPurple = Color(0xFFA78BFA)
private val TextPrimary = Color(0xFFF1F5F9)
private val TextSecondary = Color(0xFF94A3B8)
private val BorderSubtle = Color(0xFF334155)
private val BorderGlass = Color(0x20FFFFFF)

private val EchoDarkScheme = darkColorScheme(
    primary = PrimaryBlue,
    onPrimary = Color(0xFF0A1628),
    primaryContainer = Color(0xFF1E3A5F),
    onPrimaryContainer = Color(0xFFD6E4FF),
    secondary = AccentCyan,
    onSecondary = Color(0xFF002020),
    secondaryContainer = Color(0xFF003737),
    onSecondaryContainer = Color(0xFFB8F5F5),
    tertiary = AccentPurple,
    onTertiary = Color(0xFF1B103E),
    tertiaryContainer = Color(0xFF2E2360),
    onTertiaryContainer = Color(0xFFE4DCFF),
    surface = DeepBackground,
    onSurface = TextPrimary,
    surfaceVariant = SurfaceBg,
    onSurfaceVariant = TextSecondary,
    surfaceContainer = CardBg,
    surfaceContainerHigh = CardBgLighter,
    outline = BorderSubtle,
    outlineVariant = Color(0xFF1E293B),
    error = Color(0xFFFF6B6B),
    onError = Color(0xFF2A0709),
)

// ── Shapes — more generous rounding ──
private val EchoShapes = Shapes(
    extraSmall = RoundedCornerShape(6.dp),
    small = RoundedCornerShape(10.dp),
    medium = RoundedCornerShape(18.dp),
    large = RoundedCornerShape(24.dp),
    extraLarge = RoundedCornerShape(32.dp),
)

// ── Typography — refined hierarchy ──
private val EchoTypography = Typography().run {
    val f = FontFamily.Default
    copy(
        displayLarge = displayLarge.copy(fontFamily = f, fontWeight = FontWeight.Bold, color = TextPrimary),
        headlineLarge = headlineLarge.copy(fontFamily = f, fontWeight = FontWeight.Bold),
        headlineMedium = headlineMedium.copy(fontFamily = f, fontWeight = FontWeight.SemiBold, letterSpacing = 0.3.sp),
        titleLarge = titleLarge.copy(fontFamily = f, fontWeight = FontWeight.SemiBold),
        titleMedium = titleMedium.copy(fontFamily = f, fontWeight = FontWeight.Medium, letterSpacing = 0.2.sp),
        titleSmall = titleSmall.copy(fontFamily = f, fontWeight = FontWeight.Bold, letterSpacing = 0.1.sp),
        bodyLarge = bodyLarge.copy(fontFamily = f, letterSpacing = 0.2.sp),
        bodyMedium = bodyMedium.copy(fontFamily = f, letterSpacing = 0.15.sp),
        bodySmall = bodySmall.copy(fontFamily = f, letterSpacing = 0.12.sp),
        labelLarge = labelLarge.copy(fontFamily = f, fontWeight = FontWeight.Medium, letterSpacing = 0.8.sp),
        labelMedium = labelMedium.copy(fontFamily = f, fontWeight = FontWeight.Medium, letterSpacing = 1.0.sp),
        labelSmall = labelSmall.copy(fontFamily = f, letterSpacing = 0.8.sp),
    )
}

object EchoTheme {
    val cardBorder = BorderGlass
}

@Composable
fun EchoTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    MaterialTheme(
        colorScheme = EchoDarkScheme,
        typography = EchoTypography,
        shapes = EchoShapes,
        content = content,
    )
}
