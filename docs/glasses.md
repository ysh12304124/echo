# 眼镜端（`glasses/`）

Rokid Glass3 上运行的轻量 CXR-S CustomApp（Android，Kotlin）。只负责**录像 + IMU 采样 + 按键交互**，
不采集音频（音频由手机麦克风直接录制），不做任何本地存储/上传落地——所有数据边采集边通过
`CXRServiceBridge.sendMessage` 转发给手机端，由手机转发给后台。

## 目录结构

| 文件 | 职责 |
| --- | --- |
| `MainActivity.kt` | 场景选择、录制状态机、视频分片/IMU 发送、按键分发、CXR 连接状态展示 |
| `VideoRecorder.kt` | 基于 Camera2 API 的本地录像，边写文件边把新增字节回调给 `MainActivity` 发送 |
| `receiver/KeyReceiver.kt` | 系统按键广播接收器，归一化为 `KeyType` 上报给 `MainActivity` |

## 场景与操作

三种时间记忆场景（单击场景条切换，录制中不可切换）：

| 场景 | 命令 | 用途 |
| --- | --- | --- |
| Onsite | `ONSITE` | 现场巡检/走访 |
| Meeting | `MEETING` | 会议 |
| Quality Time | `QUALITY_TIME` | 陪伴时光（独立数据分区） |

按键手势（`KeyType`，见 `KeyReceiver.kt`；双击被系统占用为"退出应用"，单指长按被系统 AI 助手占用，
故不可用于本应用）：

| 手势 | 广播 Action | 行为 |
| --- | --- | --- |
| 单击 | `ACTION_SPRITE_BUTTON_CLICK` | 开始 / 结束当前场景的时间记忆录制 |
| 双指前滑 / 后滑 | `ACTION_TWO_FINGER_SWIPE_FORWARD/BACK` | 未录制时循环切换场景 |
| 双指长按 | `ACTION_TWO_FINGER_LONG_PRESS` | 切换空间记忆（IMU 1Hz 采样）开/关，与时间记忆录制独立、可同时进行 |

## 与手机端的消息协议（CXR-S `rk_custom_key` / `rk_custom_client`）

眼镜经 `sendMessage("rk_custom_key", Caps)` 主动上报给手机，`Caps` 首个字段是消息类型：

| 类型 | 字段 | 说明 |
| --- | --- | --- |
| `cmd` | `START\|STOP`, `sceneCmd`, `sid` | 开始/结束时间记忆录制，`sid` 为本次记忆的会话号 |
| `video_chunk` | `sid`, `index`, `base64` | 视频分片（当前仍用 Base64 编码，分片大小 `CHUNK=50KB`） |
| `video_patch` | `sid`, `"0"`, `base64` | 录制结束后用最终文件头覆盖此前发出的头部（修正 `MediaRecorder` 回改的 `mdat` box 大小字段） |
| `video_end` | `sid`, `filename` | 视频发送完毕 |
| `imu` | `ax,ay,az,gx,gy,gz,timestamp`（各自独立字段） | 空间记忆开启时 1Hz 采样的加速度计+陀螺仪读数 |
| `space_state` | `"on"\|"off"` | 空间记忆开关状态变化，供手机端实时展示，不依赖 IMU 数据流间接推断 |

手机经 `subscribe("rk_custom_client")` 回推给眼镜（`MainActivity.mc`）：

| 类型 | 说明 |
| --- | --- |
| `status` | 云端/后台状态文本，展示在眼镜连接状态栏 |
| `memory_complete` | 后台 `complete` 成功后通知眼镜（当前阶段仅记录日志，不清理本地视频，便于测试对照） |

## 发送重试

`sendCmd` 统一封装 `bridge.sendMessage`：实测 `ret=-3` 集中出现在系统 AI 助手唤起或息屏抢占应用前台
（CXR 会话 `SESSION_AI_START` / `SESSION_SCREEN_OFF`）期间，属短暂性失败。因此失败时在后台线程
（`upExec`，避免阻塞主线程）做有限次数（`MAX_SEND_RETRY=5`，间隔 `150ms`）阻塞重试，重试仍失败则丢弃
并记录日志。

## 权限与依赖

- `AndroidManifest.xml` 仅声明 `CAMERA`（`VideoRecorder` 用 Camera2 API）与 `INTERNET`
  （经 CXR-S 走网络，尽管实际发送走 `sendMessage` 而非直接 HTTP）。
- `build.gradle.kts` 依赖仅 `androidx.core`/`androidx.appcompat` + Rokid `cxr-service-bridge`
  （不依赖 CameraX/Coroutines，`VideoRecorder` 直接用原生 Camera2 API）。

## 编译与安装

方式 A（推荐，Android Studio）：打开 `glasses/` 完成 Gradle Sync → Build → Build APK(s)。
产物：`glasses/app/build/outputs/apk/debug/app-debug.apk`。

方式 B（命令行）：

```bash
cd glasses
gradle wrapper            # 首次生成 gradlew（需本机已装 Gradle）
./gradlew :app:assembleDebug
```

> 首次会从 `https://maven.rokid.com/repository/maven-public/` 拉取 `cxr-service-bridge` 依赖，需联网。

安装到眼镜（眼镜本身是一台 Android 设备，需先在其"开发者选项"开启 USB 调试）：

```bash
adb devices                                        # 确认眼镜已被识别（USB 直连或 adb connect <IP>:5555）
adb install -r glasses/app/build/outputs/apk/debug/app-debug.apk
adb shell pm list packages | grep com.echo.glasses  # 验证安装
adb shell am start -n com.echo.glasses/.MainActivity
```

> 多设备时用 `-s <序列号>` 指定眼镜。也可由手机端 CXR-L `appUploadAndInstall(apkPath)` 推送安装，
> 日常联调推荐先用 adb 直接装更直接。

包名（`applicationId`，默认 `com.echo.glasses`）须与手机端 `GLASS_APP_PACKAGE` 一致。
CXR-L 协议细节见 [protocols/rokid-cxr-integration.md](protocols/rokid-cxr-integration.md)。
