# Echo 架构总览

识境 Echo 是一套"眼镜采集 → 手机转发 → 后台存储/编排 → 算力服务异步分析"的记忆系统，
由四个独立模块组成，分别在各自目录下有更详细的模块文档：

| 模块 | 目录 | 文档 | 职责 |
| --- | --- | --- | --- |
| 眼镜端 | `glasses/` | [glasses.md](glasses.md) | Rokid Glass3 CustomApp：录像、采样 IMU、按键交互，边录边发给手机 |
| 手机端 | `phone/` | [phone.md](phone.md) | Android App：连接眼镜、录音、转发视频/音频/IMU 给后台、查询展示 |
| 后台服务 | `backend/` | [backend.md](backend.md) | FastAPI：接收上传、编排记忆生成、提交算力任务、查询/证据接地问答 |
| 算力服务 | `compute/` | [compute.md](compute.md) | 独立 FastAPI 微服务：ASR/视觉/重建等 AI 推理，异步回调后台落库 |

## 总体数据流

```
┌──────────┐  CXR-S sendMessage   ┌──────────┐   REST (OpenAPI, multipart)   ┌──────────┐
│ 眼镜端    │ ──视频分片/IMU/按键──► │ 手机端    │ ───────────────────────────► │ 后台服务  │
│ glasses/ │ ◄──状态/记忆完成────  │ phone/   │  上传视频/音频/IMU、complete   │ backend/ │
└──────────┘   (CXRServiceBridge) └──────────┘   查询记忆/证据接地问答         └────┬─────┘
                                       ▲                                         │
                                       │ 手机麦克风采集音频直传                    │ 提交分析任务 (POST /analyze/*)
                                       │                                         ▼
                                  （不经眼镜）                              ┌──────────┐
                                                                          │ 算力服务  │
                                                                          │ compute/ │
                                                                          └────┬─────┘
                                                    回调 POST /internal/callback/* │
                                                    （X-Internal-Token 鉴权，结果落库）
                                                                                  ▼
                                                                            SQLite + Blob
                                                                            + 向量检索
```

关键点：

- **眼镜不采集音频**：音频由手机麦克风直接录制上传，眼镜只负责视频（Camera2 录制）与 IMU 采样。
- **视频边录边传、后台不落地转发**：眼镜按分片通过 CXR-S `sendMessage` 推给手机，手机原样透传给后台
  （`POST /ingest/sessions/{id}/video`，服务端按 `index` 顺序 `append`，收到末片 `rename` 成片）。
- **后台是数据库唯一属主**，算力服务无状态：只按共享磁盘路径读写媒体文件，不直连后台数据库。
- **`complete` 立即返回，重活异步甩给算力服务**：后台收到 `complete` 后创建 `status=processing` 的记忆并
  立即应答，实际的语音转写/视觉分析/空间重建由算力服务后台跑完后主动回调，回调处理器按 `memory_id`
  幂等覆盖式更新记忆为 `completed`（或 `failed`）。详见 [protocols/compute-service.md](protocols/compute-service.md)。

## 核心领域对象（后台）

- **TimeMemory**：时间记忆（Meeting / Onsite / QualityTime 三种场景）
- **SpaceMemory**：空间记忆（质量评级、锚点、3D 模型）
- **Event**：关键瞬间（系统内部索引，用户不直接管理）
- **Evidence**：证据（视觉 / 音频转写 / OCR / 空间 / 用户备注）
- **Entity**：实体（人物 / 项目 / 设备 / 地点）
- **Binding**：时空绑定（记忆级 / 瞬间级 / 证据级 / 候选）
- **DataPartition**：数据分区（`work` / `quality_time`，强制隔离）

## 查询三态

1. **确定答案**（`confirmed`）— 高置信证据支撑，返回答案 + 证据 + 来源
2. **可能相关证据**（`possible`）— 高置信未命中，低置信候选降级展示
3. **没有找到**（`not_found`）— 无可用证据，不猜测

## 产品硬规则（代码必须遵守）

- 手动开启，不被动记录
- 查询必须有证据，无证据不回答
- Quality Time 数据独立分区，不参与全局工作查询
- 首页只做识别，导航型摘要在记忆详情二级页
- 底部 Tab 仅：首页、查询、我的
- 低置信内容不主动打扰，仅查询降级召回

## 端到端接入顺序（真机）

手机上涉及**两个不同的 App**，别混淆：

- **Rokid AI App**（官方伴侣 App，`com.rokid.sprite.aiapp`）：从应用商店安装，版本 **≥ 1.9.0**。
  负责眼镜配对/固件/账号，并为第三方 App 提供授权。**不是**编译 `phone/` 得到的。
- **Echo App**（`com.echo.phone`）：由 Android Studio 编译 `phone/` 得到，鉴权依赖上面的 Rokid AI App。

推荐顺序：

1. **眼镜端**：编译 `glasses/` 出 APK，`adb install` 到眼镜（见 [glasses.md](glasses.md)）。
2. **手机装伴侣**：安装 Rokid AI App，登录账号，蓝牙配对眼镜，确认"已连接"。
3. **手机装 Echo**：Android Studio 编译安装 `phone/`，`USE_MOCK_GLASSES=false`。
4. **打通**：Echo 点"连接眼镜" → 唤起 Rokid AI App 授权页 → 同意麦克风/相机权限 → 返回 token →
   CXR-L 经已配对链路连上眼镜并 `appStart` 拉起眼镜端 Echo App。

## 全链路验证清单

| 检查项 | 验证方式 |
| --- | --- |
| 无证据不回答 | 查询不存在的信息 → `status=not_found`，answer 为 null |
| 有证据返回答案 | 录制会议后查询 → `confirmed` + 转写/视觉证据 + 来源记忆 |
| 低置信降级 | 仅低置信证据/模型不确定 → `possible` + 提示，不下确定结论 |
| Quality Time 分区 | quality_time 记忆不出现在 work 列表，也不参与 global_work 查询 |
| 分区强制 | meeting/onsite + quality_time 组合 → 400 |
| 首页只识别 | 列表卡片仅识别简介，导航型摘要在详情页 |
| 时空绑定 | 并行时间+空间 → 记忆详情出现候选绑定，可确认/否定 |
| 视频/音频/IMU 上传 | 记忆结束后 `session` 目录下依次出现 `video/*.mp4`、`audio/*.pcm`、`imu/imu.jsonl` |
| 异步分析 | `complete` 立即返回 `processing`（或 mock 模式秒级 `completed`），算力回调后转 `completed` |
| 媒体服务 | `GET /api/v1/media/{key}` 返回文件，缺失 404 |
| 三 Tab 无陪伴 | 底部仅首页/查询/我的 |

## 离线开发（无真机、无本地模型）

- 后台 `ECHO_PROVIDER_MODE=mock` + `ECHO_COMPUTE_PROVIDER_MODE=mock`：AI 由确定性 Mock 提供，
  算力任务在进程内同步"秒回"，无需启动 `compute/` 服务。
- 手机端 `USE_MOCK_GLASSES=true`：`MockGlassesConnection` 周期发合成视频分片，真实上传链路照常走。
- 三端均可在无真机/无本地模型时打通，便于开发与回归，见各模块文档的"运行"章节。
