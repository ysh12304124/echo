# Echo Phone App

原生 Android (Kotlin + Jetpack Compose) 手机端。

## 配置

1. 用 Android Studio 打开 `phone/` 目录
2. 修改 `app/build.gradle.kts` 中的 `API_BASE_URL` 为后台地址
3. `USE_MOCK_GLASSES`：`true` 离线开发；`false` 接真实 Rokid CXR-L 眼镜
   （需装 Rokid AI App ≥ 1.9.0 并配对，`GLASS_APP_PACKAGE` 与 `glasses/` 包名一致）

## 架构

- `domain/` — 业务模型
- `data/api/` — Retrofit 后台客户端（对齐 openapi.yaml）
- `data/glasses/` — 眼镜连接层（`GlassesConnection` 接口 + `MockGlassesConnection`）
- `data/glasses/cxr/` — Rokid CXR-L 实现（`CxrGlassesConnection` + `CxrLinkHub`）
- `data/` — Repository、端上初筛、`RecordingController`
- `ui/` — Compose 界面（首页/查询/我的 三 Tab）

## Rokid CXR-L 对接

`CxrGlassesConnection` 封装：鉴权（`AuthorizationHelper`）→ 建 CustomApp 会话（`CXRLink`）→ appStart
拉起眼镜端 App → 音频 PCM→`audioFlow`、拍照 JPEG→`frameFlow`、物理键→`keyEvents`。
`MainActivity` 负责 `attachActivity` 与 `onActivityResult` 转发鉴权结果。

协议细节见 [../docs/protocols/rokid-cxr-integration.md](../docs/protocols/rokid-cxr-integration.md)。
开发阶段 `USE_MOCK_GLASSES=true` 用 `MockGlassesConnection` 可独立运行。
