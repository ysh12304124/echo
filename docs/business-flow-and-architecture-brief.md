# 识境 Echo — 业务流程与系统架构简报（供画图用）

> 本文档用于喂给 AI 画图工具生成「系统架构图」与「核心业务流程图」，因此每部分都尽量给出
> **明确的节点、连线、方向、时序编号**，而不是纯叙述性文字。

---

## 一、系统概述

一副智能眼镜 + 一个手机 App + 一个后台服务 + 一个算力服务，组成"手动开启记录 → 云端异步分析 →
证据接地查询"的个人记忆系统。核心原则：**手动开启不被动记录**、**查询必须有证据、无证据不回答**。

产品把记忆分两类：

- **时间记忆**（Time Memory）：会议 / 现场巡检 / 陪伴时光三种场景，录视频+录音，事后转写+分析。
- **空间记忆**（Space Memory）：录视频+IMU 惯性数据，事后做空间重建（点云/3D模型）。

---

## 二、系统架构图要素

### 2.1 节点清单（画架构图用）

| 节点 | 类型 | 部署位置 | 关键技术 |
| --- | --- | --- | --- |
| 眼镜端 App（`glasses/`） | 客户端 | Rokid Glass3 智能眼镜 | Android / Kotlin, Camera2, Rokid CXR-S SDK |
| 手机端 App（`phone/`） | 客户端 | 用户手机 | Android / Kotlin + Jetpack Compose, Rokid CXR-L SDK |
| 后台服务（`backend/`） | 服务端 | 服务器 A（或 3090 机器） | Python FastAPI + SQLAlchemy + SQLite + 向量检索 |
| 算力服务（`compute/`） | 服务端 | 与后台**同机**部署，共享本地磁盘 | Python FastAPI，无状态 |
| ASR 模型服务（Whisper） | 服务端 | 与算力服务同机 | faster-whisper，OpenAI 兼容 `/v1/audio/transcriptions` |
| 视觉/推理模型（预留） | 服务端 | 与算力服务同机（Ollama，尚未接入） | 人脸识别 / YOLO / VLM，用于时间/空间记忆深度分析 |
| SQLite + Blob 存储 | 存储 | 后台本机磁盘 | 结构化数据 + 媒体文件（视频/音频/IMU 原始文件） |
| 向量库 | 存储 | 后台本机磁盘 | 语义检索，供查询引擎使用 |

### 2.2 连线清单（节点A → 节点B：协议/内容，方向）

1. **眼镜端 → 手机端**：Rokid CXR-S `sendMessage("rk_custom_key")`，内容=视频分片（Base64）、
   IMU 采样、场景开始/结束指令、空间记忆开关状态。（眼镜主动推送）
2. **手机端 → 眼镜端**：CXR-S `subscribe("rk_custom_client")`，内容=云端状态文本、
   `memory_complete` 通知。（手机主动推送，反向）
4. **手机端 → 后台服务**：REST/HTTP（multipart），内容=创建会话、视频分片转发、音频分片上传
   （手机麦克风录制）、IMU 批量上传、`complete` 结束会话、查询、记忆/空间/人物管理。
5. **后台服务 → 手机端**：REST 响应，内容=记忆摘要、查询结果（三态）、记忆/空间详情、媒体文件流。
6. **后台服务 → 算力服务**：HTTP `POST /analyze/{audio|time|space}`，内容=`job_id`+`memory_id`+
   媒体文件路径（不传字节，传共享磁盘路径），提交即返回 `202`（异步，发完即走）。
7. **算力服务 → 后台服务**：HTTP `POST /internal/callback/{audio|time|space}`（带鉴权 Token），
   内容=分析结果（转写文本 / 关键帧+事件+摘要 / 3D模型路径），处理完成后回调。
8. **算力服务 → ASR/视觉/推理模型服务**：本机 HTTP（OpenAI 兼容接口），内容=音频/图像推理请求。
9. **后台服务 ↔ 本地存储**：读写 SQLite（结构化数据）、Blob 目录（媒体文件）、向量库（语义检索）。
10. **算力服务 ↔ 共享磁盘**：只读输入媒体文件路径、只写分析产出（转写/关键帧/3D模型文件）。

### 2.3 部署分组（画图时可用于"边界框"）

- **端侧分组**：眼镜端 + 手机端 + Rokid AI App（用户随身设备）
- **服务侧分组**：后台服务 + 算力服务 + ASR/视觉模型（同机部署，多进程，localhost 通信，共享磁盘）

---

## 三、核心业务流程（供画流程图/时序图）

### 流程 A：时间记忆录制与查询（主流程）

```
角色：用户 / 眼镜端 / 手机端 / 后台服务 / 算力服务
```

1. 用户在眼镜上单击物理键，选择场景（Meeting / Onsite / Quality Time），眼镜端开始 Camera2 录像。
2. 眼镜端生成本次记忆的会话号 `sid`，通过 CXR-S 上报「开始」指令给手机端。
3. 手机端收到「开始」指令 → 调用后台 `POST /ingest/sessions` 创建会话 → 同时启动三路采集：
   - 3a. 订阅眼镜转发的视频分片流，逐片转发给后台 `POST /video`（严格按顺序）；
   - 3b. 启动手机自身麦克风录音，音频块上传后台 `POST /audio`；
   - 3c.（若空间记忆已开启）订阅眼镜转发的 IMU 采样，批量上传后台 `POST /imu`。
