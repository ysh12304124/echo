package com.echo.phone.data

import com.echo.phone.domain.MediaAudio
import com.echo.phone.domain.MediaFrame
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * 端上图片初筛：模糊/重复/无信息帧丢弃。
 * 可插拔接口，后续可替换为更复杂的算法。
 */
interface FrameFilter {
    suspend fun shouldKeep(frame: MediaFrame): Boolean
}

class SimpleFrameFilter : FrameFilter {
    private val recentHashes = mutableListOf<Int>()
    private val maxRecent = 20

    override suspend fun shouldKeep(frame: MediaFrame): Boolean {
        if (frame.data.size < 100) return false
        val hash = frame.data.contentHashCode()
        if (recentHashes.contains(hash)) return false
        recentHashes.add(hash)
        if (recentHashes.size > maxRecent) recentHashes.removeAt(0)
        return true
    }
}

/**
 * 端上 ASR 占位接口，后续可接入设备端语音识别。
 */
interface OnDeviceASR {
    suspend fun transcribe(audio: MediaAudio): String?
}

class MockOnDeviceASR : OnDeviceASR {
    override suspend fun transcribe(audio: MediaAudio): String? = null
}

class MediaUploadPipeline(
    private val frameFilter: FrameFilter = SimpleFrameFilter(),
    private val onDeviceASR: OnDeviceASR = MockOnDeviceASR(),
) {
    suspend fun filterFrames(frames: List<MediaFrame>): List<MediaFrame> =
        withContext(Dispatchers.Default) {
            frames.filter { frameFilter.shouldKeep(it) }
        }
}
