package com.demo.management.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.AccountCircle
import androidx.compose.material.icons.automirrored.outlined.Assignment
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.automirrored.outlined.FactCheck
import androidx.compose.material.icons.outlined.Groups
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.outlined.Storage
import androidx.compose.material.icons.outlined.WarningAmber
import androidx.compose.material.icons.outlined.Notifications
import androidx.compose.material.icons.outlined.Feedback
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.TextButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.platform.LocalContext
import com.demo.management.BuildConfig
import com.demo.management.DemoAppViewModel
import com.demo.management.data.BootstrapPayload
import com.demo.management.data.WorkbenchPayload
import com.demo.management.data.LocalSyncSummary
import com.demo.management.core.update.ApkUpdateManager
import com.demo.management.core.update.MobileUpdatePolicy
import com.demo.management.core.update.UpdateDecision
import com.demo.management.feature.projectApplication.ProjectApplicationScreen
import com.demo.management.feature.customer.CustomerScreen
import com.demo.management.feature.customer.CustomerPanoramaScreen
import com.demo.management.feature.task.TaskScreen
import com.demo.management.feature.followup.FollowupScreen
import com.demo.management.feature.customer.CustomerProfileScreen
import com.demo.management.feature.customer.BusinessProfileScreen
import com.demo.management.feature.approval.ApprovalScreen
import com.demo.management.feature.workItem.WorkItemScreen
import com.demo.management.feature.workbench.WorkbenchScreen
import com.demo.management.feature.workbench.workbenchRoute
import com.demo.management.feature.data.DataHubScreen
import com.demo.management.feature.exception.ExceptionCenterScreen
import com.demo.management.feature.notification.NotificationScreen
import com.demo.management.feature.scan.ScanScreen
import com.demo.management.feature.sync.SyncCenterScreen
import com.demo.management.feature.feedback.FeedbackScreen
import com.demo.management.feature.help.HelpScreen
import com.demo.management.feature.assistant.AiDraftScreen
import com.demo.management.feature.adoption.AdoptionScreen
import com.demo.management.feature.onboarding.RoleOnboardingDialog
import com.demo.management.feature.profile.ProfileScreen
import com.demo.management.feature.profile.AppearanceScreen
import com.demo.management.feature.lead.LeadDetailScreen
import com.demo.management.feature.lead.LeadFormScreen
import com.demo.management.feature.lead.LeadWorkbenchScreen
import com.demo.management.feature.lead.canAssignLead
import com.demo.management.feature.lead.canConvertLead
import com.demo.management.feature.lead.canCreateLead
import com.demo.management.feature.lead.canQueueLeadFollowup
import com.demo.management.feature.lead.canOpenProjectApplication
import com.demo.management.feature.lead.canOpenLeadWorkspace
import com.demo.management.feature.lead.canOpenLeadOperationsWorkbench
import com.demo.management.feature.lead.canUseLeadOcr
import com.demo.management.feature.lead.canUseProductIntent
import com.demo.management.feature.lead.leadFormFeatures
import com.demo.management.feature.collaboration.CustomerTagsScreen
import com.demo.management.feature.collaboration.DeliveryScreen
import com.demo.management.feature.collaboration.canViewCustomerTags
import com.demo.management.feature.collaboration.canViewFulfillment
import com.demo.management.core.reminder.canUseAiDrafts
import com.demo.management.core.notification.notificationTarget
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.NavType
import androidx.navigation.navArgument
import com.demo.designsystem.components.AppScaffold
import com.demo.designsystem.components.LiquidActionButton
import com.demo.designsystem.components.LiquidBottomBar
import com.demo.designsystem.components.LiquidDialog
import com.demo.designsystem.components.LiquidIconButton
import com.demo.designsystem.components.LiquidNavigationItem
import com.demo.designsystem.components.LiquidTopBar
import com.demo.designsystem.components.StateLayout
import com.demo.designsystem.components.StateLayoutState
import com.demo.designsystem.glass.LiquidBackdropHost
import com.demo.designsystem.theme.AppearanceSettings
import com.demo.designsystem.theme.GlassPreference
import com.demo.designsystem.theme.LiquidTheme
import com.demo.designsystem.theme.LiquidThemeMode
import com.demo.designsystem.theme.LiquidUiConfig
import com.demo.designsystem.theme.MotionPreference

