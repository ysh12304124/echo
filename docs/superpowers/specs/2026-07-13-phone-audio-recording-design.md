# 手机端音频采集 + 断连保护 设计文档

**日期**: 2026-07-13
**状态**: 已批准

## 背景

眼镜端麦克风在测试中存在问题，需要将时间记忆录制的音频采集从眼镜切换到手机端麦克风。同时需要处理眼镜蓝牙断连场景，保证照片与音频的时间对齐。

## 约束

- 眼镜 START/STOP 指令依然是录制的总开关
- 眼镜蓝牙断连 = 录制立即结束，自动完成 session
- 音频和照片的时间戳必须对齐

## 架构改动

### 新增: PhoneMicRecorder

封装 Android AudioRecord，输出与眼镜音频回调相同格式的数据流。

- 配置: 16kHz / Mono / PCM 16bit
- 缓冲: 累积 32000 字节（1 秒）为一块，通过 SharedFlow 暴露
- 时间戳: 每块 System.currentTimeMillis()，与照片帧时间戳同源
- 生命周期: start() 开始采集, stop() 停止并 flush 尾部残余块

文件位置: phone/app/src/main/java/com/echo/phone/data/PhoneMicRecorder.kt

### 修改: RecordingController

- startTime(): 新增 phoneMic.start(), glasses.startTimeRecording() 不再启动眼镜音频流
- collectMedia(): audioJob 数据源从 glasses.audioFlow 切到 phoneMic.audioFlow
- stopAndComplete(): 新增 phoneMic.stop(), glasses.stopRecording() 不再停止眼镜音频流

### 修改: CxrGlassesConnection

- startTimeRecording(): 去掉 startAudioStream(1), 只保留 startPhotoLoop()
- stopRecording(): 去掉 stopAudioStream() + flushAudio(), 只保留 stopPhotoLoop()
- pauseRecording() / resumeRecording(): 去掉音频流启停
- 音频回调、buffer 等基础设施保留不删

### 修改: EchoApplication

- 新增协程监听 glassesConnection.connectionState
- 当状态变为 DISCONNECTED 且 isRecording=true 时, 自动调用 handleStop() 完成录制
- compareAndSet(true, false) 保证 STOP 指令和断连不会重复触发

## 时间对齐保证

照片和音频的时间戳都打在同一台手机的 System.currentTimeMillis() 上:
- 照片: 眼镜拍照 -> CXR-L 传输 -> onImageReceived -> MediaFrame(timestampMs=手机钟)
- 音频: 手机麦克风 -> AudioRecord.read() -> 累积 1 秒 -> MediaAudio(timestampMs=手机钟)

不存在时钟偏差。后台 AI 处理按 timestampMs 排序即可正确配对。蓝牙传输照片延迟 (< 500ms) 相对于 4 秒拍照间隔可忽略。

## 断连流程

蓝牙断开 -> btConnected = false
         -> observeDeviceState() -> connectionState = DISCONNECTED
         -> EchoApplication 监听到变化
         -> isRecording? -> handleStop()
         -> stopAndComplete() -> completeSession()
         -> recordingCompleted 通知 UI 刷新

## 风险点

- 断连瞬间的尾部照片: stopPhotoLoop() 只取消定时器，已发出的 takePhoto() 仍可能回调 onImageReceived，排空机制会等它上传完
- 断连后 glasses.stopRecording() 的副作用: stopPhotoLoop() 只 cancel 协程，不依赖眼镜链路，安全
