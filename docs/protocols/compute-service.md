# 算力服务集成协议（后台 ↔ 算力）

后台服务与算力服务是**同机部署的两个独立进程**（后台负责链路/存储/查询，算力负责 GPU 推理），
通过 `localhost` HTTP 通信，并共享同一块本地磁盘（`backend/data/blobs` 即 blob store 根目录）。
接口之间**只传文件路径，不传字节**：算力服务直接从共享磁盘按路径读输入、写产出。

架构与决策背景见 `docs/superpowers/plans`（如有）或本次改造的 PR 说明；核心原则：

- **后台服务是数据库唯一属主**。算力服务无状态，不直接读写后台的业务库。
- **异步 = 提交 + 回调（模式 B）**：后台 `complete` 时把任务提交给算力服务并立即返回（不等结果），
  算力处理完毕后主动回调后台，后台在回调处理器里落库。
- **本期简化**：不做回调重试、不做对账 sweeper、不做去重/防旧、不建 jobs 表。回调丢失 = 记忆停在
  `processing` 状态，可接受。重跑 = 算力再回调一次，后台按 `memory_id` 覆盖式更新即可，无需特殊处理。

## 角色与端口约定

| 角色 | 默认地址 | 说明 |
|---|---|---|
| 后台服务 | `http://127.0.0.1:8000` | `ECHO_PUBLIC_CALLBACK_BASE_URL`，算力回调时使用 |
| 算力服务 | `http://127.0.0.1:8100` | `ECHO_COMPUTE_BASE_URL`，后台提交任务时使用 |

鉴权：算力回调后台时，请求头带 `X-Internal-Token: <token>`（两端约定的共享密钥，默认开发值见
`backend/.env.example` 与 `compute/.env.example` 的 `ECHO_INTERNAL_TOKEN` / `COMPUTE_INTERNAL_TOKEN`）。
后台的 `/internal/*` 路由只做该 token 校验（本期不做来源 IP 限制、不做重试/签名等更复杂的防护）。

## 总体时序

```
手机 --complete--> 后台: 建 Memory(status=processing) + 生成 job_id
                     |- 提交任务(接口①) --> 算力服务 --202 {job_id}--> 后台立即返回手机 {status: processing}
算力服务(黑盒, 自行读共享盘/推理) 处理完 --回调(接口②)--> 后台: 幂等 upsert 入库 -> status=completed
手机 --轮询 GET /memories/{id} | /spaces/{id}--> 读结果
```

## 接口①：后台 → 算力（提交，异步，发完即走）

统一路径前缀 `POST {compute_base_url}/analyze/{audio|time|space}`，成功返回 `202 { "job_id": "..." }`。
`job_id` 由后台生成并在请求体中传入，算力原样透传，仅用于双端日志关联，不作为查库键
（回调里后台是按请求体中的 `memory_id` 做幂等更新的）。

### A. 语音 `/analyze/audio`（本期唯一接入正式 complete 流程的接口，用于打通整条链路）

```jsonc
POST {compute}/analyze/audio
{
  "job_id": "job-...",
  "memory_id": "...",
  "session_id": "...",
  "partition": "work",
  "inputs": { "audio_paths": ["sessions/{sid}/audio/a1.pcm", "sessions/{sid}/audio/a2.pcm"] },
  "callback_url": "http://127.0.0.1:8000/api/v1/internal/callback/audio"
}
```

算力内部实现：把 `audio_paths` 指向的 PCM（16kHz / 单声道 / 16bit）依序拼接为一个 WAV，调用一次
Whisper（或其它 ASR），输出全量转写文本。

### B. 时间记忆 `/analyze/time`（本期为桩实现，不接入 complete 主流程）

```jsonc
POST {compute}/analyze/time
{
  "job_id": "...", "memory_id": "...", "session_id": "...", "partition": "work",
  "inputs": {
    "video_path": "sessions/{sid}/video/xxx.mp4",
    "audio_paths": ["sessions/{sid}/audio/a1.pcm"]
  },
  "callback_url": "http://127.0.0.1:8000/api/v1/internal/callback/time"
}
```

算力内部（未来实现）：抽帧 → 人脸检测/识别 + YOLO 关键帧/事件 → VLM 总结。本期桩实现只读取输入、
记录日志、回填占位 `result` 并回调，用于验证链路可用。

### C. 空间记忆 `/analyze/space`（本期为桩实现，已接入 complete 主流程，等待真实重建算法接入）

```jsonc
POST {compute}/analyze/space
{
  "job_id": "...", "memory_id": "...", "session_id": "...", "partition": "work",
  "inputs": {
    "video_path": "sessions/{sid}/video/xxx.mp4",
    "imu_path": "sessions/{sid}/imu/imu.jsonl"
  },
  "callback_url": "http://127.0.0.1:8000/api/v1/internal/callback/space"
}
```

