package dev.planneros.android

import androidx.compose.material3.ColorScheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.ui.graphics.Color

/** Shared brand colours. Wine stays a dark fill; ice carries readable accents at night. */
internal object PlannerPalette {
    val Wine = Color(0xFF71383E)
    val Navy = Color(0xFF172B43)
    val Ice = Color(0xFFDCEAF2)
    val IceBlue = Color(0xFF90B9D3)
    val WarmWhite = Color(0xFFF8F6F2)
    val Slate = Color(0xFF16202C)
    val Ink = Color(0xFF1E2B3C)
    val MutedInk = Color(0xFF536575)
    val Teal = Color(0xFF2F6B64)
    val Amber = Color(0xFF946330)
}

internal fun plannerColorScheme(dark: Boolean): ColorScheme = if (dark) {
    darkColorScheme(
        primary = PlannerPalette.IceBlue,
        onPrimary = PlannerPalette.Navy,
        primaryContainer = PlannerPalette.Wine,
        onPrimaryContainer = Color.White,
        inversePrimary = PlannerPalette.Wine,
        secondary = PlannerPalette.Ice,
        onSecondary = PlannerPalette.Navy,
        secondaryContainer = Color(0xFF243F58),
        onSecondaryContainer = PlannerPalette.Ice,
        tertiary = Color(0xFF9ECFC2),
        onTertiary = Color(0xFF123F38),
        tertiaryContainer = Color(0xFF214D46),
        onTertiaryContainer = Color(0xFFD6EFE7),
        background = Color(0xFF101923),
        onBackground = Color(0xFFECF2F6),
        surface = PlannerPalette.Slate,
        onSurface = Color(0xFFECF2F6),
        surfaceVariant = Color(0xFF203245),
        onSurfaceVariant = Color(0xFFB5CBD9),
        surfaceTint = PlannerPalette.IceBlue,
        inverseSurface = PlannerPalette.WarmWhite,
        inverseOnSurface = PlannerPalette.Ink,
        error = Color(0xFFF0B18E),
        onError = Color(0xFF502A14),
        errorContainer = Color(0xFF583323),
        onErrorContainer = Color(0xFFFFE1CA),
        outline = Color(0xFF718A9C),
        outlineVariant = Color(0xFF334B5F),
        scrim = Color.Black,
        surfaceBright = Color(0xFF2A3947),
        surfaceDim = Color(0xFF101923),
        surfaceContainer = Color(0xFF1C2937),
        surfaceContainerHigh = Color(0xFF213143),
        surfaceContainerHighest = Color(0xFF293B4D),
        surfaceContainerLow = Color(0xFF131E2A),
        surfaceContainerLowest = Color(0xFF0C141D)
    )
} else {
    lightColorScheme(
        primary = PlannerPalette.Wine,
        onPrimary = Color.White,
        primaryContainer = PlannerPalette.Wine,
        onPrimaryContainer = Color.White,
        inversePrimary = PlannerPalette.IceBlue,
        secondary = PlannerPalette.Navy,
        onSecondary = Color.White,
        secondaryContainer = PlannerPalette.Ice,
        onSecondaryContainer = PlannerPalette.Navy,
        tertiary = PlannerPalette.Teal,
        onTertiary = Color.White,
        tertiaryContainer = Color(0xFFDDEBE4),
        onTertiaryContainer = Color(0xFF234C43),
        background = PlannerPalette.WarmWhite,
        onBackground = PlannerPalette.Ink,
        surface = Color(0xFFFFFEFB),
        onSurface = PlannerPalette.Ink,
        surfaceVariant = Color(0xFFE7EEF2),
        onSurfaceVariant = PlannerPalette.MutedInk,
        surfaceTint = PlannerPalette.Navy,
        inverseSurface = PlannerPalette.Navy,
        inverseOnSurface = PlannerPalette.Ice,
        error = Color(0xFF9A392A),
        onError = Color.White,
        errorContainer = Color(0xFFF5E4D7),
        onErrorContainer = Color(0xFF682A1D),
        outline = Color(0xFF778994),
        outlineVariant = Color(0xFFCCD7DE),
        scrim = Color.Black,
        surfaceBright = Color(0xFFFFFEFB),
        surfaceDim = Color(0xFFE0E5E7),
        surfaceContainer = Color(0xFFEDF1F2),
        surfaceContainerHigh = Color(0xFFE7EDF0),
        surfaceContainerHighest = Color(0xFFDCE6EC),
        surfaceContainerLow = Color(0xFFF3F5F4),
        surfaceContainerLowest = Color.White
    )
}
