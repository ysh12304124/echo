# Rokid CXR 集成协议（眼镜 ↔ 手机）

Echo 眼镜链路基于 Rokid **CXR-L（手机端）/ CXR-S（眼镜端）** SDK。手机端为链路主导者，
眼镜端只运行一个轻量 CustomApp 负责镜片状态显示与物理按键上报。

## 角色与依赖

| 端 | SDK | 依赖坐标 | 职责 |
|----|-----|----------|------|
| 手机 | CXR-L | `com.rokid.cxr:client-l:1.0.4` | 鉴权、建会话、接收音频 PCM / 触发拍照收 JPEG、拉起眼镜 App、发状态、收按键 |
| 眼镜 | CXR-S | `com.rokid.cxr:cxr-service-bridge:1.0-20260417.063502-103` | 显示状态、上报物理键 |

- Maven 仓库：`https://maven.rokid.com/repository/maven-public/`（两端 `settings.gradle.kts` 已配）。
- 前置：手机安装 **Rokid AI App ≥ 1.9.0**（`com.rokid.sprite.aiapp`）并与眼镜配对；鉴权由该 App 承担，**无需 appId/appSecret**。
- 采集（音频/拍照）由**眼镜固件经 CXR-L 直达手机**；眼镜 CustomApp 不采集媒体。

## 会话生命周期（手机端 CxrGlassesConnection）

```
校验 Rokid AI App 已安装
  → AuthorizationHelper.requestAuthorization(MICROPHONE/CAMERA/MEDIA) 取 token
  → CXRLink(context).configCXRSession(CUSTOMAPP, GLASS_APP_PACKAGE).setCXRLinkCbk(hub).connect(token)
  → 等 onCXRLConnected(true) + onGlassBtConnected(true)
  → appIsInstalled() → onQueryAppResult(installed)
  → appStart("<pkg>.MainActivity") → onOpenAppResult(true)
  → setCXRAudioCbk / setCXRImageCbk / setCXRCustomCmdCbk
```

鉴权需 Activity 与 `onActivityResult` 配合：`MainActivity.attachActivity(this)` +
`onActivityResult → conn.onAuthResult(resultCode, data)`（requestCode = `REQUEST_CODE_AUTH`）。

## 媒体流

- **音频**：`startAudioStream(1)` 开启，`IAudioStreamCbk.onAudioReceived(data, offset, length)` 收 PCM
  （16kHz / 单声道 / 16bit）。手机端累积到 ~32000 字节（约 1s）为一块 → `audioFlow`，上传后台 `audio` 部件。
- **拍照关键帧**：手机按 `PHOTO_INTERVAL_MS`（默认 4000ms）循环 `takePhoto(1024,768,80)`，
  `IImageStreamCbk.onImageReceived(jpeg)` 收 JPEG → `frameFlow`，上传后台 `frame` 部件。
- **关键时刻**：`markKeyMoment()` 立即 `takePhoto`，该帧 `isKeyMoment=true`。
- **空间记忆**：仅拍照循环，不开音频。

## 自定义指令通道（Caps）

| 方向 | 通道键 | Caps 内容 | 用途 |
|------|--------|-----------|------|
| 手机 → 眼镜 | `rk_custom_client` | `["status", <文案>]` | 镜片显示：待机 / 记忆中 / 空间采集中 / 已暂停 |
| 眼镜 → 手机 | `rk_custom_key` | `["action", <KeyType 名>]` | 物理按键上报 |

- 手机侧：`cxrLink.sendCustomCmd("rk_custom_client", Caps)` 发状态；
  `ICustomCmdCbk.onCustomCmdResult(key, payload)`（key==`rk_custom_key`）收按键，`Caps.fromBytes` 解析。
- 眼镜侧：`CXRServiceBridge.subscribe("rk_custom_client", MsgCallback)` 收状态；
  `sendMessage("rk_custom_key", Caps)` 上报。

## 物理按键映射

眼镜端 `KeyReceiver` 监听系统广播（镜腿键/触控板/返回键，`com.android.action.ACTION_SPRITE_*` /
`ACTION_TWO_FINGER_*`），原样上报按键名；手机端 `CxrGlassesConnection` 归一为 `GlassKeyAction`，
再由采集页按录制状态映射语义：

| GlassKeyAction | 手机行为 |
|----------------|----------|
| CLICK | 未录制→开始时间记忆；录制中→结束并上传 |
| DOUBLE_CLICK | 标记关键时刻 |
| LONG_PRESS | 结束并上传 |

## 能力矩阵与 Mock

- `USE_MOCK_GLASSES=true`（`phone/app/build.gradle.kts`）：无真机离线开发，`MockGlassesConnection`
  周期产生合成 JPEG / PCM，可跑通"边采边传→后台处理→查询"。
- `USE_MOCK_GLASSES=false`：接真实 CXR-L 眼镜。

## 关键 API 索引（以官方 Sample 为准）

- `com.rokid.cxr.link.CXRLink`：`configCXRSession`、`connect(token)`、`disconnect`、`appIsInstalled/appStart/appStop/appUploadAndInstall`、`setCXRAudioCbk/startAudioStream/stopAudioStream`、`setCXRImageCbk/takePhoto`、`setCXRCustomCmdCbk/sendCustomCmd`、`setGlassBrightness/setGlassVolume/getGlassDeviceInfo`。
- `com.rokid.cxr.link.utils.CxrDefs.CXRSession(CxrDefs.CXRSessionType.CUSTOMAPP, pkg)`。
- 回调 `com.rokid.cxr.link.callbacks.*`：`ICXRLinkCbk / IGlassAppCbk / IAudioStreamCbk / IImageStreamCbk / ICustomCmdCbk`。
- 鉴权 `com.rokid.sprite.aiapp.externalapp.auth.*`：`AuthorizationHelper`、`AuthResult`、`GlassPermission`。
- 眼镜端 `com.rokid.cxr.CXRServiceBridge`、`com.rokid.cxr.Caps`。