算力内部（未来实现）：抽帧 + IMU → 重建/点云，产出模型**文件**，直接写共享磁盘约定路径
（如 `sessions/{sid}/space/model.glb`），回调 JSON 里只回文件路径。

## 接口②：算力 → 后台（回调，结果入库）

统一路径 `POST {public_callback_base_url}/api/v1/internal/callback/{audio|time|space}`，
带 `X-Internal-Token` 头，成功返回 `200 { "accepted": true }`。

通用外层结构：

```jsonc
{
  "job_id": "job-...",
  "memory_id": "...",
  "status": "succeeded",   // 或 "failed"
  "result": { /* 见下方各类型 */ },
  "error": null             // status=failed 时填失败原因
}
```

### A. 语音回调 `result`

```jsonc
{ "transcript": "全量转写文本..." }
```

入库：`transcript` 非空时，覆盖写 `Evidence(type=transcript)`（先删旧后写新，幂等）+ 向量库
upsert（供 `/query` 检索使用），并把 `evidence_status` 置为 `ready`；随后把记忆 `status` 置为
`completed`。`transcript` 为空（如桩/mock 场景）则不写证据，`evidence_status` 保持 `pending`，
记忆 `status` 仍置为 `completed`。

### B. 时间记忆回调 `result`（字段为占位，后续与算力实现方对齐后钉死）

```jsonc
{
  "identify_brief": "共3人 · 会议室｜讨论排期",
  "navigation_summary": {
    "persons": ["3人"], "topics": ["排期"], "spaces": ["会议室"],
    "key_moments": [{"timestamp_ms": 4100, "label": "白板讲解"}],
    "suggested_questions": ["谁负责后端？"]
  },
  "key_frames": [
    {"media_path": "sessions/{sid}/frames/000123.jpg", "filename": "000123.jpg",
     "frame_index": 123, "timestamp_ms": 4100, "label": "白板", "description": "..."}
  ],
  "events": [ {"event_type": "speaking", "start_ms": 3000, "end_ms": 8000, "label": "张三发言", "confidence": "high"} ],
  "faces": [ {"name": null, "crop_path": "sessions/{sid}/faces/f1.jpg", "confidence": "medium"} ]
}
```

入库：`identify_brief` / `navigation_summary` / `key_frames` 映射到 `TimeMemory` 对应字段后置
`completed`。`events` / `faces` 到 `Event` / `Person`+`Binding` 的落库为后续阶段（阶段四）实现，
本期回调处理器仅记录日志，不落库这两项，避免在字段未与实现方钉死前写入不稳定的数据结构。

### C. 空间记忆回调 `result`

```jsonc
{
  "model_url": "sessions/{sid}/space/model.glb",
  "model_format": "glb",
  "quality": "good",
  "loop_angle": 342.0,
  "scene_summary": "客厅，含沙发/电视墙",
  "identify_brief": "客厅空间重建完成",
  "anchors": [ {"name": "电视墙", "anchor_type": "wall", "position": {"x": 0, "y": 0, "z": 0}} ]
}
```

入库：映射到 `SpaceMemory` 对应字段后置 `completed`。

## 幂等与失败

- 所有回调按 `memory_id` **覆盖式更新**（不是 append）；语音证据额外做"先删旧类型再写新"，
  避免重跑产生重复证据行。
- `status = "failed"` 时，记忆置为 `failed`，不覆盖已有的 `identify_brief` 等字段。
- 本期**不做**：回调重试、乱序/旧结果防护(`produced_at` 校验)、对账 sweeper、jobs 状态表。

## 分工边界

| 模块 | 负责方 | 契约 |
|---|---|---|
| `/analyze/audio` 内部（拼接 PCM + Whisper） | 本期实现 | 接口①A / 接口②A |
| `/analyze/time` 内部（人脸/YOLO/VLM） | 后续实现方 | 接口①B / 接口②B |
| `/analyze/space` 内部（重建/点云） | 后续实现方 | 接口①C / 接口②C |
| 后台提交 + 回调入库 + 状态流转 | 后台团队 | 维护本文档定义的 JSON 契约 |

## 日志约定

算力服务与后台服务的日志都遵循"每条日志尽量带上 `session=<session_id>`"的约定，便于按会话号
跨两个服务的日志文件联合排查一次记忆的完整处理过程。算力服务日志参考
`compute/app/logging_setup.py`，风格与 `backend/app/logging_setup.py` 一致（滚动文件 + 控制台）。
