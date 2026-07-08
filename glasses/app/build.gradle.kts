plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.echo.glasses"
    compileSdk = 34

    defaultConfig {
        // 须与手机端 BuildConfig.GLASS_APP_PACKAGE 保持一致。
        applicationId = "com.echo.glasses"
        // Rokid CXR-S SDK 要求 minSdk 31。
        minSdk = 31
        targetSdk = 34
        versionCode = 1
        versionName = "1.0.0"
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
    implementation("androidx.core:core-ktx:1.12.0")
    implementation("androidx.appcompat:appcompat:1.6.1")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.3")

    // Rokid CXR-S SDK（眼镜端桥）：接收手机自定义指令、上报物理按键。
    // 仓库 https://maven.rokid.com/repository/maven-public/ 已在 settings.gradle.kts 配置。
    implementation("com.rokid.cxr:cxr-service-bridge:1.0-20260417.063502-103")
}
