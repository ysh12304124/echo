# 端到端联调指南

## 链路

```
眼镜固件 --CXR-S/CXR-L(音频PCM+拍照JPEG+按键)--> 手机端 (phone/) --REST--> 后台 (backend/)
                                                                          |
                    Whisper ASR / 本地 VLM(视觉+OCR) / 本地 LLM / bge Embedding / SQLite 向量检索
```

真实数据流：眼镜固件经 Rokid CXR-L 把音频 PCM + 触发拍照 JPEG 送达手机（手机主导鉴权/建会话，
眼镜端 CustomApp 只显示状态 + 上报物理键）→ 手机边采边传 → 后台摄入流水线
（转写 / 视觉 / OCR / 事件·实体·人物结构化抽取 + 向量索引）→ RAG 查询（证据接地问答）。
详见 [protocols/rokid-cxr-integration.md](protocols/rokid-cxr-integration.md)。

## 真机接入前置与配对顺序

手机上涉及**两个不同的 App**，别混淆：

- **Rokid AI App**（Rokid 官方伴侣 App，包名 `com.rokid.sprite.aiapp`，国际版 `com.rokid.sprite.global.aiapp`）：
  从应用商店 / Rokid 官网安装，版本 **≥ 1.9.0**。负责眼镜配对/固件/账号，并为第三方 App 提供授权。
  **不是**编译 `phone/` 得到的。
- **Echo App**（我们自己的，包名 `com.echo.phone`）：由 Android Studio 编译 `phone/` 得到，鉴权依赖上面的 Rokid AI App。

推荐接入顺序：

1. **眼镜端**：编译 `glasses/` 出 APK，用 `adb` 安装到眼镜（见"三、眼镜端"）。
2. **手机端装伴侣**：安装 **Rokid AI App**，登录 Rokid 账号，在其中按引导（蓝牙"添加设备/扫描"）**与眼镜配对绑定**，确认显示"已连接"。
3. **手机端装 Echo**：Android Studio 编译安装 `phone/`，把 `USE_MOCK_GLASSES` 设为 `false`。
4. **打通**：Echo 点"连接眼镜" → 唤起 Rokid AI App 授权页 → 同意麦克风/相机/媒体 → 返回 token → CXR-L 经已配对链路连上眼镜并 `appStart` 拉起眼镜端 Echo App。

> 注意："眼镜用 adb 接到电脑"（第 1 步，用于装眼镜 App）与"手机↔眼镜蓝牙配对"（第 2 步，在 Rokid AI App 里做）是两条独立通道，互不替代。

## 一、后台

### provider 模式
后台通过 `ECHO_PROVIDER_MODE` 在两种模式切换（见 `backend/.env.example`）：

- `mock`（默认）：离线开发/测试，AI 由确定性 Mock 提供，向量为词法哈希嵌入。
- `local`：接本地部署的 OpenAI 兼容服务：
  - LLM `/v1/chat/completions`（事件/实体抽取、导航摘要、证据接地问答）
  - VLM 多模态（视觉摘要 + OCR，同一模型）
  - Whisper `/v1/audio/transcriptions`（verbose_json 分段）
  - Embedding `/v1/embeddings`（bge/m3e）
  向量落 SQLite（`SqliteVectorStore`），numpy 余弦 + metadata 过滤。

### 启动

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # 首次
pip install -r requirements.txt
cp .env.example .env     # 按本地模型服务地址修改；保持 mock 可离线跑
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

验证：`curl http://localhost:8000/health` → `{"status":"ok"}`

### 测试

```bash
cd backend && pytest -q
```

- 验收用例 1-8（产品文档端到端）
- `SqliteVectorStore` 单测（持久化 / 过滤 / 级联删除）
- 时空绑定候选 + 确认、分区隔离单测
- 本地 provider 集成测试：无服务自动跳过；`ECHO_RUN_LOCAL_TESTS=1` 且服务可达时执行

## 二、手机端（Android / Kotlin）

- Android Studio 打开 `phone/`，确认 `API_BASE_URL` 指向后台（模拟器 `10.0.2.2:8000`）。
- 首次启动进入引导页并申请权限（相机/麦克风/蓝牙/定位）。
- 眼镜连接经 `GlassesConnection` 抽象，由 `phone/app/build.gradle.kts` 的 `USE_MOCK_GLASSES` 切换：
  - `true`（默认）：`MockGlassesConnection` 周期产生合成帧/音频，离线可跑通上传。
  - `false`：`CxrGlassesConnection`（Rokid CXR-L），需先装 **Rokid AI App ≥ 1.9.0** 并配对眼镜；
    鉴权由 AI App 承担，无需 appId/appSecret。`MainActivity` 已接 `attachActivity` / `onActivityResult`。
- 录制经 `RecordingController` 边采边传（帧/音频到达即上传，结束触发后台处理）。
- 眼镜物理键经 `keyEvents` 驱动采集页：单击=开始/结束、双击=标记、长按=结束。
- 空间详情用 WebView + `<model-viewer>` 加载后台 glb 模型（需要 CDN 访问）。
- 底部仅三 Tab：首页 / 查询 / 我的（无陪伴 Tab）。

