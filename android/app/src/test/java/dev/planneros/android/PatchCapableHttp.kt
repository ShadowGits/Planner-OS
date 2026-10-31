package dev.planneros.android

import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.io.OutputStream
import java.net.HttpURLConnection
import java.net.Socket
import java.net.URL
import java.net.URLConnection
import java.net.URLStreamHandler

/**
 * The desktop JVM's HttpURLConnection refuses PATCH; Android's own one (the
 * phone) accepts it. Tests route the app's unchanged HttpURLConnection calls
 * through a plain HTTP/1.1 socket, which sends any method. Local server only.
 */
object PatchCapableHttp {
    private var installed=false

    fun install()=synchronized(this){
        if(installed)return@synchronized
        installed=true
        URL.setURLStreamHandlerFactory{protocol->
            if(protocol=="http")object:URLStreamHandler(){override fun openConnection(u:URL):URLConnection=Connection(u)} else null
        }
    }

    private class Connection(url:URL):HttpURLConnection(url){
        private val headers=linkedMapOf<String,String>()
        private val body=ByteArrayOutputStream()
        private var response:Pair<Int,ByteArray>?=null

        override fun setRequestMethod(method:String){this.method=method}
        override fun setRequestProperty(key:String,value:String){headers[key]=value}
        override fun getOutputStream():OutputStream=body
        override fun connect(){}
        override fun disconnect(){}
        override fun usingProxy()=false

        private fun send():Pair<Int,ByteArray> = response?:run{
            val payload=if(doOutput)body.toByteArray() else ByteArray(0)
            Socket(url.host,if(url.port>0)url.port else 80).use{socket->
                val head=StringBuilder("$method ${url.file} HTTP/1.1\r\nHost: ${url.host}:${url.port}\r\nConnection: close\r\nContent-Length: ${payload.size}\r\n")
                headers.forEach{(key,value)->head.append("$key: $value\r\n")}
                socket.getOutputStream().apply{write(head.append("\r\n").toString().toByteArray());write(payload);flush()}
                val raw=socket.getInputStream().readBytes()
                val split=(0 until raw.size-3).first{raw[it]==13.toByte()&&raw[it+1]==10.toByte()&&raw[it+2]==13.toByte()&&raw[it+3]==10.toByte()}
                val status=String(raw,0,split).lineSequence().first().split(" ")[1].toInt()
                (status to raw.copyOfRange(split+4,raw.size)).also{response=it}
            }
        }
        override fun getResponseCode()=send().first
        override fun getInputStream():InputStream=ByteArrayInputStream(send().second)
        override fun getErrorStream():InputStream=ByteArrayInputStream(send().second)
    }
}
