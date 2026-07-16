package com.echo.glasses

import android.os.Binder
import android.os.IBinder
import android.os.IInterface
import android.os.Parcel

/**
 * Manual implementation matching assistserver's com.rokid.os.sprite.assist.client.IAssistClient$Stub.
 * Method codes: 1=onRegisterResult, 2=onMessageReceive, 3=onDataReceive
 */
abstract class IAssistClientStub : Binder(), IInterface {

    companion object {
        const val DESCRIPTOR = "com.rokid.os.sprite.assist.client.IAssistClient"
        const val TRANSACTION_onRegisterResult = 1
        const val TRANSACTION_onMessageReceive = 2
        const val TRANSACTION_onDataReceive = 3
    }

    override fun asBinder(): IBinder = this

    override fun queryLocalInterface(descriptor: String): IInterface? {
        return if (DESCRIPTOR == descriptor) this else null
    }

    override fun onTransact(code: Int, data: Parcel, reply: Parcel?, flags: Int): Boolean {
        return when (code) {
            IBinder.INTERFACE_TRANSACTION -> {
                reply?.writeString(DESCRIPTOR)
                true
            }
            TRANSACTION_onRegisterResult -> {
                data.enforceInterface(DESCRIPTOR)
                val result = data.readInt()
                onRegisterResult(result)
                true
            }
            TRANSACTION_onMessageReceive -> {
                data.enforceInterface(DESCRIPTOR)
                val msg = data.readString() ?: ""
                onMessageReceive(msg)
                true
            }
            TRANSACTION_onDataReceive -> {
                data.enforceInterface(DESCRIPTOR)
                val len = data.readInt()
                val bytes = if (len > 0) {
                    val b = ByteArray(len)
                    data.readByteArray(b)
                    b
                } else {
                    ByteArray(0)
                }
                onDataReceive(bytes)
                true
            }
            else -> false
        }
    }

    abstract fun onRegisterResult(result: Int)
    abstract fun onMessageReceive(msg: String)
    abstract fun onDataReceive(data: ByteArray)
}
