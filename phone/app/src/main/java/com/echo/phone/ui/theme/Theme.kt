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

// ── Brand colors ──
private val Blue700 = Color(0xFF1B5E7B)
private val Blue200 = Color(0xFF90CBF0)
private val Blue50 = Color(0xFFD0E8F5)
private val Blue900 = Color(0xFF003548)
private val Blue950 = Color(0xFF001F2E)
private val Slate600 = Color(0xFF5C6B73)
private val Slate200 = Color(0xFFBBC8D0)
private val Slate50 = Color(0xFFF0F4F8)
private val Slate950 = Color(0xFF111318)
private val Slate900 = Color(0xFF1D2025)
private val Surface = Color(0xFFFAFCFF)

// ── Light Color Scheme ──
private val EchoLightScheme = lightColorScheme(
    primary = Blue700,
    onPrimary = Color.White,
    primaryContainer = Blue50,
    onPrimaryContainer = Blue950,
    secondary = Slate600,
    onSecondary = Color.White,
    secondaryContainer = Slate50,
    onSecondaryContainer = Color(0xFF1D1B20),
    tertiary = Color(0xFF6750A4),
    onTertiary = Color.White,
    tertiaryContainer = Color(0xFFEADDFF),
    onTertiaryContainer = Color(0xFF21005D),
    surface = Surface,
    onSurface = Color(0xFF1D1B20),
    surfaceVariant = Slate50,
    onSurfaceVariant = Color(0xFF49454F),
    surfaceContainer = Slate50,
    surfaceContainerHigh = Color(0xFFE5EAF0),
    outline = Slate200,
    outlineVariant = Color(0xFFDEE4E9),
    error = Color(0xFFBA1A1A),
    onError = Color.White,
)

// ── Dark Color Scheme ──
private val EchoDarkScheme = darkColorScheme(
    primary = Blue200,
    onPrimary = Blue950,
    primaryContainer = Color(0xFF004A63),
    onPrimaryContainer = Blue50,
    secondary = Color(0xFFB0BEC5),
    onSecondary = Color(0xFF1D1B20),
    secondaryContainer = Color(0xFF424A52),
    onSecondaryContainer = Slate50,
    tertiary = Color(0xFFD0BCFF),
    onTertiary = Color(0xFF381E72),
    tertiaryContainer = Color(0xFF4F378B),
    onTertiaryContainer = Color(0xFFEADDFF),
    surface = Slate950,
    onSurface = Color(0xFFE6E0E9),
    surfaceVariant = Slate900,
    onSurfaceVariant = Color(0xFFCAC4D0),
    surfaceContainer = Slate900,
    surfaceContainerHigh = Color(0xFF262830),
    outline = Color(0xFF5C5E64),
    outlineVariant = Color(0xFF3E4046),
    error = Color(0xFFFFB4AB),
    onError = Color(0xFF690005),
)

// ── Shapes ──
private val EchoShapes = Shapes(
    extraSmall = RoundedCornerShape(4.dp),
    small = RoundedCornerShape(8.dp),
    medium = RoundedCornerShape(16.dp),
    large = RoundedCornerShape(24.dp),
    extraLarge = RoundedCornerShape(28.dp),
)

// ── Typography ──
private val EchoTypography = Typography().run {
    val f = FontFamily.Default
    copy(
        headlineLarge = headlineLarge.copy(fontFamily = f, fontWeight = FontWeight.Bold),
        headlineMedium = headlineMedium.copy(fontFamily = f, fontWeight = FontWeight.SemiBold, letterSpacing = 0.3.sp),
        titleLarge = titleLarge.copy(fontFamily = f, fontWeight = FontWeight.SemiBold),
        titleMedium = titleMedium.copy(fontFamily = f, fontWeight = FontWeight.Medium, letterSpacing = 0.2.sp),
        titleSmall = titleSmall.copy(fontFamily = f, fontWeight = FontWeight.Bold, letterSpacing = 0.1.sp),
        bodyLarge = bodyLarge.copy(fontFamily = f, letterSpacing = 0.15.sp),
        bodyMedium = bodyMedium.copy(fontFamily = f),
        bodySmall = bodySmall.copy(fontFamily = f),
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
        colorScheme = if (darkTheme) EchoDarkScheme else EchoLightScheme,
        typography = EchoTypography,
        shapes = EchoShapes,
        content = content,
    )
}
