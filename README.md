# 识境 Echo MVP

一副眼镜，一个随身 AI 智能秘书。用户手动开启记录，系统记住时间现场与空间现场，事后通过 App 查询、回溯和查看证据。

## 模块

| 模块 | 路径 | 技术栈 | 说明 | 文档 |
|------|------|--------|------|------|
| 后台服务 | `backend/` | Python FastAPI | 媒体摄入、记忆编排、提交算力任务、查询 | [docs/backend.md](docs/backend.md) |
| 手机端 | `phone/` | Android Kotlin + Compose + Rokid CXR-L | 链路主导：鉴权/建会话、收麦克风音频与眼镜视频、上传后台、查询 UI | [docs/phone.md](docs/phone.md) |
| 眼镜端 | `glasses/` | Android Kotlin + Rokid CXR-S | 轻量 CustomApp：录像+IMU 采样、边采边发、物理按键上报 | [docs/glasses.md](docs/glasses.md) |
| 算力服务 | `compute/` | Python FastAPI | 独立微服务：ASR/视觉/重建等 AI 推理，异步回调后台 | [docs/compute.md](docs/compute.md) |

## 快速开始

### 后台

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API 文档: http://localhost:8000/docs

### 手机端

用 Android Studio 打开 `phone/` 编译运行。`phone/app/build.gradle.kts` 的 `USE_MOCK_GLASSES=true`
可无真机离线跑通全链路；接真机时置为 `false`（需先装 **Rokid AI App ≥ 1.9.0** 并配对眼镜）。

### 眼镜端

用 Android Studio 打开 `glasses/`，编译后用 `adb` 安装到 Rokid 眼镜（或由手机端 `appUploadAndInstall` 推送）。
包名须与手机端 `GLASS_APP_PACKAGE` 一致（默认 `com.echo.glasses`）。会话由手机端 CXR-L `appStart` 主导拉起。

## 文档

- 总体架构、数据流、接入顺序、验证清单: [docs/architecture.md](docs/architecture.md)
- 各模块文档: [docs/backend.md](docs/backend.md) / [docs/phone.md](docs/phone.md) /
  [docs/glasses.md](docs/glasses.md) / [docs/compute.md](docs/compute.md)
- 协议契约: 手机 ↔ 后台 [docs/protocols/openapi.yaml](docs/protocols/openapi.yaml)，
  后台 ↔ 算力 [docs/protocols/compute-service.md](docs/protocols/compute-service.md)，
  眼镜 ↔ 手机 [docs/protocols/rokid-cxr-integration.md](docs/protocols/rokid-cxr-integration.md)

## 数据分区

- **工作分区** (`work`): Meeting、Onsite 时间记忆 + 工作空间记忆，参与全局工作查询
- **Quality Time 分区** (`quality_time`): 独立存储，不参与全局工作查询
