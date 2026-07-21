# 130 上最新代码架构 vs 缺失功能报告

日期：2026-07-20
项目：Echo 空间记忆系统

## 一、架构变化

新增了独立的 **`compute/` 微服务**（与 backend 同机部署，共享磁盘，localhost HTTP 通信）：

```
用户完成录制
  → backend /ingest/sessions/{id}/complete
  → 立即创建 SpaceMemory(status=PROCESSING) 返回
  → compute_client.submit_space(job)  ← HTTP POST 到 compute
     → compute /analyze/space (202 立即返回)
     → BackgroundTask 异步跑 run_space_analysis()
     → 完成后 POST /internal/callback/space
  → apply_space_result() 落库
```

旧的 `backend/services/remote_reconstruction.py`（SSH 到 200 跑 FastGS）**已删除**。

## 二、完整数据流的断点

### 眼镜端
- 只上报 `space_state=on/off`（双指双击开关）
- **缺**：large / object 场景类型的选择和上报

### 手机 → Backend session 创建
- `CreateSessionRequest` 只有 `memory_type / scene / partition / title`
- **缺**：`scene_type` 参数
- `IngestPipeline.create_session` 和 `_complete_space_session_store_only` 创建 `SpaceMemory` 时也没写 scene_type

### Backend → Compute 提交
- `SpaceAnalyzeJob` 只带 `video_path / imu_path`
- HTTP `inputs` 只传 `{"video_path": ..., "imu_path": ...}`
- **缺**：`scene_type`、`recording_duration_sec`

### Compute 处理（**核心问题**）

`compute/app/analyze/space_memory.py` 是**完全的桩**：

```python
# TODO(阶段四): 接入抽帧 + IMU 重建/点云的真实模型链路
result = {
    "model_url": None,      # 全是占位
    "quality": "good",
    "anchors": [],
    ...
}
```

- **完全不做 3DGS**
- 没有 COLMAP、没有训练、没有 poses/anchor 生成

### Compute → Backend 回调落库

`apply_space_result()` 只更新 6 个字段：

```
status, quality, model_url, model_format, loop_angle, scene_summary, identify_brief
```

**完全不读也不写**：
- `poses_url`, `anchor_url`, `anchor_method`, `pose_count`
- `anchor_position_x/y/z`
- `scene_type`
- `recording_duration_sec`

## 三、已就绪但空转的部分

- ✅ 数据库列：`poses_url / anchor_url / anchor_method / pose_count / anchor_position_x/y/z / scene_type / recording_duration_sec` 都存在
- ✅ Schema `SpaceMemoryDetailResponse`：字段完整
- ✅ 手机 `SpaceMemoryDetail` 模型 + `EchoApi` DTO：完整
- ✅ 手机 `SpaceDetailScreen`：下载 poses.txt、拟合圆、算速度都在
- ✅ 手机 `PointCloudViewer`：三种模式（path/orbit/free）代码完整
- ❌ **只是永远拿到 null，因为后端从不填这些字段**

## 四、需要补齐的清单（按依赖顺序）

| # | 位置 | 补什么 |
|---|------|--------|
| 1 | `backend/domain/enums.py` | 定义 `SpaceSceneType`（LARGE, OBJECT）或字符串常量约定 |
| 2 | `glasses/MainActivity.kt` | 场景选择加 large/object 选项；开始录制时上报类型 |
| 3 | `phone/CxrGlassesConnection` | 解析眼镜上报的场景类型 |
| 4 | `phone/EchoRepository.startSession` + `CreateSessionRequest` | 加 `scene_type` 参数 |
| 5 | `backend/IngestSession` + `create_session` | 存储 `scene_type` |
| 6 | `backend/_complete_space_session_store_only` + `SpaceMemory(...)` | 把 scene_type 写入 SpaceMemory |
| 7 | `backend/SpaceAnalyzeJob` + `submit_space` | HTTP inputs 加 `scene_type`, `recording_duration_sec` |
| 8 | **`compute/analyze/space_memory.py`** | 替换桩为真实链路（COLMAP + FastGS train + poses.txt + anchor.json + 拷贝到 blob） |
| 9 | Compute 返回 result | 加 `poses_url, anchor_url, anchor_method, pose_count, anchor_position, scene_type, recording_duration_sec` |
| 10 | `backend/apply_space_result` | 读上述字段调 `update_space_memory` 传入 |

## 五、推荐推进顺序

1. **#8 → #9 → #10**：先把 3DGS 真实实现装回来，让 poses/anchor 落到数据库
2. **#1 → #4 → #5 → #6 → #7**：打通 scene_type 链路
3. **#2 → #3**：眼镜端 UI 收尾

眼镜端场景选择可以先在手机侧手动选（进入录制前选大场景/单物体），最后再补眼镜 UI。

## 六、关键文件路径参考（130 上）

- Backend：
  - `/Users/saas/GitHub/echo/backend/app/api/routes.py`
  - `/Users/saas/GitHub/echo/backend/app/services/ingest_pipeline.py`
  - `/Users/saas/GitHub/echo/backend/app/services/compute_client.py`
  - `/Users/saas/GitHub/echo/backend/app/schemas/__init__.py`
  - `/Users/saas/GitHub/echo/backend/app/domain/models.py`
  - `/Users/saas/GitHub/echo/backend/app/domain/enums.py`
- Compute（新增微服务）：
  - `/Users/saas/GitHub/echo/compute/app/main.py`
  - `/Users/saas/GitHub/echo/compute/app/analyze/space_memory.py`（**桩**）
  - `/Users/saas/GitHub/echo/compute/app/callback.py`
- Phone：
  - `/Users/saas/GitHub/echo/phone/app/src/main/java/com/echo/phone/ui/common/PointCloudViewer.kt`
  - `/Users/saas/GitHub/echo/phone/app/src/main/java/com/echo/phone/ui/space/SpaceDetailScreen.kt`
  - `/Users/saas/GitHub/echo/phone/app/src/main/java/com/echo/phone/data/EchoRepository.kt`
  - `/Users/saas/GitHub/echo/phone/app/src/main/java/com/echo/phone/data/api/EchoApi.kt`
  - `/Users/saas/GitHub/echo/phone/app/src/main/java/com/echo/phone/domain/Models.kt`
- Glasses：
  - `/Users/saas/GitHub/echo/glasses/app/src/main/java/com/echo/glasses/MainActivity.kt`
  - `/Users/saas/GitHub/echo/glasses/app/src/main/java/com/echo/glasses/VideoRecorder.kt`
- 3DGS pipeline（在 200 上）：
  - `/home/liangjiahua/FastGS/scripts/reconstruct_images.py`
