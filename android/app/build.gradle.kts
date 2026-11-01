// 3D Ops 安卓 App。改了功能就把 versionName / versionCode 加一：GitHub 会编译并发布成 android-v<versionName>，
// ERP 的 设置 → 组件与插件 → 安卓 App 里能取到。
plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// 签名：GitHub 的 Secrets 里放了正式密钥就用（ANDROID_KEYSTORE_FILE 等环境变量，见 .github/workflows/android.yml）；
// 没放就用仓库里固定的 debug.keystore——每次编译签名一样，员工手机上可以直接覆盖安装新版本。
val ksFile = System.getenv("ANDROID_KEYSTORE_FILE")?.takeIf { it.isNotBlank() && file(it).exists() }

android {
    namespace = "com.threedops.app"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.threedops.app"
        minSdk = 24
        targetSdk = 34
        versionCode = 2
        versionName = "1.1.0"
        // 只打包手机 / 平板用的 ARM（条码识别的原生库每种 CPU 一份，去掉模拟器的 x86 小一半）
        ndk { abiFilters += listOf("arm64-v8a", "armeabi-v7a") }
    }

    signingConfigs {
        getByName("debug") {
            storeFile = file("debug.keystore")
            storePassword = "android"
            keyAlias = "androiddebugkey"
            keyPassword = "android"
        }
        create("release") {
            if (ksFile != null) {
                storeFile = file(ksFile)
                storePassword = System.getenv("ANDROID_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("ANDROID_KEY_ALIAS")
                keyPassword = System.getenv("ANDROID_KEY_PASSWORD")
            } else {
                storeFile = file("debug.keystore")
                storePassword = "android"
                keyAlias = "androiddebugkey"
                keyPassword = "android"
            }
        }
    }

    buildTypes {
        getByName("debug") {
            signingConfig = signingConfigs.getByName("debug")
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
        }
        getByName("release") {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = signingConfigs.getByName("release")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        buildConfig = true
    }
    lint {
        abortOnError = false
        checkReleaseBuilds = false
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.activity:activity-ktx:1.9.3")
    implementation("androidx.webkit:webkit:1.11.0")

    // 摄像头 + 条码识别（ML Kit 模型打包在 App 里，不用 Google Play 服务下载，没网也能扫）
    val camerax = "1.3.4"
    implementation("androidx.camera:camera-core:$camerax")
    implementation("androidx.camera:camera-camera2:$camerax")
    implementation("androidx.camera:camera-lifecycle:$camerax")
    implementation("androidx.camera:camera-view:$camerax")
    implementation("com.google.mlkit:barcode-scanning:17.3.0")
    // v1.1 文字识别（拉丁字母：货位牌、单号、SKU；模型打包在 App 里，没网也能用）
    implementation("com.google.mlkit:text-recognition:16.0.1")

    // 本机单元测试（./gradlew testDebugUnitTest）：文字识别挑「像码的文字」（TextCodesTest）
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
}
