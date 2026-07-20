# 远程 FastGS 三维重建实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 实现“130 图片 -> 200 COLMAP + FastGS -> 130 PLY -> 手机渲染”的异步三维重建链路，并用 200 上的 `huiyi` 数据集完成端到端验收。

**架构：** 200 新增纯图片重建脚本，负责独立任务目录、COLMAP、FastGS 和结果校验。130 新增远程执行器，使用 SSH/SFTP 传输图片和 PLY，并由空间会话完成流程创建后台任务、更新阶段状态和发布 BlobStore URL。手机复用现有空间 API 和 PLY 查看器。

**技术栈：** Python 3.13、FastAPI、SQLAlchemy、pytest、Paramiko、COLMAP、FastGS、Kotlin/Android WebView。

## 全局约束

- 不使用 IMU 位姿初始化 COLMAP；MVP 由 COLMAP 从纯图片估计位姿。
- 不要求回环检测成功后才启动重建。
- SSH 密码只从运行时环境变量读取，不写入代码、命令参数或日志。
- 所有任务使用唯一 `job_id` 和独立本地/远程目录。
- 130 和 200 两端按固定阶段写结构化日志：`created`、`staging`、`uploading`、`colmap`、`training`、`downloading`、`storing`、`completed`、`failed`。
- 成功和失败任务都必须保存 `result.json` 或等价失败摘要；PLY 必须校验非空和 SHA256。
- 保留用户现有未提交修改，不执行 push，不覆盖无关改动。
- `huiyi` 验收数据源为 `/home/liangjiahua/FastGS/datasets/huiyi/images`，当前约 250 张 JPEG、约 41 MB。

---

### 任务 1：200 主机纯图片 FastGS 重建脚本

**文件：**

- 创建：`/home/liangjiahua/FastGS/scripts/reconstruct_images.py`
- 创建：`/home/liangjiahua/FastGS/scripts/tests/test_reconstruct_images.py`

**接口：**

- 输入：`--job-dir PATH --fastgs-dir PATH --conda-env NAME --iterations INT --timeout-seconds INT`
- 输入目录：`<job-dir>/input/*.jpg` 或 `*.jpeg`
- 输出：`<job-dir>/model/point_cloud/iteration_<iterations>/point_cloud.ply`
- 结果：`<job-dir>/result.json`，包含 `job_id`、状态、阶段、PLY 路径、大小、SHA256、退出码和耗时。

- [ ] **步骤 1：先写输入校验和结果校验测试**

测试至少覆盖：不存在 `input/`、少于 3 张图片、成功输出 PLY、零字节 PLY、结果文件不包含密码。

- [ ] **步骤 2：运行测试确认失败**

运行：

```bash
cd /home/liangjiahua/FastGS
python -m pytest scripts/tests/test_reconstruct_images.py -q
```

预期：因为脚本尚未创建而失败。

- [ ] **步骤 3：实现最小脚本**

实现 `validate_input_dir()`、`build_commands()`、`sha256_file()`、`write_result()` 和 `main()`。使用 `subprocess.Popen` 分别运行：

```bash
python convert.py --source_path <job-dir> --sequential --camera OPENCV
python train.py -s <job-dir> -m <job-dir>/model --images images \
  --iterations <N> --save_iterations <N> --checkpoint_iterations <N>
```

在 `fastgs` 环境中运行，分别写入 `stdout.log` 和 `stderr.log`，超时终止子进程并返回非零退出码。

- [ ] **步骤 4：运行测试确认通过**

运行同一 pytest 命令，预期所有脚本单元测试通过。

- [ ] **步骤 5：提交 200 端脚本**

```bash
git add scripts/reconstruct_images.py scripts/tests/test_reconstruct_images.py
git commit -m "feat: add image-only FastGS reconstruction worker"
```

### 任务 2：130 远程执行器和分阶段日志

**文件：**

- 修改：`backend/requirements.txt`
- 创建：`backend/app/services/remote_reconstruction.py`
- 创建：`backend/tests/test_remote_reconstruction.py`
- 修改：`backend/.env.example`

