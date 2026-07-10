package com.echo.phone.ui

import androidx.compose.animation.*
import androidx.compose.animation.core.tween
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.echo.phone.data.PermissionManager
import com.echo.phone.domain.DataPartition
import com.echo.phone.ui.home.HomeScreen
import com.echo.phone.ui.memory.MemoryDetailScreen
import com.echo.phone.ui.mine.DeviceScreen
import com.echo.phone.ui.mine.HelpScreen
import com.echo.phone.ui.mine.MineScreen
import com.echo.phone.ui.mine.StorageScreen
import com.echo.phone.ui.onboarding.OnboardingScreen
import com.echo.phone.ui.persons.PersonsScreen
import com.echo.phone.ui.query.QueryScreen
import com.echo.phone.ui.space.SpaceDetailScreen
import com.echo.phone.ui.space.SpaceLibraryScreen
import com.echo.phone.ui.splash.SplashScreen

data class BottomTab(val route: String, val label: String, val icon: ImageVector)

private val tabs = listOf(
    BottomTab(Routes.HOME, "首页", Icons.Default.Home),
    BottomTab(Routes.QUERY, "查询", Icons.Default.Search),
    BottomTab(Routes.MINE, "我的", Icons.Default.Person),
)

@Composable
fun EchoApp() {
    val navController = rememberNavController()
    val context = LocalContext.current
    val navBackStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = navBackStackEntry?.destination?.route
    val showBottomBar = currentRoute in tabs.map { it.route }
    val startDestination = if (PermissionManager.allGranted(context)) Routes.HOME else Routes.ONBOARDING

    // 启动页 → 主界面
    var showSplash by remember { mutableStateOf(true) }
    if (showSplash) {
        SplashScreen(onDone = { showSplash = false })
        return
    }

    Scaffold(
        bottomBar = {
            if (showBottomBar) {
                NavigationBar {
                    tabs.forEach { tab ->
                        NavigationBarItem(
                            selected = currentRoute == tab.route,
                            onClick = {
                                navController.navigate(tab.route) {
                                    popUpTo(Routes.HOME) { saveState = true }
                                    launchSingleTop = true
                                    restoreState = true
                                }
                            },
                            icon = { Icon(tab.icon, contentDescription = tab.label) },
                            label = { Text(tab.label) },
                        )
                    }
                }
            }
        },
    ) { padding ->
        NavHost(
            navController = navController,
            startDestination = startDestination,
            modifier = Modifier.padding(padding),
        ) {
            composable(Routes.ONBOARDING) {
                OnboardingScreen(onDone = {
                    navController.navigate(Routes.HOME) { popUpTo(Routes.ONBOARDING) { inclusive = true } }
                })
            }
            composable(Routes.HOME) {
                HomeScreen(
                    onNavigateMemory = { id -> navController.navigate(Routes.memoryDetail(id)) },
                    onNavigateSpace = { id -> navController.navigate(Routes.spaceDetail(id)) },
                )
            }
            composable(Routes.QUERY) {
                QueryScreen(onNavigateMemory = { id -> navController.navigate(Routes.memoryDetail(id)) })
            }
            composable(Routes.MINE) {
                MineScreen(
                    onNavigatePersons = { navController.navigate(Routes.PERSONS) },
                    onNavigateQualityTime = { navController.navigate(Routes.QUALITY_TIME) },
                    onNavigateSpaces = { navController.navigate(Routes.SPACES) },
                    onNavigateDevice = { navController.navigate(Routes.DEVICE) },
                    onNavigateStorage = { navController.navigate(Routes.STORAGE) },
                    onNavigateHelp = { navController.navigate(Routes.HELP) },
                )
            }
            composable(Routes.MEMORY_DETAIL, arguments = listOf(navArgument("memoryId") { type = NavType.StringType })) { entry ->
                MemoryDetailScreen(
                    memoryId = entry.arguments?.getString("memoryId") ?: "",
                    onBack = { navController.popBackStack() },
                    onNavigateSpace = { id -> navController.navigate(Routes.spaceDetail(id)) },
                )
            }
            composable(Routes.SPACE_DETAIL, arguments = listOf(navArgument("spaceId") { type = NavType.StringType })) { entry ->
                SpaceDetailScreen(spaceId = entry.arguments?.getString("spaceId") ?: "", onBack = { navController.popBackStack() })
            }
            composable(Routes.PERSONS) { PersonsScreen(onBack = { navController.popBackStack() }) }
            composable(Routes.SPACES) { SpaceLibraryScreen(onBack = { navController.popBackStack() }, onOpenSpace = { id -> navController.navigate(Routes.spaceDetail(id)) }) }
            composable(Routes.DEVICE) { DeviceScreen(onBack = { navController.popBackStack() }) }
            composable(Routes.STORAGE) { StorageScreen(onBack = { navController.popBackStack() }) }
            composable(Routes.HELP) { HelpScreen(onBack = { navController.popBackStack() }) }
            composable(Routes.QUALITY_TIME) {
                HomeScreen(partitionFilter = DataPartition.QUALITY_TIME, title = "Quality Time", onNavigateMemory = { id -> navController.navigate(Routes.memoryDetail(id)) }, onNavigateSpace = { id -> navController.navigate(Routes.spaceDetail(id)) })
            }
        }
    }
}