## 三、眼镜端（Android / Kotlin，CXR-S CustomApp）

眼镜本身是一台 Android 设备。眼镜端 Echo App（`glasses/`，包名 `com.echo.glasses`）需**编译成 APK 并用 adb 安装到眼镜**。
Echo 出现在眼镜应用列表（LAUNCHER），与原有翻译/提词器并存；会话由手机端 CXR-L `appStart` 主导拉起。

### 3.1 编译出 APK

方式 A（推荐，Android Studio）：打开 `glasses/` 完成 Gradle Sync → Build → Build APK(s)。
产物：`glasses/app/build/outputs/apk/debug/app-debug.apk`。

方式 B（命令行）：仓库未附带 `gradlew` 脚本，需先生成 wrapper（或用 Android Studio Sync 后自动生成），再打包：

```bash
cd glasses
gradle wrapper            # 首次生成 gradlew（需本机已装 Gradle）；之后可用 ./gradlew
./gradlew :app:assembleDebug
# 产物：glasses/app/build/outputs/apk/debug/app-debug.apk
```

> 首次会从 `https://maven.rokid.com/repository/maven-public/` 拉取 `cxr-service-bridge` 依赖，需联网。

### 3.2 用 adb 连接眼镜

眼镜先开启"开发者选项 → USB 调试"（在眼镜设置里，或按 Rokid 说明操作）。

- USB 直连：用数据线把眼镜接到电脑（本项目里眼镜接在 130 那台机器）。
- 或无线 adb：眼镜与电脑同一局域网，`adb connect <眼镜IP>:5555`。

确认设备已识别（应能看到眼镜序列号/IP）：

```bash
adb devices
```

如同时接了手机等多台设备，用 `-s <序列号>` 指定眼镜，例如 `adb -s <眼镜序列号> install ...`。

### 3.3 安装到眼镜

```bash
# -r 覆盖安装，-g 直接授予运行时权限（可选）
adb install -r glasses/app/build/outputs/apk/debug/app-debug.apk
# 多设备时：
# adb -s <眼镜序列号> install -r glasses/app/build/outputs/apk/debug/app-debug.apk
```

验证安装成功与可启动：

```bash
adb shell pm list packages | grep com.echo.glasses          # 应列出该包
adb shell am start -n com.echo.glasses/.MainActivity        # 手动拉起，镜片显示"就绪"
```

> 备选：不接线也可由手机端 CXR-L `appUploadAndInstall(apkPath)` 把 APK 推送到眼镜安装
> （需手机侧存储权限，见 `phone/` Manifest）。日常联调推荐先用 adb 预装更直接。

### 3.4 职责与约定

- `MainActivity` 集成 `CXRServiceBridge`：`subscribe("rk_custom_client")` 显示手机状态；
  `receiver/KeyReceiver` 监听镜腿键/触控板/返回键 → `sendMessage("rk_custom_key")` 上报。
- **不采集媒体**：音频/拍照由眼镜固件经 CXR-L 直达手机。
- 包名（`applicationId`）须与手机端 `GLASS_APP_PACKAGE` 一致（默认 `com.echo.glasses`）。
- 协议细节见 [protocols/rokid-cxr-integration.md](protocols/rokid-cxr-integration.md)。

## 四、全链路验证

| 检查项 | 验证方式 |
|--------|----------|
| 无证据不回答 | 查询不存在的信息 → `status=not_found`，answer 为 null |
| 有证据返回答案 | 录制会议后查询 → `confirmed` + 转写/视觉证据 + 来源记忆 |
| 低置信降级 | 仅低置信证据/模型不确定 → `possible` + 提示，不下确定结论 |
| Quality Time 分区 | quality_time 记忆不出现在 work 列表，也不参与 global_work 查询 |
| 分区强制 | meeting/onsite + quality_time 组合 → 400 |
| 首页只识别 | 列表卡片仅识别简介，导航型摘要在详情页 |
| 时空绑定 | 并行时间+空间 → 记忆详情出现候选绑定，可确认/否定 |
| 证据跳转 | 查询结果来源可跳转到对应记忆 |
| 人物编辑 | 命名/合并/拆分/删除，禁跨分区合并 |
| 媒体服务 | `GET /api/v1/media/{key}` 返回文件，缺失 404 |
| 三 Tab 无陪伴 | 底部仅首页/查询/我的 |

## 产品硬规则对照

- ✅ 手动开启，不被动记录（录制均由用户在手机/眼镜手动触发）
- ✅ 查询必须有证据（无证据 → 没有找到；低置信 → 可能相关）
- ✅ Quality Time 数据独立分区并与全局工作查询隔离
- ✅ 首页只做识别，导航型摘要在二级页
- ✅ 底部 Tab 仅三个
- ✅ 低置信不主动打扰

## Mock 模式（无真机全链路）

- 后台 `ECHO_PROVIDER_MODE=mock`
- 手机端 `USE_MOCK_GLASSES=true`：`MockGlassesConnection` 周期发合成帧/音频（`RecordingController` 仍走真实上传）
- 眼镜端无需参与（Mock 模式下手机自产媒体）

三端均可在无真机/无本地模型时打通，便于开发与回归。
