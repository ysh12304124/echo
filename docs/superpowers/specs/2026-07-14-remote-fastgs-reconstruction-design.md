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

## 测试范围

测试使用假的 SSH 和 BlobStore 边界，不依赖真实 GPU 或网络：

- 重建脚本的命令构造、输入校验、输出校验和非零失败行为。
- 远程执行器是否上传预期的连续图片、调用重建脚本、下载 PLY 并清理临时目录。
- 远程执行器不会将密码放入命令参数或日志。
- 空间会话完成后立即返回 `processing`，并且只调度一个任务。
- 后台任务成功后写入 `model_url`、`model_format=ply`，并将状态设为 `completed`。
- 后台任务失败后将状态设为 `failed`，并保持 `model_url` 为空。
- 现有 API 响应和手机端模型 URL 映射保持兼容。

## 非目标

- 不自动停止图像采集。
- 不将 IMU 位姿注入 COLMAP。
- 不要求检测到回环后才能重建。
- 不转换为 GLB，也不实现移动端专用的高斯压缩。
- 不实现生产级持久化任务队列、重试策略或多 worker 调度器。