**接口：**

```python
class RemoteReconstructionService:
    async def reconstruct(
        self,
        session_id: UUID,
        space_id: UUID,
        frame_paths: list[str],
        blob_store: BlobStore,
    ) -> ReconstructionArtifact:
        ...
```

`ReconstructionArtifact` 至少包含 `model_url`、`model_format`、`size_bytes`、`sha256` 和 `job_id`。

- [ ] **步骤 1：先写假的 SSH/SFTP 和 BlobStore 测试**

覆盖：顺序上传图片、重建命令参数、下载 PLY、BlobStore key、密码不进入命令和日志、异常时清理临时目录。

- [ ] **步骤 2：运行测试确认失败**

```bash
cd /Users/saas/GitHub/echo/backend
pytest tests/test_remote_reconstruction.py -q
```

预期：导入服务失败。

- [ ] **步骤 3：添加依赖和环境配置**

在 `requirements.txt` 添加 `paramiko`；在 `.env.example` 添加：

```text
FASTGS_SSH_HOST=192.168.0.200
FASTGS_SSH_PORT=22
FASTGS_SSH_USER=liangjiahua
FASTGS_SSH_PASSWORD=
FASTGS_REMOTE_PROJECT=/home/liangjiahua/FastGS
FASTGS_REMOTE_ENV=fastgs
FASTGS_REMOTE_WORK_ROOT=/tmp/echo-fastgs
FASTGS_TRAIN_ITERATIONS=30000
FASTGS_TRAIN_TIMEOUT_SECONDS=1800
```

- [ ] **步骤 4：实现远程执行器**

使用 `tempfile.TemporaryDirectory` 创建本地 staging；以 `frame_000000.jpg` 形式复制图片；使用 Paramiko SFTP 上传；通过 SSH 执行 200 端 worker；下载并校验 PLY；保存 `spaces/{space_id}/models/point_cloud.ply`；所有阶段记录 `job_id`；在 `finally` 中清理远程目录。

- [ ] **步骤 5：运行测试确认通过**

```bash
pytest tests/test_remote_reconstruction.py -q
```

- [ ] **步骤 6：提交 130 远程执行器**

```bash
git add backend/requirements.txt backend/.env.example backend/app/services/remote_reconstruction.py backend/tests/test_remote_reconstruction.py
git commit -m "feat: add remote FastGS reconstruction executor"
```

### 任务 3：空间会话异步接入和状态更新

**文件：**

- 修改：`backend/app/services/ingest_pipeline.py`
- 修改：`backend/app/api/routes.py`
- 修改：`backend/app/repositories/memory_repo.py`
- 创建：`backend/tests/test_async_space_reconstruction.py`

**接口：**

- `complete_session()` 对空间会话创建 `processing` 状态的 `SpaceMemory` 后立即返回。
- 后台函数 `run_space_reconstruction(memory_id, session_id, frame_paths)` 成功时写入 PLY URL，失败时写入 `failed`。

- [ ] **步骤 1：先写异步行为测试**

测试完成接口返回 `processing`，后台成功将状态改为 `completed` 并写入 `model_url`，后台失败将状态改为 `failed` 且 `model_url` 为空；重复完成请求不启动第二个任务。

- [ ] **步骤 2：运行测试确认失败**

```bash
cd /Users/saas/GitHub/echo/backend
pytest tests/test_async_space_reconstruction.py -q
```

- [ ] **步骤 3：实现异步接入**

使用 FastAPI `BackgroundTasks` 或现有应用生命周期任务机制调度任务；在任务开始、阶段变化、成功和失败时更新日志和空间记录；继续计算 IMU 回环结果，但不将其作为启动条件。

- [ ] **步骤 4：运行测试确认通过**

```bash
pytest tests/test_async_space_reconstruction.py tests/test_spatial.py -q
```

- [ ] **步骤 5：提交会话接入**

```bash
git add backend/app/services/ingest_pipeline.py backend/app/api/routes.py backend/app/repositories/memory_repo.py backend/tests/test_async_space_reconstruction.py
git commit -m "feat: start async FastGS reconstruction after space capture"
```

