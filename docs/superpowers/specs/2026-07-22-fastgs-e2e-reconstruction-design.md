# FastGS 手机采集到渲染设计

## 目标

打通手机/眼镜采集视频和 IMU、153 机异步重建、结果回调和手机端渲染的单一链路。现有 `POST /api/v1/ingest/sessions/{session_id}/complete` 是唯一启动点。

## 数据流

1. 手机把视频分片、IMU JSONL 上传到 backend 的共享 BlobStore。
2. `complete` 创建 `SpaceMemory(status=processing)`，提交包含视频路径、IMU 路径、会话开始时间和场景类型的空间任务。
3. compute 在后台线程创建独立 job 目录，按固定 FPS 抽取 JPEG。
4. 按 `session.created_at + frame_index / fps` 计算帧时间，从 IMU JSONL 选择最近的加速度样本，生成 FastGS v1 `imu_manifest.json`。
5. FastGS pipeline 依次执行 COLMAP、gravity alignment、训练和导出，写出 PLY、poses.txt、anchor.json、result.json。
6. compute 校验产物并复制到 `backend/data/blobs/spaces/{memory_id}/models/`，回调 backend。
7. backend 更新空间状态和产物 URL；手机已有轮询和 PointCloudViewer 使用这些字段渲染。

## 坐标和时间约定

- manifest 的 `acceleration_frame` 固定为 `camera`，`acceleration_type` 默认 `gravity`。
- IMU 样本使用 `timestamp_ms`；帧时间由会话开始时间和抽帧 FPS 推导。
- 合成测试生成与 COLMAP 位姿一致的相机坐标系重力，真实设备若传感器坐标轴不同，需要在采集侧或配置中完成传感器到相机坐标转换。
- 没有足够有效 IMU 时允许回退到 `colmap_world`，但结果中明确记录 `alignment_method` 和有效样本数量。

## 组件边界

- `compute/app/analyze/imu_manifest.py` 只负责 JSONL 校验、最近时间样本匹配和 manifest 写入。
- `compute/app/analyze/space_memory.py` 只负责任务目录、视频抽帧、FastGS 调度、产物复制和回调。
- backend 只负责任务提交、状态和数据库字段，不直接执行 GPU 进程。
- phone 只负责补齐 `scene_type` 请求字段和已有状态/模型展示，不处理重建逻辑。

## 失败语义

- 视频不存在、帧数少于 3、COLMAP/FastGS 非零退出、产物缺失或回调输入无效都会回调 `failed`。
- 每个 job 保留 stdout、stderr、events、stage status 和 result.json；临时任务目录不覆盖其他 job。
- PLY、poses.txt、anchor.json 均在发布前检查存在且非空；PLY 记录 SHA256。

## 验证

- 单元测试覆盖 IMU 时间匹配、无效样本过滤、manifest 格式、任务输入和产物回调字段。
- huiyi 验收分两段：先运行 COLMAP，再根据 COLMAP 位姿生成合成 IMU manifest，最后从 alignment 阶段继续跑 FastGS/export，验证三个文件和回调数据。
- 真实服务验收确认 backend 8000、compute 8100、`complete` 后状态流转和手机端读取 URL。
