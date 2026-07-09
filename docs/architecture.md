# Echo 架构说明

## 总体架构

```
┌─────────────┐   Rokid CXR-S/CXR-L   ┌─────────────┐    REST/OpenAPI    ┌─────────────┐
│  眼镜端 App  │ ◄──状态/按键 rk_*───► │  手机端 App  │ ─────────────────► │  后台服务    │
│  (glasses/) │   ◄音频PCM+拍照JPEG(固件经CXR-L)  │  (phone/)   │   上传 + 查询       │  (backend/) │
└─────────────┘                     └─────────────┘                    └──────┬──────┘
                                                                              │
                                                                     ┌────────▼────────┐
                                                                     │ Provider 适配层  │
                                                                     │ ASR/Vision/OCR  │
                                                                     │ LLM/Embedding   │
                                                                     └────────┬────────┘
                                                                              │
                                                                     ┌────────▼────────┐
                                                                     │ SQLite + Blob   │
                                                                     │ + 向量检索       │
                                                                     └─────────────────┘
```

## 分层原则

### 后台 (`backend/app/`)

| 层         | 目录              | 职责                         |
| ---------- | ----------------- | ---------------------------- |
| API        | `api/`          | HTTP 路由，请求/响应校验     |
| Service    | `services/`     | 业务编排（摄入、查询、人物） |
| Domain     | `domain/`       | 领域模型与枚举               |
| Provider   | `providers/`    | 可插拔 AI/存储接口 + Mock    |
| Repository | `repositories/` | 持久化与检索                 |

### 手机端 (`phone/app/src/main/java/com/echo/phone/`)

| 层     | 目录        | 职责                                                                                    |
| ------ | ----------- | --------------------------------------------------------------------------------------- |
| UI     | `ui/`     | Compose 界面 + ViewModel                                                                |
| Domain | `domain/` | 业务模型                                                                                |
| Data   | `data/`   | API 客户端、眼镜连接（`glasses/`：接口+Mock；`glasses/cxr/`：CXR-L 实现）、本地缓存 |

眼镜连接经 `GlassesConnection` 抽象：`MockGlassesConnection`（离线合成）与 `CxrGlassesConnection`
（Rokid CXR-L：鉴权/会话/音频/拍照/按键），由 `USE_MOCK_GLASSES` 切换。

### 眼镜端 (`glasses/app/src/main/java/com/echo/glasses/`)

轻量 CXR-S CustomApp，不采集媒体（采集由眼镜固件经 CXR-L 送手机）。

| 目录/文件                   | 职责                                                             |
| --------------------------- | ---------------------------------------------------------------- |
| `MainActivity.kt`         | 初始化`CXRServiceBridge`、订阅手机状态、显示镜片状态、上报按键 |
| `receiver/KeyReceiver.kt` | 眼镜系统按键广播 → 归一`KeyType` 上报                         |

## 核心领域对象

- **TimeMemory**: 时间记忆（Meeting / Onsite / QualityTime 场景）
- **SpaceMemory**: 空间记忆（质量评级、锚点、3D 模型）
- **Event**: 关键瞬间（系统内部索引，用户不直接管理）
- **Evidence**: 证据（视觉 / 音频转写 / OCR / 空间 / 用户备注）
- **Entity**: 实体（人物 / 项目 / 设备）
- **Binding**: 时空绑定（记忆级 / 瞬间级 / 证据级）
- **DataPartition**: 数据分区（work / quality_time）

## 查询三态

1. **确定答案** — 高置信证据支撑，返回答案 + 证据 + 来源
2. **可能相关证据** — 高置信未命中，低置信候选降级展示
3. **没有找到** — 无可用证据，不猜测

## 产品硬规则（代码必须遵守）

- 手动开启，不被动记录
- 查询必须有证据，无证据不回答
- Quality Time 数据独立分区，不参与全局工作查询
- 首页只做识别，导航型摘要在记忆详情二级页
- 底部 Tab 仅：首页、查询、我的
- 低置信内容不主动打扰，仅查询降级召回
