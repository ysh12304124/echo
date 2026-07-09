package com.echo.phone.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * 识境 Echo 科技感主题。
 *
 * 深空底色 + 电光蓝/青作为主强调色，配合克制的圆角与字距，营造简洁耐看的科技风。
 * 仅提供视觉样式，不改变任何业务逻辑；各页面沿用 MaterialTheme 令牌自动适配。
 */

private val ElectricBlue = Color(0xFF4C8DFF)
private val Cyan = Color(0xFF22D3EE)
private val Violet = Color(0xFF8B7BFF)

private val EchoColorScheme = darkColorScheme(
    primary = ElectricBlue,
    onPrimary = Color(0xFF041228),
    primaryContainer = Color(0xFF16305C),
    onPrimaryContainer = Color(0xFFCFE0FF),
    secondary = Cyan,
    onSecondary = Color(0xFF00201F),
    secondaryContainer = Color(0xFF0E3A44),
    onSecondaryContainer = Color(0xFFBDF3FF),
    tertiary = Violet,
    onTertiary = Color(0xFF1B103E),
    tertiaryContainer = Color(0xFF2E2360),
    onTertiaryContainer = Color(0xFFE4DCFF),
    background = Color(0xFF0A0E17),
    onBackground = Color(0xFFE6EDF7),
    surface = Color(0xFF111827),
    onSurface = Color(0xFFE6EDF7),
    surfaceVariant = Color(0xFF1B2740),
    onSurfaceVariant = Color(0xFF9FB0CC),
    surfaceContainer = Color(0xFF141D2F),
    surfaceContainerHigh = Color(0xFF1A2438),
    outline = Color(0xFF2A3A57),
    outlineVariant = Color(0xFF1F2C45),
    error = Color(0xFFFF6B6B),
    onError = Color(0xFF2A0709),
    inversePrimary = Color(0xFF0F4A9C),
)

private val EchoShapes = Shapes(
    extraSmall = RoundedCornerShape(6.dp),
    small = RoundedCornerShape(10.dp),
    medium = RoundedCornerShape(14.dp),
    large = RoundedCornerShape(20.dp),
    extraLarge = RoundedCornerShape(28.dp),
)

private val EchoTypography = Typography().run {
    val f = FontFamily.Default
    copy(
        headlineMedium = headlineMedium.copy(
            fontFamily = f, fontWeight = FontWeight.SemiBold, letterSpacing = 0.5.sp,
        ),
        titleLarge = titleLarge.copy(
            fontFamily = f, fontWeight = FontWeight.SemiBold, letterSpacing = 0.3.sp,
        ),
        titleMedium = titleMedium.copy(
            fontFamily = f, fontWeight = FontWeight.Medium, letterSpacing = 0.2.sp,
        ),
        labelMedium = labelMedium.copy(
            fontFamily = f, fontWeight = FontWeight.Medium, letterSpacing = 1.2.sp,
        ),
        bodyLarge = bodyLarge.copy(fontFamily = f, letterSpacing = 0.15.sp),
    )
}

@Composable
fun EchoTheme(
    // 保留形参以便未来扩展；当前统一使用科技感深色主题。
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    MaterialTheme(
        colorScheme = EchoColorScheme,
        typography = EchoTypography,
        shapes = EchoShapes,
        content = content,
    )
}
