# 远程 FastGS 三维重建设计

**日期：** 2026-07-14

## 目标

用户完成空间采集后，130 主机上的 Echo 后端异步将已保存的全部 JPEG 图片发送到 200 主机。200 主机使用 COLMAP 和 FastGS 重建高斯点云，将最终 PLY 文件回传到 130，并通过接口提供给手机端渲染。

## 范围

本次改动覆盖完整的 MVP 重建链路：

1. 200 主机新增一个只接收图片目录的重建脚本。
2. 脚本执行 COLMAP 位姿估计和 FastGS 训练。
3. 130 主机在空间会话完成后启动重建任务。
4. 后端上传会话图片、等待重建、下载 PLY，并保存到本地 BlobStore。
5. 现有空间接口提供 PLY 地址，手机端通过现有模型查看器加载。

在正式接入 130 的真实采集数据前，使用 200 主机已有的测试数据集 `/home/liangjiahua/FastGS/datasets/huiyi/images` 做端到端验收。测试数据先复制到 130，随后严格按照“130 图片目录 -> 200 重建 -> PLY 回传 130 -> 手机端渲染”的路径执行，避免直接从 200 本地读取图片而绕过网络传输链路。

MVP 不使用 IMU 位姿初始化 COLMAP，不要求回环检测成功后才能重建，也不引入任务队列服务或分布式任务数据库。

## 系统架构

### 200 主机：图片重建脚本

新增文件：`FastGS/scripts/reconstruct_images.py`。

脚本接收一个任务目录，目录中包含 `input/` 和 JPEG 图片，训练模型输出到该任务目录下。

脚本流程：

1. 校验 `input/` 目录存在，并且至少包含 3 张 `.jpg` 或 `.jpeg` 图片。
2. 执行 `convert.py --source_path <job_dir> --sequential --camera OPENCV`，由 COLMAP 估计位姿并生成 `sparse/0`。
3. 在 `fastgs` conda 环境中执行 `train.py -s <job_dir> -m <job_dir>/model --images images --iterations <N> --save_iterations <N> --checkpoint_iterations <N>`。
4. 校验 `<job_dir>/model/point_cloud/iteration_<N>/point_cloud.ply` 存在且文件大小大于 0。
5. 输出包含迭代次数和 PLY 路径的机器可解析成功结果。发生错误时记录日志并返回非零退出码。

脚本不会修改 FastGS 源码或原始数据集。每个任务使用独立目录，避免并发任务共享 COLMAP 数据库或模型输出目录。

### 130 主机：远程重建执行器

新增后端服务，负责执行一次完整的远程重建任务：

1. 从现有 Repository 读取会话图片路径。
2. 创建唯一的本地临时目录，并将会话 JPEG 图片复制到 `input/`，使用稳定的连续文件名。
3. 在 200 主机配置的 FastGS 临时根目录下创建唯一的远程任务目录。
4. 通过 SSH/SFTP 将本地 `input/` 目录传输到 200 主机。
5. 使用配置的 FastGS 项目路径、conda 环境和训练迭代次数调用重建脚本。
6. 将校验通过的 PLY 下载到本地临时目录。
7. 通过现有 `BlobStore` 保存到 `spaces/{space_id}/models/point_cloud.ply`。
8. 返回生成的媒体 URL 和模型格式。
9. 在 `finally` 中清理本地和远程临时文件，同时保留包含任务上下文的结构化错误日志。

SSH 配置通过环境变量提供，代码中不设置密码默认值：

```text
FASTGS_SSH_HOST
FASTGS_SSH_PORT=22
FASTGS_SSH_USER
FASTGS_SSH_PASSWORD
FASTGS_REMOTE_PROJECT=/home/liangjiahua/FastGS
FASTGS_REMOTE_ENV=fastgs
FASTGS_REMOTE_WORK_ROOT=/tmp/echo-fastgs
FASTGS_TRAIN_ITERATIONS=30000
FASTGS_TRAIN_TIMEOUT_SECONDS
```

执行器使用 Python SSH/SFTP 客户端，因此密码不会被拼接到 shell 命令中。密码只在运行时从环境变量读取，绝不写入日志。

### 会话生命周期

空间会话调用 `complete_session` 时，先创建状态为 `processing` 的 `SpaceMemory`，不等待 FastGS 完成，随后立即返回。后台任务再执行远程重建。

```text
POST /ingest/sessions/{id}/complete
  -> 创建 SpaceMemory(status=processing)
  -> 返回会话摘要
  -> 启动后台重建任务
       -> 上传图片到 200
       -> 执行 COLMAP 转换
       -> 执行 FastGS 训练
       -> 下载 PLY 到 130
       -> 保存 model_url
       -> status=completed
```

任意步骤失败时，将空间记忆更新为 `failed`，保持模型 URL 为空，并记录包含 session 和 space 标识的错误日志。回环检测仍然会计算并保存为元数据，但结果不影响是否启动重建。

实现必须避免同一个会话因重复调用完成接口而启动重复任务。MVP 使用会话到空间记忆的关联关系和进程内任务锁进行保护。后续版本可以替换为持久化任务队列。

### 分阶段日志和任务产物

异步重建必须按阶段记录日志，便于定位任务停留在图片准备、传输、COLMAP、FastGS 训练、结果回传还是本地保存阶段。每个任务生成唯一的 `job_id`，所有 130 和 200 两端日志都必须携带以下关联字段：

```text
job_id
session_id
space_id
stage
status
```

阶段固定为：

```text
created
staging
uploading
colmap
training
downloading
storing
completed
failed
```

