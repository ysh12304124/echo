package com.echo.phone.data

/** Tracks the independent video stream used by an inline SPACE session. */
internal class SpaceVideoStreamState(val streamId: String) {
    var headerPatchReceived: Boolean = false
        private set

    var videoEnded: Boolean = false
        private set

    val isComplete: Boolean
        get() = headerPatchReceived && videoEnded

    fun accepts(candidateStreamId: String): Boolean = candidateStreamId == streamId

    fun onHeaderPatch(candidateStreamId: String): Boolean {
        if (!accepts(candidateStreamId)) return false
        headerPatchReceived = true
        return true
    }

    fun onVideoEnd(candidateStreamId: String): Boolean {
        if (!accepts(candidateStreamId)) return false
        videoEnded = true
        return true
    }
}
