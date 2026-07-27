package com.echo.phone.data.api

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Test
import retrofit2.http.Multipart
import retrofit2.http.POST

class VoiceQueryApiContractTest {
    @Test
    fun declaresMultipartVoiceQueryEndpoints() {
        val methods = EchoApiService::class.java.declaredMethods
        val transcribe = methods.single { it.name == "transcribeVoice" }
        val query = methods.single { it.name == "queryVoice" }

        assertNotNull(transcribe.getAnnotation(Multipart::class.java))
        assertEquals("query/voice/transcribe", transcribe.getAnnotation(POST::class.java).value)
        assertNotNull(query.getAnnotation(Multipart::class.java))
        assertEquals("query/voice", query.getAnnotation(POST::class.java).value)
    }
}