每个阶段至少记录开始时间、结束时间、耗时和结果。任务级别还需要记录：

- 图片数量、图片总字节数和实际上传数量。
- 200 主机地址、远程任务目录和 FastGS 项目路径。
- FastGS conda 环境、训练迭代次数和超时时间。
- COLMAP 和 FastGS 的退出码。
- 最终 PLY 的文件大小、SHA256 和保存后的 BlobStore key。
- 错误类型、失败阶段、退出码和脱敏后的错误摘要。

200 主机每个任务目录保存以下调试产物：

```text
<remote_job_dir>/
├── input/
├── stdout.log
├── stderr.log
├── job.json
└── result.json
```

其中：

- `job.json` 保存任务参数、输入图片数量、开始时间和版本信息。
- `stdout.log` 保存 COLMAP、训练脚本及包装脚本的标准输出。
- `stderr.log` 保存标准错误输出。
- `result.json` 只在任务结束时生成，包含成功或失败状态、PLY 路径、文件大小、SHA256、退出码和耗时。

130 主机记录同一 `job_id` 对应的远程执行、下载和 BlobStore 保存过程。数据库中至少保存当前阶段、任务状态、开始时间、结束时间、错误摘要和最终模型信息；文件日志保存完整调试细节。手机端只读取状态和面向用户的错误提示，不直接暴露内部命令或主机路径。

日志和任务产物必须满足以下安全约束：

- 不记录 SSH 密码、完整认证信息或包含密码的命令行。
- 不记录图片内容，只记录文件名、数量、大小和校验值。
- 对远程路径、命令参数和异常信息进行脱敏，避免泄露本机目录或凭据。
- 任务清理前先确保 `result.json` 和必要错误日志已写入；成功任务可以按保留策略清理原始图片，失败任务至少保留错误日志和结果摘要。

## API 和客户端行为

继续使用现有空间响应字段作为客户端契约：

- `status=processing`：显示正在重建，不尝试加载模型。
- `status=completed` 且 `model_url` 不为空：使用现有 PLY 查看器加载模型。
- `status=failed`：显示重建失败，并允许用户重新录制。
- `model_format=ply`：标识渲染器使用的模型格式。

MVP 不新增手机端传输协议。手机端轮询或刷新现有空间详情接口，状态变化后使用已有的绝对媒体 URL 处理逻辑。

## 失败处理

- 图片少于 3 张：在远程传输前失败，并返回明确的校验错误。
- 图片缺失或不是有效 JPEG：拒绝任务，并将空间状态设为 `failed`。
- SSH/SFTP 连接失败：将状态设为 `failed`，日志记录主机、用户和任务信息，但不记录凭据。
- COLMAP 失败：在日志中保留工作进程退出码和标准错误输出。
- FastGS 超时：终止重建进程，将状态设为 `failed`，并清理远程任务目录。
- PLY 缺失或文件大小为 0：视为失败，不发布模型 URL。
- BlobStore 保存失败：将状态设为 `failed`，不报告重建完成。
- 日志或 `result.json` 写入失败：不能覆盖原始重建结果，但必须将任务标记为 `failed` 或 `diagnostic_incomplete`，并记录可用的进程错误信息。

## 测试范围

测试使用假的 SSH 和 BlobStore 边界，不依赖真实 GPU 或网络：

- 重建脚本的命令构造、输入校验、输出校验和非零失败行为。
- 远程执行器是否上传预期的连续图片、调用重建脚本、下载 PLY 并清理临时目录。
- 远程执行器不会将密码放入命令参数或日志。
- 空间会话完成后立即返回 `processing`，并且只调度一个任务。
- 后台任务成功后写入 `model_url`、`model_format=ply`，并将状态设为 `completed`。
- 后台任务失败后将状态设为 `failed`，并保持 `model_url` 为空。
- 每个阶段都会生成带有 `job_id` 的结构化日志，并且成功、失败任务都能读取到 `result.json` 或等价的失败摘要。
- 日志不会包含 SSH 密码、图片内容或未经脱敏的敏感命令参数。
- 现有 API 响应和手机端模型 URL 映射保持兼容。

### huiyi 端到端验收

验收使用 250 张、约 41 MB 的 `huiyi` JPEG 图片，验收步骤固定为：

1. 从 200 主机复制 `/home/liangjiahua/FastGS/datasets/huiyi/images` 到 130 的测试目录。
2. 在 130 上校验图片数量、文件大小和 SHA256 清单。
3. 以 130 测试目录作为输入，通过 SSH/SFTP 上传到 200 的唯一远程任务目录。
4. 在 200 上执行 `reconstruct_images.py`，检查 COLMAP 输出、FastGS 训练日志和最终 `point_cloud.ply`。
5. 将 PLY 下载回 130，校验文件非空且 SHA256 与远程结果一致。
6. 保存到 130 的 BlobStore，确认 `/api/v1/media/...` 可以访问。
7. 通过手机端现有空间详情和 PLY 查看器加载该模型，确认模型 URL、格式和渲染结果均正确。

每一步都必须记录 `job_id`、阶段状态、耗时、输入/输出文件大小和校验值；任一步失败都停止后续步骤，并保留对应日志和 `result.json`。

## 非目标

- 不自动停止图像采集。
- 不将 IMU 位姿注入 COLMAP。
- 不要求检测到回环后才能重建。
- 不转换为 GLB，也不实现移动端专用的高斯压缩。
- 不实现生产级持久化任务队列、重试策略或多 worker 调度器。
