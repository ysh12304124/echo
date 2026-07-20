# 空间记忆 — 后台需要实现的功能与接口

**日期**: 2026-07-13

## 1. 现有已可用接口

以下接口已在手机端使用，无需改动：

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/ingest/sessions` | 创建录制会话 (TIME/SPACE) |
| POST | `/ingest/sessions/{id}/frames` | 上传照片帧 |
| POST | `/ingest/sessions/{id}/audio` | 上传音频（仅 TIME） |
| POST | `/ingest/sessions/{id}/imu` | 上传 IMU 批数据 |
| POST | `/ingest/sessions/{id}/complete` | 结束会话，触发后台处理 |
| GET | `/spaces` | 列出空间记忆 |
| GET | `/spaces/{id}` | 获取空间记忆详情 |

## 2. 需要新增的后台功能

### 2.1 IMU 数据接收与存储

**手机已实现**：手机端已在 space 录制时收集 IMU，每 25 条（~500ms）批上传。

**请求格式**：
```
POST /ingest/sessions/{sessionId}/imu
Content-Type: application/json

{
  "samples": [
    {"ax": 0.12, "ay": 9.81, "az": 0.05, "gx": 0.01, "gy": -0.02, "gz": 0.0, "timestamp_ms": 1750845600001},
    ...
  ]
}
```

**后台需实现**：
- 接收并存储 IMU 样本到数据库或文件
- IMU 数据量：50 条/秒 × session 时长（如 60 秒 = 3000 条）
- 建议按 session 存为 JSON Lines 文件或独立表

### 2.2 回环检测接口

**说明**：用户自行实现回环检测逻辑（基于 IMU 或照片特征），检测完成后需通知手机端。

**建议接口**：

```
POST /ingest/sessions/{sessionId}/loop-detect
后台分析 IMU 数据 → 判断是否完成回环
返回: {"loop_complete": true, "angle_degrees": 350, "confidence": 0.95}
```

**手机端用法**：手机在录制期间定期轮询此接口，或后台主动推送结果。

### 2.3 3DGS 重建触发

**说明**：session complete 后，后台需触发 3DGS 重建流程。

**处理流程**：
1. session complete → 状态变为 `processing`
2. 收集该 session 的所有照片帧
3. 运行 COLMAP (SfM) → 稀疏点云 + 相机位姿
4. 运行 3DGS 训练 → 高斯点云 (`.ply` 或 `.splat`)
5. 转换为 Web 可渲染格式（可选压缩）
6. 状态变为 `completed`，`model_url` 指向生成文件

**生成产物**：
- `splat.ply` 或 `point_cloud.splat` — 点云/高斯文件
- `sparse/` — COLMAP 稀疏重建结果
- `model_url` 指向可通过 HTTP 访问的文件

### 2.4 照片质量标记

**说明**：手机端已做实时质量检测（模糊/暗光/过快），在 frame 上传时可在 metadata 中附带质量标记，供后台筛选高质量帧用于 3DGS。

**扩展方案**（非 MVP）：
- frame 上传时增加可选字段 `quality_score`
- 后台在 3DGS 处理时可过滤低质量帧

### 2.5 scene_summary 生成

**复用现有时间记忆的 VLM 场景分析**：
- 选取关键帧 + 照片序列
- 调用 VLM 生成 `identify_brief` 和 `scene_summary`
- 存入 `space_memories` 表

## 3. 数据库扩展建议

```sql
-- IMU 数据表
CREATE TABLE imu_samples (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    ax REAL, ay REAL, az REAL,    -- 加速度 m/s^2
    gx REAL, gy REAL, gz REAL,    -- 陀螺仪 rad/s
    timestamp_ms INTEGER NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_imu_session ON imu_samples(session_id);
CREATE INDEX idx_imu_session_ts ON imu_samples(session_id, timestamp_ms);

-- 空间记忆扩展字段
ALTER TABLE space_memories ADD COLUMN space_type TEXT;    -- 'single_object' | 'large_scene'
ALTER TABLE space_memories ADD COLUMN scene_summary TEXT; -- VLM 生成的场景描述
ALTER TABLE space_memories ADD COLUMN model_format TEXT;  -- 'ply' | 'splat' | 'glb'
ALTER TABLE space_memories ADD COLUMN loop_angle REAL;    -- 回环角度（度）
```

## 4. Space Session 生命周期

```
[手机] createSession(SPACE) → status=recording
       ├── uploadFrame × N
       ├── uploadImuBatch × M
       └── completeSession → status=processing
                                ↓
[后台]                     COLMAP → 3DGS → model_url
                                ↓
                           status=completed
                           identify_brief 生成
                                ↓
[手机] GET /spaces → 展示卡片
       GET /spaces/{id} → 详情 + 3D 查看器
```
