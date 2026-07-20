# 手机端（`phone/`）

原生 Android（Kotlin + Jetpack Compose）应用，是眼镜与后台之间的枢纽：连接眼镜、接收眼镜转发的视频
分片与 IMU、用手机自身麦克风录音、把三类数据实时转发给后台，并承载查询/记忆管理等所有用户界面。

## 目录结构

| 层 | 目录 | 职责 |
| --- | --- | --- |
| UI | `ui/` | Compose 界面 + ViewModel（首页/查询/我的三 Tab，记忆详情、空间详情、人物库等二级页） |
| Domain | `domain/Models.kt` | 业务模型（`VideoChunk`、`ImuSample`、`DeviceStatus`、`MemorySummary` 等） |
| Data | `data/` | 录制编排（`RecordingController`）、后台 API 客户端（`api/`）、眼镜连接（`glasses/`）、麦克风录制 |

## 眼镜连接抽象

`GlassesConnection` 接口（`data/glasses/GlassesConnection.kt`）解耦具体眼镜 SDK，暴露：

- `videoChunkFlow: Flow<VideoChunk>` — 眼镜边录边发的视频分片（`Data`/`Patch`/`End` 三种）
- `imuFlow: Flow<ImuSample>` — 空间记忆开启时的 IMU 采样
- `commands: Flow<GlassCommand>` — 眼镜端按键触发的场景开始/结束指令
- `connectionState` / `deviceStatus` — 连接状态与设备状态（电量、是否正在录制）

两种实现，由 `USE_MOCK_GLASSES`（`build.gradle.kts`）切换：

- `MockGlassesConnection`：无真机开发用，连接后周期产生合成视频分片，可离线跑通"上传→后台存储"全链路。
- `CxrGlassesConnection`（`data/glasses/cxr/`）：真机实现，基于 Rokid CXR-L。通过 `CXRServiceBridge`
  接收眼镜 `rk_custom_key` 消息（`video_chunk`/`video_patch`/`video_end`/`imu`/`cmd`/`space_state`，
  见 [glasses.md](glasses.md) 的消息协议表），视频分片经 Base64 解码后透传进 `videoChunkFlow`。
  鉴权由 Rokid AI App 承担，无需 appId/appSecret，`MainActivity` 已接 `attachActivity`/`onActivityResult`。

## 录制编排（`RecordingController`）

一次时间记忆的完整生命周期：

1. **`startTime`**：创建后台会话（`POST /ingest/sessions`），并行启动三路采集：
   - `collectVideo`：订阅 `videoChunkFlow`，按到达顺序**严格串行**（不并发）转发给后台的
     `/video`（分片）与 `/video/patch`（头部覆盖），保证后台按 `index` 顺序 append 不会因为并发乱序
     导致过早 `rename` 截断成片；`End` 到达即标记 `videoDone`。
   - `collectImu`：订阅 `imuFlow`，攒够 25 条或结束时批量 `POST /imu`（并发甩出去，不阻塞）。
   - `startMic`：`PhoneMicRecorder` 启动手机麦克风录音，音频块并发上传 `POST /audio`。
2. **`stopAndComplete`**：通知眼镜停止录制、停麦克风；等待视频/音频/IMU 全部上传排空
   （最长等待 15s，超时打警告日志但不阻塞流程）；调用 `POST /complete`；成功后
   `glasses.sendMemoryComplete(sid)` 通知眼镜（供其决定是否清理本地视频）。

首页"上传状态"栏（`UploadStatus`）由 `RecordingController.uploadStatus` 驱动，规则：

- 记忆开启后默认显示，展示"视频上传中"/"音频上传中"/（若空间记忆开启）"IMU上传中"；
- 各项传输排空后转为"…上传结束"；
- 全部结束 2 秒后（`UPLOAD_BAR_LINGER_MS`）整栏自动隐藏。

首页顶部状态栏另外两项：

- **眼镜连接状态**：未连接显示"未连接"+连接按钮；已连接显示"眼镜已连接 · 电量 N%"。
- **记忆场景状态**：未开启显示"记忆未开启"；开启后显示"`{场景}`时间记忆中"，若空间记忆同时开启则
  追加"，3D记忆已开启"。

## 与后台的接口（`data/api/EchoApi.kt`）

Retrofit 声明，路径与 [backend.md](backend.md) 的 API 一览一一对应：会话创建/视频/视频头部覆盖/音频/
IMU/complete、记忆与空间的增删改查、绑定确认/否定、查询、人物/实体管理、导出。完整字段契约见
[protocols/openapi.yaml](protocols/openapi.yaml)。

## 运行

- Android Studio 打开 `phone/`，确认 `API_BASE_URL` 指向后台（模拟器用 `10.0.2.2:8000`）。
- 首次启动进入引导页并申请权限（相机/麦克风/蓝牙/定位）。
- `USE_MOCK_GLASSES=true`（默认）：离线可跑通上传全链路；`false`：需先装
  **Rokid AI App ≥ 1.9.0** 并配对眼镜，见 [architecture.md](architecture.md#端到端接入顺序真机)。
- 空间详情页（`SpaceDetailScreen`/`PointCloudViewer`）用 `<model-viewer>`/点云渐进加载后台产出的
  3D 模型，对应字段目前由算力服务的 `/analyze/space` 回调填充（本期为桩实现，见 [compute.md](compute.md)）。
- 底部仅三 Tab：首页 / 查询 / 我的（无陪伴 Tab）。
