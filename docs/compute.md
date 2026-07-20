# 算力服务（`compute/`）

独立的 FastAPI 微服务，与 `backend/` **同机部署、共享本地磁盘**，通过 `localhost` HTTP 通信。
职责：接收后台提交的分析任务（语音 / 时间记忆 / 空间记忆），跑推理，处理完毕后主动回调后台落库。
完整接口契约（提交/回调 JSON 结构、幂等规则）见 [protocols/compute-service.md](protocols/compute-service.md)。

## 职责边界

- **无状态**：不直接读写后台的 SQLite 业务库，只按路径读共享磁盘（`backend/data/blobs`）上的媒体文件。
- **异步**：三个端点收到请求立即返回 `202 {job_id}`，用 `BackgroundTask` 跑实际处理，完成后
  `POST` 回后台 `/api/v1/internal/callback/{audio|time|space}`。
- **本期范围**：`/analyze/audio` 是唯一接入正式链路的真实实现（拼接 PCM → WAV → Whisper 转写）；
  `/analyze/time` 与 `/analyze/space` 是桩实现（读输入、记日志、回填占位结果），已接入 `complete`
  主流程，等待后续接入真实模型（人脸识别、YOLO、VLM、3D 重建等）。

## 模块

| 文件 | 职责 |
| --- | --- |
| `app/main.py` | FastAPI 应用，`/analyze/{audio,time,space}` 三个提交端点 + `/health` |
| `app/settings.py` | 配置（`COMPUTE_` 前缀环境变量，见 `.env.example`） |
| `app/logging_setup.py` | 日志（落盘 `log/compute.log` + 控制台），`get_session_logger` 让每条日志自动带 `session=<id>` |
| `app/callback.py` | 处理完成后回调后台（带 `X-Internal-Token` 头） |
| `app/openai_client.py` | 极简 Whisper（OpenAI 兼容）客户端 |
| `app/analyze/audio.py` | 语音分析真实实现：合并 PCM → WAV → 调一次 Whisper → 回调转写文本 |
| `app/analyze/time_memory.py` / `space_memory.py` | 时间/空间记忆分析桩实现 |

## 模型目录（`compute/models/`）

| 目录 | 状态 | 说明 |
| --- | --- | --- |
| `asr-whisper/` | 已实现 | 基于 `faster-whisper` 的 OpenAI 兼容 ASR 服务，供 `app/analyze/audio.py` 调用 |
| `ollama/` | 预留 | 为后续视觉模型（YOLO/人脸识别）与推理大模型（VLM 总结）预留的部署目录，尚未接入 |

### ASR（Whisper）服务

`compute/models/asr-whisper/`：独立虚拟环境 + FastAPI，包装 `faster-whisper` 提供
`/v1/audio/transcriptions`（OpenAI 兼容）。

```bash
cd compute/models/asr-whisper
sh ./download.sh          # 预下载模型权重，默认 medium，存到 ./weights；国内镜像 hf-mirror.com
# 指定模型规格：WHISPER_MODEL_SIZE=large-v3 ./download.sh，或换回官方源：HF_ENDPOINT=https://huggingface.co ./download.sh
./start.sh                # 后台运行(nohup)，默认端口 8081，日志只写 log/asr.log
./stop.sh                  # 停止
```

`compute/.env` 里的 `COMPUTE_ASR_BASE_URL`（默认 `http://127.0.0.1:8081/v1`）需指向此服务。

## 运行（算力主服务）

```bash
cd compute
python -m venv .venv && source .venv/bin/activate   # 首次运行需要
pip install -r requirements.txt
cp .env.example .env   # COMPUTE_INTERNAL_TOKEN 需与 backend/.env 的 ECHO_INTERNAL_TOKEN 一致
./start.sh   # 默认后台运行(nohup)，端口 8100，日志只写 log/compute.log
./stop.sh    # 停止
```

后台服务默认以 `ECHO_COMPUTE_PROVIDER_MODE=mock` 运行（不依赖本服务，本地直接回填假结果）。要跑通真实的
提交 → 处理 → 回调全链路，在 `backend/.env` 里把 `ECHO_COMPUTE_PROVIDER_MODE` 改成 `http` 并确保本服务
（以及依赖的 `asr-whisper`）已启动。

## 验证

```bash
curl -X POST http://127.0.0.1:8100/health
```

正常提交任务后，可在 `compute/log/compute.log` 里按 `session=<id>` 搜索到该会话完整的分析日志，
在 `backend/log/echo.log` 里搜同一个 `session=<id>` 能看到"提交"与"收到回调"两条日志，两边日志
通过 session 号即可串联起一次记忆处理的完整链路。

## 分工边界

| 模块 | 负责方 | 契约 |
| --- | --- | --- |
| `/analyze/audio` 内部（拼接 PCM + Whisper） | 本期已实现 | 协议接口①A / ②A |
| `/analyze/time` 内部（人脸/YOLO/VLM） | 后续实现方 | 协议接口①B / ②B |
| `/analyze/space` 内部（重建/点云） | 后续实现方 | 协议接口①C / ②C |
| 后台提交 + 回调入库 + 状态流转 | 后台团队 | 维护 [protocols/compute-service.md](protocols/compute-service.md) 定义的 JSON 契约 |
