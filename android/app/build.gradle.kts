import java.io.FileInputStream
import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("com.google.dagger.hilt.android")
    id("com.google.devtools.ksp")
}

val signingProperties = Properties()
val signingPropertiesFile = rootProject.file("signing.properties")
if (signingPropertiesFile.exists()) {
    FileInputStream(signingPropertiesFile).use(signingProperties::load)
}

android {
    namespace = "com.demo.management"
    compileSdk = 36

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        applicationId = "com.demo.management"
        minSdk = 26
        targetSdk = 35
        versionCode = 11
        versionName = "1.7.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        manifestPlaceholders["usesCleartextTraffic"] = "false"
    }

    flavorDimensions += "environment"
    productFlavors {
        create("dev") {
            dimension = "environment"
            applicationIdSuffix = ".dev"
            versionNameSuffix = "-dev"
            buildConfigField("String", "API_BASE_URL", "\"http://10.0.2.2:8000/api/v1/\"")
            manifestPlaceholders["usesCleartextTraffic"] = "true"
        }
        create("staging") {
            dimension = "environment"
            applicationIdSuffix = ".staging"
            versionNameSuffix = "-staging"
            buildConfigField("String", "API_BASE_URL", "\"https://staging.example.invalid/api/v1/\"")
        }
        create("production") {
            dimension = "environment"
            buildConfigField("String", "API_BASE_URL", "\"https://example.invalid/api/v1/\"")
        }
    }

    signingConfigs {
        if (signingPropertiesFile.exists()) {
            create("release") {
                storeFile = rootProject.file(signingProperties.getProperty("storeFile"))
                storePassword = signingProperties.getProperty("storePassword")
                keyAlias = signingProperties.getProperty("keyAlias")
                keyPassword = signingProperties.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        debug {
            applicationIdSuffix = ".debug"
        }
        release {
            isMinifyEnabled = false
            // Release artifacts target physical phones. Debug variants keep x86_64 so
            // Gradle Managed Devices can install the app under instrumentation.
            ndk { abiFilters += listOf("arm64-v8a", "armeabi-v7a") }
            signingConfigs.findByName("release")?.let { signingConfig = it }
        }
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    sourceSets {
        getByName("androidTest").assets.srcDir(file("schemas"))
        getByName("test").resources.srcDir(file("schemas"))
    }

    testOptions {
        unitTests.isIncludeAndroidResources = true
    }

    lint {
        // The 1.6 release intentionally freezes dependencies, targetSdk 35 and phone ABIs.
        disable += setOf("ChromeOsAbiSupport", "GradleDependency", "NewerVersionAvailable", "ObsoleteSdkInt", "OldTargetApi", "UseKtx")
    }
}

kotlin {
    jvmToolchain(17)
}

ksp {
    arg("room.schemaLocation", file("schemas").path)
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2026.02.00")
    val serializationBom = platform("org.jetbrains.kotlinx:kotlinx-serialization-bom:1.8.1")
    implementation(composeBom)
    implementation(serializationBom)
    androidTestImplementation(composeBom)
    androidTestImplementation(serializationBom)

    implementation(project(":core:designsystem"))

    implementation("androidx.activity:activity-compose:1.12.4")
    implementation("androidx.core:core-ktx:1.17.0")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.10.0")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.10.0")
    implementation("androidx.navigation:navigation-compose:2.9.7")
    implementation("androidx.hilt:hilt-navigation-compose:1.3.0")
    implementation("androidx.hilt:hilt-work:1.3.0")
    implementation("androidx.datastore:datastore-preferences:1.2.0")
    implementation("androidx.security:security-crypto:1.1.0-alpha06")
    implementation("androidx.room:room-runtime:2.8.4")
    implementation("androidx.room:room-ktx:2.8.4")
    ksp("androidx.room:room-compiler:2.8.4")
    implementation("net.zetetic:sqlcipher-android:4.17.0")
    implementation("androidx.work:work-runtime-ktx:2.10.0")
    implementation("androidx.exifinterface:exifinterface:1.3.7")
    implementation("androidx.camera:camera-camera2:1.4.1")
    implementation("androidx.camera:camera-lifecycle:1.4.1")
    implementation("androidx.camera:camera-view:1.4.1")

    implementation("com.squareup.retrofit2:retrofit:2.11.0")
    implementation("com.squareup.retrofit2:converter-moshi:2.11.0")
    implementation("com.squareup.okhttp3:logging-interceptor:4.12.0")
    implementation("com.squareup.moshi:moshi-kotlin:1.15.1")
    implementation("io.coil-kt:coil-compose:2.7.0")
    implementation("com.google.mlkit:barcode-scanning:17.3.0")
    implementation("com.google.mlkit:text-recognition-chinese:16.0.1")
    implementation("com.google.dagger:hilt-android:2.58")
    ksp("com.google.dagger:hilt-compiler:2.58")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.9.0")
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.6.1")
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
    androidTestImplementation("androidx.room:room-testing:2.8.4")

    debugImplementation("androidx.compose.ui:ui-tooling")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
}

val verifyLiquidUiBoundary by tasks.registering {
    group = "verification"
    description = "Ensures Backdrop stays in :core:designsystem and pages use Liquid primitives."
    doLast {
        val sourceFiles = fileTree("src/main/java") { include("**/*.kt") }.files
        val forbiddenMaterialImports = listOf(
            "import androidx.compose.material3.AlertDialog",
            "import androidx.compose.material3.Button",
            "import androidx.compose.material3.Card",
            "import androidx.compose.material3.FilterChip",
            "import androidx.compose.material3.IconButton",
            "import androidx.compose.material3.ModalBottomSheet",
            "import androidx.compose.material3.OutlinedButton",
            "import androidx.compose.material3.Scaffold",
            "import androidx.compose.material3.TopAppBar",
        )
        val violations = buildList {
            sourceFiles.forEach { file ->
                val text = file.readText()
                if ("com.kyant.backdrop" in text) {
                    add("${file.relativeTo(projectDir)} imports Backdrop directly")
                }
                forbiddenMaterialImports.filter(text::contains).forEach { directImport ->
                    add("${file.relativeTo(projectDir)} uses $directImport")
                }
                if (file.name.endsWith("Screen.kt") && "com.demo.designsystem" !in text) {
                    add("${file.relativeTo(projectDir)} does not use the Liquid design system")
                }
            }
        }
        check(violations.isEmpty()) {
            "Liquid UI boundary violations:\n${violations.joinToString("\n")}"
        }
    }
}

tasks.matching { it.name == "preBuild" }.configureEach {
    dependsOn(verifyLiquidUiBoundary)
}