private data class TabItem(val key: String, val label: String, val icon: ImageVector)

private val allTabs = listOf(
    TabItem("home", "首页", Icons.Outlined.Home),
    TabItem("customers", "客户", Icons.Outlined.Groups),
    TabItem("projects", "项目", Icons.AutoMirrored.Outlined.Assignment),
    TabItem("approvals", "审批", Icons.AutoMirrored.Outlined.FactCheck),
    TabItem("data", "数据", Icons.Outlined.Storage),
    TabItem("exceptions", "异常", Icons.Outlined.WarningAmber),
)

private val customerTabPermissions = setOf("customer.view", "crm_task.view", "crm_customer_profile.view", "crm_business_profile.view")
private val projectTabPermissions = setOf("crm_project.view", "crm_project.create", "crm_task.view", "crm_followup.view", "crm_issue.view")
private val approvalTabPermissions = setOf("approval.view", "approval.approve", "crm_lead.approve", "customer_tag.review")
private val dataTabPermissions = setOf(
    "customer.view", "product.view", "supplier.view", "sales_detail.view", "purchase_detail.view",
    "inventory_snapshot.view", "account_balance.view", "inventory_check.view", "receivable.view",
)
private val exceptionTabPermissions = setOf("exception_center.view")

internal fun visibleTabKeys(
    featureFlags: Map<String, Boolean>,
    permissions: Collection<String>,
    serverNavigation: Collection<String> = emptyList(),
): List<String> = buildList {
    add("home")
    if (hasCrmCustomerWorkspace(featureFlags, permissions) || canOpenLeadWorkspace(permissions, featureFlags)) add("customers")
    if (hasCrmProjectWorkspace(featureFlags, permissions) || canViewFulfillment(permissions, featureFlags)) add("projects")
    if (featureFlags["crm_approvals"] == true && permissions.any(approvalTabPermissions::contains)) add("approvals")
    if (featureFlags["exception_center"] == true && permissions.any(exceptionTabPermissions::contains)) {
        add("exceptions")
    } else if (featureFlags["data_query"] == true && permissions.any(dataTabPermissions::contains)) {
        add("data")
    }
}.let { keys ->
    if (serverNavigation.isEmpty()) keys else keys.filter { it == "home" || it in serverNavigation }
}

internal fun hasCrmCustomerWorkspace(featureFlags: Map<String, Boolean>, permissions: Collection<String>): Boolean =
    (featureFlags["crm_customers"] == true || featureFlags["customers"] == true) &&
        permissions.any(customerTabPermissions::contains)

internal fun hasCrmProjectWorkspace(featureFlags: Map<String, Boolean>, permissions: Collection<String>): Boolean =
    (featureFlags["crm_tasks"] == true || featureFlags["project_application"] == true) &&
        permissions.any(projectTabPermissions::contains)

internal fun canonicalMobileRoute(target: String): String = when (target) {
    "tasks" -> "projects"
    else -> target
}

