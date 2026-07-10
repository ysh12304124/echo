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
private val SurfaceWhite = Color(0xFFF8F9FC)
private val CardWhite = Color(0xFFF0F2F8)
private val PrimaryBlue = Color(0xFF2563EB)
private val AccentTeal = Color(0xFF0D9488)
private val AccentAmber = Color(0xFFD97706)
private val TextMain = Color(0xFF111827)
private val TextSub = Color(0xFF6B7280)
private val BorderSub = Color(0xFFE5E7EB)
private val ShadowColor = Color(0x1A000000)

private val EchoLightScheme = lightColorScheme(
    primary = PrimaryBlue,
    onPrimary = White,
    primaryContainer = Color(0xFFDBEAFE),
    onPrimaryContainer = Color(0xFF1E3A5F),
    secondary = AccentTeal,
    onSecondary = White,
    secondaryContainer = Color(0xFFCCFBF1),
    onSecondaryContainer = Color(0xFF134E4A),
    tertiary = AccentAmber,
    onTertiary = White,
    tertiaryContainer = Color(0xFFFEF3C7),
    onTertiaryContainer = Color(0xFF78350F),
    surface = White,
    onSurface = TextMain,
    surfaceVariant = SurfaceWhite,
    onSurfaceVariant = TextSub,
    surfaceContainer = CardWhite,
    surfaceContainerHigh = Color(0xFFEBEDF3),
    outline = BorderSub,
    outlineVariant = Color(0xFFE5E7EB),
    error = Color(0xFFDC2626),
    onError = White,
)

private val EchoShapes = Shapes(
    extraSmall = RoundedCornerShape(6.dp),
    small = RoundedCornerShape(10.dp),
    medium = RoundedCornerShape(18.dp),
    large = RoundedCornerShape(24.dp),
    extraLarge = RoundedCornerShape(32.dp),
)

private val EchoTypography = Typography().run {
    val f = FontFamily.Default
    copy(
        headlineLarge = headlineLarge.copy(fontFamily = f, fontWeight = FontWeight.Bold),
        headlineMedium = headlineMedium.copy(fontFamily = f, fontWeight = FontWeight.SemiBold, letterSpacing = 0.3.sp),
        titleLarge = titleLarge.copy(fontFamily = f, fontWeight = FontWeight.SemiBold),
        titleMedium = titleMedium.copy(fontFamily = f, fontWeight = FontWeight.Medium),
        titleSmall = titleSmall.copy(fontFamily = f, fontWeight = FontWeight.Bold),
        bodyLarge = bodyLarge.copy(fontFamily = f, letterSpacing = 0.2.sp),
        bodyMedium = bodyMedium.copy(fontFamily = f, letterSpacing = 0.1.sp),
        bodySmall = bodySmall.copy(fontFamily = f, letterSpacing = 0.1.sp),
        labelMedium = labelMedium.copy(fontFamily = f, fontWeight = FontWeight.Medium, letterSpacing = 0.8.sp),
        labelSmall = labelSmall.copy(fontFamily = f, letterSpacing = 0.5.sp),
    )
}

@Composable
fun EchoTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    MaterialTheme(
        colorScheme = EchoLightScheme,
        typography = EchoTypography,
        shapes = EchoShapes,
        content = content,
    )
}
