package com.echo.phone.data

import java.io.RandomAccessFile
import java.nio.file.Files
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SpaceVideoPatchTest {
    @Test
    fun appliesPatchAtItsOffsetWithoutReplacingTheMp4Prefix() {
        val path = Files.createTempFile("echo-space", ".mp4").toFile()
        try {
            RandomAccessFile(path, "rw").use { file ->
                file.write("ftyp-free-mdat-tail".toByteArray())
                applyVideoPatch(file, offset = 10L, bytes = "moov".toByteArray())
            }

            assertArrayEquals(
                "ftyp-free-moov-tail".toByteArray(),
                path.readBytes(),
            )
        } finally {
            path.delete()
        }
    }

    @Test
    fun appendsTailChunkToPendingSpaceCache() {
        val path = Files.createTempFile("echo-space-pending", ".mp4").toFile()
        try {
            RandomAccessFile(path, "rw").use { file ->
                file.write("ftyp-free-mdat".toByteArray())
                appendVideoChunk(file, "-tail-moov".toByteArray())
            }

            assertArrayEquals(
                "ftyp-free-mdat-tail-moov".toByteArray(),
                path.readBytes(),
            )
        } finally {
            path.delete()
        }
    }

    @Test
    fun spaceCannotFinalizeUntilVideoEndHasBeenReceived() {
        assertFalse(canFinalizeSpace(headerPatchReceived = true, videoDone = false))
        assertFalse(canFinalizeSpace(headerPatchReceived = false, videoDone = true))
        assertTrue(canFinalizeSpace(headerPatchReceived = true, videoDone = true))
    }
}