@Composable
fun DemoApp(
    viewModel: DemoAppViewModel,
    initialTarget: String? = null,
    onTargetHandled: () -> Unit = {},
) {
    val state by viewModel.state.collectAsState()
    var dismissedOptionalUpdateVersion by rememberSaveable { mutableStateOf<Int?>(null) }
    val appConfig = state.bootstrap?.app
    LiquidTheme(
        settings = state.appearanceSettings,
        config = LiquidUiConfig(
            liquidUiEnabled = appConfig?.liquidUiEnabled ?: true,
            fullEffectEnabled = appConfig?.liquidFullEffectEnabled ?: true,
            darkThemeEnabled = appConfig?.darkThemeEnabled ?: true,
            forceReducedGlass = appConfig?.forceReducedGlass ?: false,
            themeVersion = appConfig?.uiThemeVersion ?: "liquid_v1",
        ),
    ) {
        LiquidBackdropHost {
            if (!state.sessionReady) {
                StateLayout(
                    state = StateLayoutState.Loading("正在恢复登录状态"),
                    modifier = Modifier.fillMaxSize(),
                    content = {},
                )
            } else if (!state.authenticated) {
                LoginScreen(
                    loading = state.loading,
                    error = state.error,
                    onLogin = viewModel::login,
                )
            } else {
                val context = LocalContext.current
                val config = state.bootstrap?.app
                val updateDecision = config?.let {
                    MobileUpdatePolicy.decide(
                        current = BuildConfig.VERSION_CODE,
                        latest = it.latestVersionCode,
                        minimum = it.minimumSupportedVersionCode,
                        mode = it.updateMode,
                    )
                } ?: UpdateDecision.None
                val showOptionalUpdate = config != null && MobileUpdatePolicy.shouldShowOptionalPrompt(
                    decision = updateDecision,
                    latestVersionCode = config.latestVersionCode,
                    dismissedVersionCode = dismissedOptionalUpdateVersion,
                )
                Box(modifier = Modifier.fillMaxSize()) {
                    MainShell(
                        loading = state.loading,
                        error = state.error,
                        workbench = state.workbench,
                        bootstrap = state.bootstrap,
                        localDraftCount = state.localDraftCount,
                        syncSummary = state.syncSummary,
                        onRefresh = viewModel::refreshHome,
                        onSyncNow = viewModel::syncNow,
                        onRefreshSync = viewModel::refreshSyncSummary,
                        onLogout = viewModel::logout,
                        onRefreshDrafts = viewModel::refreshLocalDrafts,
                        onClearDrafts = viewModel::clearLocalDrafts,
                        onStartUpdate = { config?.let { ApkUpdateManager.start(context, it) } },
                        updateDecision = updateDecision,
                        initialTarget = initialTarget,
                        onTargetHandled = onTargetHandled,
                        appearanceSettings = state.appearanceSettings,
                        onThemeMode = viewModel::setThemeMode,
                        onGlassPreference = viewModel::setGlassPreference,
                        onMotionPreference = viewModel::setMotionPreference,
                    )
                    if (
                        state.onboardingRequired &&
                        updateDecision != UpdateDecision.Required &&
                        !showOptionalUpdate
                    ) {
                        RoleOnboardingDialog(
                            role = state.bootstrap?.user?.role.orEmpty(),
                            onComplete = viewModel::completeOnboarding,
                        )
                    }
                    if (updateDecision == UpdateDecision.Required && config != null) {
                        LiquidDialog(
                            onDismissRequest = {},
                            title = { Text("必须更新到 ${config.latestVersion}") },
                            text = { Text(config.releaseNotes ?: "当前版本已停止支持，请更新后继续使用。") },
                            confirmButton = {
                                TextButton(onClick = { ApkUpdateManager.start(context, config) }) { Text("下载更新") }
                            },
                            dismissButton = { TextButton(onClick = viewModel::logout) { Text("退出登录") } },
                        )
                    } else {
                        config?.takeIf { showOptionalUpdate }?.let { optionalConfig ->
                            LiquidDialog(
                                onDismissRequest = {
                                    dismissedOptionalUpdateVersion = optionalConfig.latestVersionCode
                                },
                                title = { Text("发现新版本 ${optionalConfig.latestVersion}") },
                                text = {
                                    Text(optionalConfig.releaseNotes ?: "新版本已经发布，建议更新后使用。")
                                },
                                confirmButton = {
                                    TextButton(
                                        onClick = { ApkUpdateManager.start(context, optionalConfig) },
                                    ) {
                                        Text("立即更新")
                                    }
                                },
                                dismissButton = {
                                    TextButton(
                                        onClick = {
                                            dismissedOptionalUpdateVersion = optionalConfig.latestVersionCode
                                        },
                                    ) {
                                        Text("稍后提醒")
                                    }
                                },
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun LoginScreen(
    loading: Boolean,
    error: String?,
    onLogin: (String, String) -> Unit,
) {
    var username by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp),
        verticalArrangement = Arrangement.Center,
    ) {
        Text("星河演示管理中心", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
        Text("客户业务协作", color = MaterialTheme.colorScheme.primary)
        Spacer(modifier = Modifier.height(24.dp))
        OutlinedTextField(
            value = username,
            onValueChange = { username = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("账号") },
            singleLine = true,
        )
        Spacer(modifier = Modifier.height(12.dp))
        OutlinedTextField(
            value = password,
            onValueChange = { password = it },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("密码") },
            singleLine = true,
            visualTransformation = PasswordVisualTransformation(),
        )
        if (!error.isNullOrBlank()) {
            Spacer(modifier = Modifier.height(12.dp))
            Text(error, color = MaterialTheme.colorScheme.error)
        }
        Spacer(modifier = Modifier.height(20.dp))
        LiquidActionButton(
            onClick = { onLogin(username, password) },
            modifier = Modifier.fillMaxWidth(),
            enabled = !loading && username.isNotBlank() && password.isNotBlank(),
        ) {
            if (loading) {
                CircularProgressIndicator()
            } else {
                Text("登录")
            }
        }
    }
}

@Composable
private fun MainShell(
    loading: Boolean,
    error: String?,
    workbench: WorkbenchPayload?,
    bootstrap: BootstrapPayload?,
    localDraftCount: Int,
    syncSummary: LocalSyncSummary?,
    onRefresh: () -> Unit,
    onSyncNow: () -> Unit,
    onRefreshSync: () -> Unit,
    onLogout: () -> Unit,
    onRefreshDrafts: () -> Unit,
    onClearDrafts: () -> Unit,
    onStartUpdate: () -> Unit,
    updateDecision: UpdateDecision,
    initialTarget: String?,
    onTargetHandled: () -> Unit,
    appearanceSettings: AppearanceSettings,
    onThemeMode: (LiquidThemeMode) -> Unit,
    onGlassPreference: (GlassPreference) -> Unit,
    onMotionPreference: (MotionPreference) -> Unit,
) {
    val featureFlags = bootstrap?.app?.featureFlags.orEmpty()
    val permissions = bootstrap?.permissions.orEmpty()
    val visibleKeys = visibleTabKeys(
        featureFlags = featureFlags,
        permissions = permissions,
        serverNavigation = bootstrap?.navigation.orEmpty().map { it.key },
    )
    val tabs = allTabs.filter { it.key in visibleKeys }
    val navController = rememberNavController()
    val backStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = backStackEntry?.destination?.route ?: "home"
    LaunchedEffect(initialTarget) {
        val target = initialTarget?.let(::canonicalMobileRoute)?.takeIf {
            it in setOf("approvals", "work_items", "notifications", "projects", "deliveries", "data", "exceptions", "sync_center", "customer_development", "me") ||
                it.matches(Regex("lead/[1-9][0-9]*"))
        }
        if (target != null) {
            navController.navigate(target) { launchSingleTop = true }
            onTargetHandled()
        }
    }
    val isFullScreenFlow = currentRoute in setOf(
        "project_application",
        "project_application?customerCode={customerCode}&customerName={customerName}",
        "customer_development",
        "deliveries",
        "customer/{code}/tags",
        "lead/new",
        "lead/{leadId}",
        "followup/{taskId}",
        "customer_profile/{code}",
        "customer/{code}",
        "business_profile/{code}",
        "scan",
        "help",
        "feedback/{source}",
        "ai_drafts",
        "adoption",
        "appearance",
    )
    AppScaffold(
        topBar = {
            if (!isFullScreenFlow) {
                LiquidTopBar(
                    title = {
                        Text(
                            when (currentRoute) {
                                "projects" -> "项目"
                                "approvals" -> "审批中心"
                                "me" -> "我的"
                                "work_items" -> "待支持事项"
                                "notifications" -> "通知中心"
                                "sync_center" -> "同步中心"
                                "exceptions" -> "异常中心"
                                else -> tabs.firstOrNull { currentRoute.startsWith(it.key) }?.label ?: "工作台"
                            }
                        )
                    },
                    navigationIcon = {
                        if (currentRoute == "me") {
                            LiquidIconButton(onClick = { navController.popBackStack() }) {
                                Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = "返回")
                            }
                        }
                    },
                    actions = {
                        if (currentRoute == "home") {
                            LiquidIconButton(onClick = onRefresh, enabled = !loading) {
                                Icon(Icons.Outlined.Refresh, contentDescription = "刷新")
                            }
                        }
                        if (bootstrap?.app?.featureFlags?.get("notifications") == true && currentRoute != "notifications") {
                            LiquidIconButton(onClick = { navController.navigate("notifications") }) {
                                Icon(Icons.Outlined.Notifications, contentDescription = "通知")
                            }
                        }
                        if (bootstrap?.app?.feedbackEnabled == true && bootstrap.app.featureFlags["in_app_feedback"] == true && !currentRoute.startsWith("feedback")) {
                            LiquidIconButton(onClick = { navController.navigate("feedback/${android.net.Uri.encode(currentRoute)}") }) {
                                Icon(Icons.Outlined.Feedback, contentDescription = "问题反馈")
                            }
                        }
                        if (currentRoute != "me") {
                            LiquidIconButton(onClick = { navController.navigate("me") { launchSingleTop = true } }) {
                                Icon(Icons.Outlined.AccountCircle, contentDescription = "我的")
                            }
                        }
                    },
                )
            }
        },
        bottomBar = {
            if (!isFullScreenFlow && currentRoute != "me") {
                LiquidBottomBar(
                    items = tabs.map { LiquidNavigationItem(it.key, it.label, it.icon) },
                    selectedKey = tabs.firstOrNull { currentRoute.startsWith(it.key) }?.key ?: "home",
                    onSelected = { key ->
                        navController.navigate(key) {
                            launchSingleTop = true
                            restoreState = true
                            popUpTo("home") { saveState = true }
                        }
                    },
                )
            }
        },
    ) { padding ->
        NavHost(
            navController = navController,
            startDestination = "home",
            modifier = if (isFullScreenFlow) Modifier.fillMaxSize() else Modifier.fillMaxSize().padding(padding),
        ) {
            composable("home") {
                ScreenContainer(error) {
                    WorkbenchScreen(
                        payload = workbench,
                        loading = loading,
                        onCreateProject = { navController.navigate("project_application") },
                        onOpenProjects = { navController.navigate("projects") },
                        onOpenApprovals = { navController.navigate("approvals") },
                        onOpenWorkItems = { navController.navigate("work_items") },
                        onTarget = { target ->
                            workbenchRoute(target)?.let { route ->
                                navController.navigate(route) { launchSingleTop = true }
                            }
                        },
                    )
                }
            }
            composable("customers") {
                ScreenContainer(error) {
                    if (hasCrmCustomerWorkspace(featureFlags, permissions)) {
                        CustomerScreen(
                            onOpenCustomer = { code -> navController.navigate("customer/${android.net.Uri.encode(code)}") },
                            canOpenCustomerDevelopment = canOpenLeadWorkspace(permissions, featureFlags),
                            onCustomerDevelopment = { navController.navigate("customer_development") },
                        )
                    } else {
                        LeadWorkbenchScreen(
                            permissions = permissions,
                            featureFlags = featureFlags,
                            canCreate = canCreateLead(permissions, featureFlags),
                            onCreate = { navController.navigate("lead/new") },
                            onOpen = { id -> navController.navigate("lead/$id") },
                        )
                    }
                }
            }
            composable("customer/{code}", arguments = listOf(navArgument("code") { type = NavType.StringType })) { entry ->
                val code = entry.arguments?.getString("code") ?: return@composable
                CustomerPanoramaScreen(
                    customerCode = code,
                    onClose = { navController.popBackStack() },
                    onEditProfile = { customerCode -> navController.navigate("customer_profile/${android.net.Uri.encode(customerCode)}") },
                    onEditBusinessProfile = { customerCode -> navController.navigate("business_profile/${android.net.Uri.encode(customerCode)}") },
                    onTarget = { target ->
                        workbenchRoute(target)?.let { route -> navController.navigate(route) { launchSingleTop = true } }
                    },
                    canOpenTags = canViewCustomerTags(bootstrap?.permissions.orEmpty(), bootstrap?.app?.featureFlags.orEmpty()),
                    onOpenTags = { customerCode -> navController.navigate("customer/${android.net.Uri.encode(customerCode)}/tags") },
                )
            }
            composable("customer/{code}/tags", arguments = listOf(navArgument("code") { type = NavType.StringType })) { entry ->
                if (canViewCustomerTags(bootstrap?.permissions.orEmpty(), bootstrap?.app?.featureFlags.orEmpty())) {
                    CustomerTagsScreen(
                        customerCode = entry.arguments?.getString("code") ?: return@composable,
                        onClose = { navController.popBackStack() },
                    )
                } else LaunchedEffect(Unit) { navController.popBackStack() }
            }
            composable("projects") {
                ScreenContainer(error) {
                    if (hasCrmProjectWorkspace(featureFlags, permissions)) {
                        TaskScreen(
                            onFollowup = { taskId -> navController.navigate("followup/$taskId") },
                            onCreateProject = { navController.navigate("project_application") },
                            canOpenDeliveries = canViewFulfillment(permissions, featureFlags),
                            onOpenDeliveries = { navController.navigate("deliveries") },
                        )
                    } else {
                        DeliveryScreen()
                    }
                }
            }
            composable("deliveries") {
                if (canViewFulfillment(bootstrap?.permissions.orEmpty(), bootstrap?.app?.featureFlags.orEmpty())) {
                    DeliveryScreen(onClose = { navController.popBackStack() })
                } else LaunchedEffect(Unit) { navController.popBackStack() }
            }
            composable("tasks") {
                LaunchedEffect(Unit) {
                    navController.navigate("projects") {
                        popUpTo("tasks") { inclusive = true }
                        launchSingleTop = true
                    }
                }
            }
            composable(
                "data?module={module}&q={query}",
                arguments = listOf(
                    navArgument("module") { type = NavType.StringType; nullable = true; defaultValue = null },
                    navArgument("query") { type = NavType.StringType; nullable = true; defaultValue = null },
                ),
            ) { entry ->
                ScreenContainer(error) {
                    DataHubScreen(
                        featureFlags = bootstrap?.app?.featureFlags.orEmpty(),
                        isAdmin = bootstrap?.user?.role == "admin",
                        onScan = { navController.navigate("scan") },
                        onOpenData = { module, query ->
                            navController.navigate("data?module=${android.net.Uri.encode(module)}&q=${android.net.Uri.encode(query)}") { launchSingleTop = true }
                        },
                        initialModule = entry.arguments?.getString("module"),
                        initialQuery = entry.arguments?.getString("query"),
                    )
                }
            }
            composable("exceptions") {
                if (bootstrap?.app?.featureFlags?.get("exception_center") == true && bootstrap.permissions.contains("exception_center.view")) {
                    ScreenContainer(error) { ExceptionCenterScreen() }
                } else {
                    LaunchedEffect(Unit) {
                        navController.navigate("home") { popUpTo("exceptions") { inclusive = true } }
                    }
                }
            }
            composable("me") {
                ScreenContainer(error) {
                    ProfileScreen(
                        bootstrap = bootstrap,
                        localDraftCount = localDraftCount,
                        syncSummary = syncSummary,
                        onRefreshDrafts = onRefreshDrafts,
                        onClearDrafts = onClearDrafts,
                        onSync = onSyncNow,
                        onRefreshSync = onRefreshSync,
                        onOpenSyncCenter = { navController.navigate("sync_center") },
                        onStartUpdate = onStartUpdate,
                        updateDecision = updateDecision,
                        canOpenHelp = bootstrap?.app?.helpEnabled == true,
                        canOpenFeedback = bootstrap?.app?.feedbackEnabled == true && bootstrap.app.featureFlags["in_app_feedback"] == true,
                        canOpenAiDrafts = canUseAiDrafts(bootstrap?.user?.role.orEmpty(), bootstrap?.app?.featureFlags.orEmpty()),
                        canOpenAdoption = bootstrap?.user?.role == "admin" && bootstrap.app.featureFlags["adoption_dashboard"] == true,
                        onOpenAppearance = { navController.navigate("appearance") },
                        onOpenHelp = { navController.navigate("help") },
                        onOpenFeedback = { navController.navigate("feedback/me") },
                        onOpenAiDrafts = { navController.navigate("ai_drafts") },
                        onOpenAdoption = { navController.navigate("adoption") },
                        onLogout = onLogout,
                    )
                }
            }
            composable(
                "project_application?customerCode={customerCode}&customerName={customerName}",
                arguments = listOf(
                    navArgument("customerCode") { type = NavType.StringType; nullable = true; defaultValue = null },
                    navArgument("customerName") { type = NavType.StringType; nullable = true; defaultValue = null },
                ),
            ) { entry ->
                if (canOpenProjectApplication(bootstrap?.permissions.orEmpty(), bootstrap?.app?.featureFlags.orEmpty())) {
                    bootstrap?.user?.let { user ->
                        ProjectApplicationScreen(
                            applicant = user,
                            prefillCustomerCode = entry.arguments?.getString("customerCode"),
                            prefillCustomerName = entry.arguments?.getString("customerName"),
                            onClose = { navController.popBackStack() },
                        )
                    }
                } else LaunchedEffect(Unit) { navController.popBackStack() }
            }
            composable("customer_development") {
                if (canOpenLeadOperationsWorkbench(bootstrap?.permissions.orEmpty(), bootstrap?.app?.featureFlags.orEmpty())) {
                    ScreenContainer(error) {
                        LeadWorkbenchScreen(
                            permissions = bootstrap?.permissions.orEmpty(),
                            featureFlags = bootstrap?.app?.featureFlags.orEmpty(),
                            canCreate = canCreateLead(bootstrap?.permissions.orEmpty(), bootstrap?.app?.featureFlags.orEmpty()),
                            onCreate = { navController.navigate("lead/new") },
                            onOpen = { id -> navController.navigate("lead/$id") },
                        )
                    }
                } else LaunchedEffect(Unit) { navController.popBackStack() }
            }
            composable("lead/new") {
                if (canCreateLead(bootstrap?.permissions.orEmpty(), bootstrap?.app?.featureFlags.orEmpty())) {
                    LeadFormScreen(
                        ocrEnabled = canUseLeadOcr(bootstrap?.permissions.orEmpty(), bootstrap?.app?.featureFlags.orEmpty()),
                        features = leadFormFeatures(bootstrap?.permissions.orEmpty(), bootstrap?.app?.featureFlags.orEmpty()),
                        onClose = { navController.popBackStack() },
                        onSubmitted = { id -> navController.navigate("lead/$id") { popUpTo("customer_development") } },
                    )
                } else LaunchedEffect(Unit) { navController.popBackStack() }
            }
            composable("lead/{leadId}", arguments = listOf(navArgument("leadId") { type = NavType.LongType })) { entry ->
                if (canOpenLeadWorkspace(bootstrap?.permissions.orEmpty(), bootstrap?.app?.featureFlags.orEmpty())) {
                    LeadDetailScreen(
                        leadId = entry.arguments?.getLong("leadId") ?: return@composable,
                        canQueueFollowup = canQueueLeadFollowup(bootstrap?.permissions.orEmpty(), bootstrap?.app?.featureFlags.orEmpty()),
                        canAssign = canAssignLead(bootstrap?.permissions.orEmpty(), bootstrap?.app?.featureFlags.orEmpty()),
                        canConvert = canConvertLead(bootstrap?.permissions.orEmpty(), bootstrap?.app?.featureFlags.orEmpty()),
                        canUseProducts = canUseProductIntent(bootstrap?.permissions.orEmpty(), bootstrap?.app?.featureFlags.orEmpty()),
                        canOpenProject = canOpenProjectApplication(bootstrap?.permissions.orEmpty(), bootstrap?.app?.featureFlags.orEmpty()),
                        onClose = { navController.popBackStack() },
                        onOpenProject = { code, name ->
                            navController.navigate("project_application?customerCode=${android.net.Uri.encode(code)}&customerName=${android.net.Uri.encode(name)}")
                        },
                    )
                } else LaunchedEffect(Unit) { navController.popBackStack() }
            }
            composable("followup/{taskId}", arguments = listOf(navArgument("taskId") { type = NavType.LongType })) { entry ->
                FollowupScreen(
                    taskId = entry.arguments?.getLong("taskId") ?: return@composable,
                    onClose = { navController.popBackStack() },
                    voiceEnabled = bootstrap?.app?.featureFlags?.get("voice_input") == true,
                )
            }
            composable("customer_profile/{code}", arguments = listOf(navArgument("code") { type = NavType.StringType })) { entry ->
                val code = entry.arguments?.getString("code") ?: return@composable
                CustomerProfileScreen(
                    code = code,
                    onClose = { navController.popBackStack() },
                    ocrEnabled = bootstrap?.app?.featureFlags?.get("contact_ocr") == true,
                )
            }
            composable("business_profile/{code}", arguments = listOf(navArgument("code") { type = NavType.StringType })) { entry ->
                val code = entry.arguments?.getString("code") ?: return@composable
                BusinessProfileScreen(code = code, name = code, onClose = { navController.popBackStack() })
            }
            composable("approvals") { ScreenContainer(error) { ApprovalScreen() } }
            composable("work_items") { ScreenContainer(error) { WorkItemScreen() } }
            composable("notifications") {
                ScreenContainer(error) {
                    NotificationScreen(
                        onClose = { navController.popBackStack() },
                        onOpen = { item -> navController.navigate(notificationTarget(item)) { launchSingleTop = true } },
                        smartRemindersEnabled = bootstrap?.app?.featureFlags?.get("smart_reminders") == true,
                    )
                }
            }
            composable("sync_center") {
                ScreenContainer(error) { SyncCenterScreen(onClose = { navController.popBackStack() }) }
            }
            composable("help") { HelpScreen(onClose = { navController.popBackStack() }) }
            composable("feedback/{source}", arguments = listOf(navArgument("source") { type = NavType.StringType })) { entry ->
                FeedbackScreen(sourceRoute = entry.arguments?.getString("source"), onClose = { navController.popBackStack() })
            }
            composable("ai_drafts") {
                if (canUseAiDrafts(bootstrap?.user?.role.orEmpty(), bootstrap?.app?.featureFlags.orEmpty())) {
                    AiDraftScreen(onClose = { navController.popBackStack() })
                } else {
                    LaunchedEffect(Unit) { navController.popBackStack() }
                }
            }
            composable("adoption") {
                if (bootstrap?.user?.role == "admin" && bootstrap.app.featureFlags["adoption_dashboard"] == true) {
                    AdoptionScreen(onClose = { navController.popBackStack() })
                } else {
                    LaunchedEffect(Unit) { navController.popBackStack() }
                }
            }
            composable("appearance") {
                AppearanceScreen(
                    settings = appearanceSettings,
                    onThemeMode = onThemeMode,
                    onGlassPreference = onGlassPreference,
                    onMotionPreference = onMotionPreference,
                    onClose = { navController.popBackStack() },
                )
            }
            composable("scan") {
                ScanScreen(
                    onClose = { navController.popBackStack() },
                    onOpenMatch = { match ->
                        val module = match.target?.get("module") ?: if (match.type == "product") "products" else "customers"
                        val query = match.target?.get("query") ?: match.code
                        navController.navigate("data?module=${android.net.Uri.encode(module)}&q=${android.net.Uri.encode(query)}") {
                            popUpTo("home")
                        }
                    },
                )
            }
        }
    }
}

@Composable
private fun ScreenContainer(error: String?, content: @Composable () -> Unit) {
    StateLayout(
        state = if (error.isNullOrBlank()) StateLayoutState.Content else StateLayoutState.Error(error),
        modifier = Modifier.fillMaxSize(),
        content = {
            Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
                content()
            }
        },
    )
}