4. 眼镜端持续录像，每产生一个分片就通过 CXR-S 推送给手机（边录边发，不在眼镜本地落盘保留）。
5. 后台服务收到视频分片，按到达顺序 append 写入临时文件；音频/IMU 分别写入各自目录下的文件。
6. 用户再次单击物理键结束录制 → 眼镜端停止 Camera2、发送最后一片视频 + 结束标记给手机。
7. 手机端等待视频/音频/IMU 全部上传完毕 → 调用后台 `POST /ingest/sessions/{id}/complete`。
8. 后台服务收到 `complete`：
   - 8a. 视频临时文件重命名为最终文件；
   - 8b. 创建一条 `status=processing` 的时间记忆记录，**立即返回**给手机（不等分析结果）；
   - 8c. 把「语音分析任务」提交给算力服务：`POST /analyze/audio`（携带音频文件路径），算力立即回 `202`。
9. 手机端收到 `complete` 响应后，通知眼镜端 `memory_complete`（眼镜据此可清理本地缓存）。
10. 算力服务后台异步处理：拼接音频 → 调用 ASR(Whisper) 模型 → 得到转写文本。
11. 算力服务把结果通过 `POST /internal/callback/audio` 回调给后台服务。
12. 后台服务收到回调：把转写文本写入证据库 + 向量库索引，把记忆状态置为 `completed`。
13. 用户在手机端"查询"页发起提问 → 后台 `POST /query`：
    - 13a. 在向量库/证据库检索相关证据；
    - 13b. 根据证据置信度返回三态之一：**确定答案**（带证据+来源）/ **可能相关**（低置信候选）/
      **没有找到**（无证据，不猜测）。
14. 手机端展示查询结果，用户可点击证据跳转回对应记忆详情。

> 备注（未来阶段，架构已预留）：算力服务对"时间记忆"还会做人脸检测/识别、YOLO 关键帧与事件抽取、
> 视觉大模型（VLM）摘要，结果同样通过 `/internal/callback/time` 回调落库，供手机端展示关键帧/事件/
> 导航摘要（当前为桩实现，接口已打通，未接入真实模型）。

### 流程 B：空间记忆录制（并行于时间记忆，可选开启）

1. 用户在眼镜上做"双指长按"手势，开启空间记忆（与时间记忆录制独立，可同时进行）。
2. 眼镜端启动 IMU（加速度计+陀螺仪）1Hz 采样，通过 CXR-S 推送给手机（同一条视频流复用）。
3. 手机端把 IMU 样本批量转发给后台 `POST /imu`，后台只写入 `imu.jsonl` 文件（不入库）。
4. 用户再次"双指长按"关闭空间记忆（IMU 采样停止），或跟随时间记忆一起结束。
5. `complete` 时，若本次会话是空间记忆类型：后台创建 `status=processing` 的空间记忆记录，
   立即返回；把视频路径 + IMU 文件路径提交给算力服务 `POST /analyze/space`。
6. 算力服务（未来实现）：抽帧 + IMU 融合 → 3D 重建/点云，产出模型文件写入共享磁盘。
7. 算力服务回调 `POST /internal/callback/space`，后台把模型路径等写入空间记忆记录，状态置为
   `completed`。
8. 手机端空间详情页加载 3D 模型/点云展示。

### 流程 C：异步提交-回调机制（横切于 A/B，是关键设计）

```
后台服务                                算力服务
  |--- POST /analyze/{type} (202) ------->|   （提交即返回，不等待）
  |<--- 立即响应手机 processing ----------|
  |                                       |--- 内部推理（ASR/视觉/重建）---
  |<--- POST /internal/callback/{type} ---|   （处理完成后主动回调）
  |--- 200 {accepted:true} -------------->|
  |
  |--- 按 memory_id 幂等更新记忆状态 = completed（或 failed）
```

- 目的：避免 `complete` 请求被算力密集型任务（转写/视觉分析/3D重建）阻塞导致手机端超时。
- 回调丢失的降级行为：记忆停留在 `processing` 状态（本期不做重试/对账，可接受）。

---

## 四、核心数据实体（画 ER 图/数据流图可用）

| 实体 | 关键字段 | 说明 |
| --- | --- | --- |
| IngestSession | session_id, memory_type, scene, partition, status | 一次录制会话，贯穿采集到 complete |
| TimeMemory | memory_id, scene, status, identify_brief, evidence_status | 时间记忆最终产物 |
| SpaceMemory | memory_id, status, model_url, quality, anchors | 空间记忆最终产物 |
| Evidence | type(transcript/visual/ocr/spatial/user_note), content | 支撑查询答案的证据 |
| Event | event_type, label, start_ms, confidence | 记忆内的关键瞬间 |
| Entity | type(person/project/device/location), name | 跨记忆的实体（人物/项目/设备/地点） |
| Binding | binding_type(memory/event/evidence/candidate) | 时间记忆与空间记忆之间的关联 |
| DataPartition | work / quality_time | 数据分区，强制隔离，陪伴时光不进入工作查询 |

## 五、记忆状态机（画状态图可用）

```
not_started → recording → uploading → processing → completed
                                          └────────→ failed
```

- `recording`：用户已开启，眼镜/手机正在采集
- `uploading`：手机仍在把尾部数据传给后台（用户已点结束，短暂过渡态）
- `processing`：后台已创建记忆记录，等待算力服务回调
- `completed` / `failed`：算力回调后终态

---

## 六、关键设计原则（画图时可作为图注/说明框）

- 后台服务是**数据库唯一属主**；算力服务无状态，只按共享磁盘路径读写文件，不直连后台数据库。
- 算力服务与后台服务**同机部署**，两者之间只传路径不传字节，避免多一次网络传输媒体文件。
- 眼镜不采集音频，音频始终由手机麦克风直接录制。
- 视频"边录边传、后台不落地转发"：眼镜产生分片即发，后台按序 append，全部到达后 rename 成片。
- 查询严格证据接地：无证据不回答，低置信不冒充确定答案。
