# 后台服务（`backend/`）

FastAPI 服务，负责接收眼镜/手机上传的媒体、编排记忆生成、把重活异步甩给 [算力服务](compute.md)、
提供查询（RAG 证据接地问答）与前端所需的所有 REST 接口。总体架构见 [architecture.md](architecture.md)。

## 分层

| 层 | 目录 | 职责 |
| --- | --- | --- |
| API | `app/api/routes.py` | HTTP 路由，请求/响应校验，全量端点见下表 |
| Service | `app/services/` | 业务编排（摄入、查询、人物、算力客户端） |
| Domain | `app/domain/` | 领域模型（`models.py`）与枚举（`enums.py`） |
| Provider | `app/providers/` | 可插拔 AI/存储接口 + Mock/Local 实现 |
| Repository | `app/repositories/` | SQLAlchemy 持久化（SQLite）与检索 |
| Schema | `app/schemas/` | Pydantic 请求/响应模型 |

## 关键模块

- `app/main.py` — FastAPI app、CORS、请求日志中间件、`/health`、静态媒体路由。
- `app/logging_setup.py` — 统一日志，落盘 `log/echo.log`（滚动 10MB×5）+ 控制台。
- `app/services/ingest_pipeline.py` — 摄入编排：建会话、接收视频分片/音频/IMU、`complete` 时创建
  `processing` 记忆并提交算力任务（见下）。
- `app/services/compute_client.py` — 算力客户端抽象：`MockComputeClient`（进程内同步回填，测试/离线用）
  与 `HttpComputeClient`（真实 HTTP 提交给 `compute/`），由 `compute_provider_mode` 切换。
- `app/services/query_engine.py` — 查询三态（确定/可能相关/没有找到）、证据接地问答、导航摘要。
- `app/services/person_service.py` — 人物合并/拆分/命名，分区隔离。
- `app/providers/` — `LLMProvider` / `EmbeddingProvider` / `VectorStore` / `BlobStore` 接口；
  ASR/VLM/OCR/3D 重建**已不在后台内实现**，全部迁到 `compute/`（见 [compute.md](compute.md)）。

## API 端点一览

前缀均为 `/api/v1`。

| 分组 | 端点 | 说明 |
| --- | --- | --- |
| 摄入 | `POST /ingest/sessions` | 创建采集会话（时间/空间记忆） |
| | `POST /ingest/sessions/{id}/video` | 视频分片上传（multipart，按 `index` 顺序 append） |
| | `POST /ingest/sessions/{id}/video/patch` | 覆盖写视频临时文件头部（修正 MediaRecorder 回改字节） |
| | `POST /ingest/sessions/{id}/audio` | 手机麦克风音频分片上传（PCM） |
| | `POST /ingest/sessions/{id}/imu` | IMU 批量上报（只写 `imu.jsonl` 文件，不入库） |
| | `POST /ingest/sessions/{id}/complete` | 结束会话：建 `processing` 记忆并提交算力任务，立即返回 |
| 内部回调 | `POST /internal/callback/{audio\|time\|space}` | 算力服务处理完成后回调，`X-Internal-Token` 鉴权 |
| 记忆 | `GET/PATCH/DELETE /memories`、`/memories/{id}` | 时间记忆列表/详情/编辑/删除 |
| 空间 | `GET/PATCH/DELETE /spaces`、`/spaces/{id}` | 空间记忆列表/详情/编辑/删除 |
| 绑定 | `GET /memories/{id}/bindings`、`POST /bindings/{id}/confirm\|reject` | 时空候选绑定 |
| 查询 | `POST /query` | 证据接地问答，返回三态之一 |
| 人物/实体 | `GET/PATCH/DELETE /persons`、`/persons/{id}/split`、`GET /entities` | 人物库管理 |
| 导出 | `POST /export/query-result` | 导出查询结果 |
| 媒体 | `GET /media/{key}` | 按 blob key 返回媒体文件，用于手机端播放/查看 |

完整字段级契约见 [protocols/openapi.yaml](protocols/openapi.yaml)。

## 异步分析流程（与算力服务协作）

`complete_session`（`ingest_pipeline.py`）不在请求内同步跑转写/视觉分析/空间重建：

1. 创建 `status=processing` 的 `TimeMemory` / `SpaceMemory`，立即返回给手机。
2. 通过 `compute_client.submit_audio/time/space(job)` 把任务甩给算力服务（`POST {compute}/analyze/*`）。
3. 算力服务处理完毕后回调 `POST /internal/callback/{type}`，后台按 `memory_id` 幂等覆盖式更新记忆为
   `completed`（或 `failed`），语音转写额外写入 `Evidence(type=transcript)` 并做向量入库。

`compute_provider_mode`（独立于 `provider_mode`）控制走 Mock 还是真实 HTTP：

- `mock`（默认）：`MockComputeClient` 在提交调用内同步回填占位结果，效果等同于"秒级完成"，
  测试/离线开发无需启动 `compute/`。
- `http`：真实提交给 `compute_base_url`（默认 `http://127.0.0.1:8100`），需要 `compute/` 已启动。

完整接口契约（提交/回调 JSON 结构、幂等规则、分工边界）见 [protocols/compute-service.md](protocols/compute-service.md)。

## Provider 模式

`ECHO_PROVIDER_MODE` 控制 LLM/Embedding 走 Mock 还是本地 OpenAI 兼容服务：

- `mock`（默认）：`MockLLMProvider` + `MockEmbeddingProvider`（词法哈希嵌入），离线可跑通全部测试。
- `local`：接 `llm_base_url` / `embedding_base_url` 指向的本地 OpenAI 兼容服务
  （`/v1/chat/completions`、`/v1/embeddings`）。向量落 SQLite（`SqliteVectorStore`），
  numpy 余弦 + metadata 过滤。

ASR（语音转写）与视觉（VLM/OCR）**不再是后台的 Provider**，完全由 `compute/` 服务负责。

## 运行

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # 首次
pip install -r requirements.txt
cp .env.example .env     # 保持 mock 可离线跑；ECHO_INTERNAL_TOKEN 需与 compute/.env 一致
./start.sh    # 后台运行(nohup)，端口 8000，日志只写 log/echo.log
./stop.sh     # 停止
```

验证：`curl http://localhost:8000/health` → `{"status":"ok"}`

## 测试

```bash
cd backend && ECHO_COMPUTE_PROVIDER_MODE=mock pytest -q
```

- 验收用例 1-8（产品文档端到端）
- `SqliteVectorStore` 单测（持久化 / 过滤 / 级联删除）
- 时空绑定候选 + 确认、分区隔离单测
- 算力异步提交/回调链路单测（`test_async_space_reconstruction.py`）
- 本地 provider 集成测试：无服务自动跳过；`ECHO_RUN_LOCAL_TESTS=1` 且服务可达时执行
