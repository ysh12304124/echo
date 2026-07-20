# Echo Compute Service（算力服务）

独立的算力微服务，与 `backend/` **同机部署、共享本地磁盘**，通过 `localhost` HTTP 与后台通信。
职责：接收后台提交的分析任务(音频/时间/空间记忆)，跑推理，处理完毕后主动回调后台落库。

完整接口契约见 [../docs/protocols/compute-service.md](../docs/protocols/compute-service.md)。

## 职责边界

- **无状态**：不直接读写后台的 SQLite 业务库，只按路径读共享磁盘上的媒体文件。
- **异步**：三个端点收到请求立即返回 `202 {job_id}`，用 `BackgroundTask` 跑实际处理，完成后
  `POST` 回后台 `/api/v1/internal/callback/{audio|time|space}`。
- **本期范围**：`/analyze/audio` 是唯一接入正式链路的真实实现（拼接 PCM → WAV → Whisper 转写）；
  `/analyze/time` 与 `/analyze/space` 是桩实现（读输入、记日志、回填占位结果），供后续实现方接入
  真实模型（人脸识别、YOLO、VLM、3D 重建等）。

## 模块

- `app/main.py` — FastAPI 应用，`/analyze/{audio,time,space}` 三个提交端点 + `/health`。
- `app/settings.py` — 配置（`COMPUTE_` 前缀环境变量，见 `.env.example`）。
- `app/logging_setup.py` — 日志（落盘 `log/compute.log` + 控制台），`get_session_logger` 让每条
  日志自动带 `session=<id>`，便于跨服务按会话号联合排查。
- `app/callback.py` — 处理完成后回调后台（带 `X-Internal-Token` 头）。
- `app/openai_client.py` — 极简 Whisper(OpenAI 兼容) 客户端。
- `app/analyze/audio.py` — 语音分析真实实现。
- `app/analyze/time_memory.py` / `app/analyze/space_memory.py` — 时间/空间记忆分析桩实现。

## 运行

```bash
cd compute
python -m venv .venv && source .venv/bin/activate   # 首次运行需要
pip install -r requirements.txt
cp .env.example .env   # 按需修改，COMPUTE_INTERNAL_TOKEN 需与 backend/.env 的 ECHO_INTERNAL_TOKEN 一致
./start.sh   # 默认后台运行(nohup)，端口 8100，日志只写 log/compute.log
./stop.sh    # 停止
```

后台服务默认以 `compute_provider_mode=mock` 运行（不依赖本服务，本地直接回填假结果）。要跑通真实的
提交 → 处理 → 回调全链路，在 `backend/.env` 里把 `ECHO_COMPUTE_PROVIDER_MODE` 改成 `http` 并确保本服务
已启动。

## 验证

```bash
curl -X POST http://127.0.0.1:8100/health
```

正常提交任务后，可在 `compute/log/compute.log` 里按 `session=<id>` 搜索到该会话完整的分析日志，
在 `backend/log/echo.log` 里搜同一个 `session=<id>` 能看到「提交」与「收到回调」两条日志，两边日志
通过 session 号即可串联起一次记忆处理的完整链路。
