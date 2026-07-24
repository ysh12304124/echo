package com.echo.phone.data

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SpaceVideoStreamStateTest {
    @Test
    fun timeStreamSignalsDoNotCompleteSpaceStream() {
        val state = SpaceVideoStreamState("space-session")

        assertFalse(state.onHeaderPatch("time-stream"))
        assertFalse(state.onVideoEnd("time-stream"))
        assertFalse(state.isComplete)
    }

    @Test
    fun spaceStreamRequiresPatchAndEndBeforeUpload() {
        val state = SpaceVideoStreamState("space-session")

        assertTrue(state.onVideoEnd("space-session"))
        assertFalse(state.isComplete)

        assertTrue(state.onHeaderPatch("space-session"))
        assertTrue(state.isComplete)

        assertTrue(state.onVideoEnd("space-session"))
        assertTrue(state.isComplete)
    }
}
