# Echo Glasses App（CXR-S CustomApp）

Rokid 眼镜端轻量应用，基于 **CXR-S**（`com.rokid.cxr:cxr-service-bridge`）。与眼镜原有翻译/提词器等
应用**并存、不覆盖**，出现在眼镜应用列表（LAUNCHER）。会话由手机端 CXR-L `appStart` 主导拉起。

## 职责

- `subscribe("rk_custom_client")` 接收手机端状态并在镜片显示（待机 / 记忆中 / 空间采集中 / 已暂停）。
- 捕获物理按键（镜腿键 / 触控板 / 返回键）经 `sendMessage("rk_custom_key")` 上报手机端。
- **不采集媒体**：音频/拍照由眼镜固件经 CXR-L 直达手机。

## 模块

- `MainActivity.kt` — 初始化 `CXRServiceBridge`、订阅指令、显示状态、上报按键。
- `receiver/KeyReceiver.kt` — 眼镜系统按键广播 → 归一为 `KeyType` 上报。

## 安装

1. 用 Android Studio 打开 `glasses/`，编译 `:app`。
2. `adb connect <眼镜/所在机器>` 后 `adb install -r app-debug.apk`（或由手机端 `appUploadAndInstall` 推送）。
3. 包名（`applicationId`）须与手机端 `GLASS_APP_PACKAGE` 一致（默认 `com.echo.glasses`）。

详见 [../docs/protocols/rokid-cxr-integration.md](../docs/protocols/rokid-cxr-integration.md)。