### 任务 4：PLY API 和手机端处理状态

**文件：**

- 修改：`backend/app/schemas/__init__.py`（仅在现有响应字段不足时）
- 修改：`phone/app/src/main/java/com/echo/phone/ui/space/SpaceDetailScreen.kt`
- 修改：`phone/app/src/main/java/com/echo/phone/data/EchoRepository.kt`（仅在需要轮询时）
- 创建或修改：对应 Kotlin 单元测试/Android 测试文件

- [ ] **步骤 1：先写状态映射测试**

覆盖 `processing` 不加载 PLY、`completed + model_url` 加载 PLY、`failed` 显示失败状态。

- [ ] **步骤 2：运行测试确认失败**

使用项目现有 Android 测试命令，预期新状态行为尚未实现而失败。

- [ ] **步骤 3：实现最小客户端状态处理**

复用现有 `model_url`、`model_format` 和 PLY WebView。增加有限轮询或页面刷新入口，避免无限后台轮询；状态错误只显示用户提示，不显示 SSH 命令和内部路径。

- [ ] **步骤 4：运行后端和 Android 回归测试**

```bash
cd /Users/saas/GitHub/echo/backend
pytest -q
cd /Users/saas/GitHub/echo/phone
./gradlew test
```

- [ ] **步骤 5：提交手机端适配**

```bash
git add phone/app/src/main/java backend/app/schemas
git commit -m "feat: show async FastGS reconstruction state"
```

### 任务 5：huiyi 端到端验收

**文件和目录：**

- 130 测试数据目录：`/Users/saas/GitHub/echo/backend/data/fastgs-e2e/huiyi/images`
- 200 测试任务目录：`/tmp/echo-fastgs/<job_id>`
- 130 结果 BlobStore：`spaces/{space_id}/models/point_cloud.ply`

- [ ] **步骤 1：从 200 拉取测试图片到 130**

```bash
scp -r liangjiahua@192.168.0.200:/home/liangjiahua/FastGS/datasets/huiyi/images \
  /Users/saas/GitHub/echo/backend/data/fastgs-e2e/huiyi/
```

校验 250 张图片、约 41 MB 和 SHA256 清单。

- [ ] **步骤 2：执行 130 到 200 的真实传输**

通过 `RemoteReconstructionService` 上传 130 测试目录，确认 200 端任务目录只包含本次 `job_id` 的输入图片和日志。

- [ ] **步骤 3：执行 COLMAP 和 FastGS**

检查 `stdout.log`、`stderr.log`、`job.json`、`result.json`、`sparse/0` 和最终 `point_cloud.ply`。训练迭代次数先使用环境变量配置值；若 GPU 时间过长，使用明确的测试迭代值重新执行，不修改正式默认值。

- [ ] **步骤 4：回传并发布 PLY**

下载 PLY 到 130，比较远程和本地 SHA256，保存到 BlobStore，使用 `/api/v1/media/...` 请求验证可访问。

- [ ] **步骤 5：手机端渲染**

通过空间详情接口读取 `status=completed`、`model_format=ply` 和 `model_url`，在手机端现有 PLY 查看器中加载，确认非空画面和基本交互。

- [ ] **步骤 6：保存验收记录**

保存 `job_id`、各阶段耗时、输入图片数量、PLY 大小、远程/本地 SHA256、最终 API URL 和截图或日志摘要。不得保存 SSH 密码。

---

## 计划自检

- 设计中的 200 纯图片脚本对应任务 1。
- 130 SSH/SFTP、PLY 回传和日志对应任务 2。
- 异步会话状态和失败处理对应任务 3。
- 手机端 `processing/completed/failed` 和 PLY 渲染对应任务 4。
- `huiyi` 从 200 拉到 130、再从 130 传回 200、PLY 回传 130 和手机渲染对应任务 5。
- 未引入 IMU 初始化、回环门槛、自动停止采集或生产级任务队列。
- 未使用 TBD、TODO 或“后续补充”等未执行占位描述。
