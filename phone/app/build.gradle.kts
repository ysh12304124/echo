plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.echo.phone"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.echo.phone"
        // Rokid CXR-L SDK 要求 minSdk 31。
        minSdk = 31
        targetSdk = 34
        versionCode = 1
        versionName = "1.0.0"
        // 真机通过局域网访问后台：改成运行 uvicorn 的电脑局域网 IP。
        // 模拟器用 10.0.2.2；真机用电脑 IP（如 192.168.1.130）。
        buildConfigField("String", "API_BASE_URL", "\"http://192.168.1.130:8000/api/v1/\"")

        // 眼镜端 Echo CustomApp 的包名与入口（须与 glasses/ 模块一致）。
        buildConfigField("String", "GLASS_APP_PACKAGE", "\"com.echo.glasses\"")
        buildConfigField("String", "GLASS_APP_ENTRY", "\".MainActivity\"")
        // true=用 Mock 眼镜（无真机离线开发）；false=接真实 Rokid CXR-L SDK。
        buildConfigField("boolean", "USE_MOCK_GLASSES", "false")
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    composeOptions {
        kotlinCompilerExtensionVersion = "1.5.8"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2024.09.00")
    implementation(composeBom)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("io.coil-kt:coil-compose:2.6.0")
    implementation("androidx.activity:activity-compose:1.8.2")
    implementation("androidx.navigation:navigation-compose:2.7.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.7.0")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.7.0")

    implementation("com.squareup.retrofit2:retrofit:2.9.0")
    implementation("com.squareup.retrofit2:converter-gson:2.9.0")
    implementation("com.google.code.gson:gson:2.10.1")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.squareup.okhttp3:logging-interceptor:4.12.0")

    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.3")

    // Rokid CXR-L SDK（手机端）：鉴权/会话/音频/拍照/自定义指令/设备控制。
    // 仓库 https://maven.rokid.com/repository/maven-public/ 已在 settings.gradle.kts 配置。
    // 鉴权由 Rokid AI App（≥1.9.0）承担，无需 appId/appSecret。
    implementation("com.rokid.cxr:client-l:1.0.4")

    testImplementation("junit:junit:4.13.2")
    debugImplementation("androidx.compose.ui:ui-tooling")
}
