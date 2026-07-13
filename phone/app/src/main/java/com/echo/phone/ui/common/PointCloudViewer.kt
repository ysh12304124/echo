package com.echo.phone.ui.common

import android.annotation.SuppressLint
import android.view.MotionEvent
import android.webkit.ConsoleMessage
import android.webkit.WebChromeClient
import android.webkit.WebView
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.viewinterop.AndroidView
import com.echo.phone.BuildConfig
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

private val BASE_URL = BuildConfig.API_BASE_URL.removeSuffix("/api/v1/").removeSuffix("/")

@SuppressLint("SetJavaScriptEnabled", "ClickableViewAccessibility")
@Composable
fun PointCloudViewer(pointCloudUrl: String?, modifier: Modifier = Modifier) {
    val path = pointCloudUrl?.removePrefix(BASE_URL) ?: ""
    val plyJs = if (path.isNotBlank()) "\"" + path + "\"" else "null"

    val html = "<!DOCTYPE html><html><head>" +
        "<meta name='viewport' content='width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover'>" +
        "</head><body style='margin:0;background:#000;overflow:hidden;'>" +
        "<canvas id='c' style='width:100%;height:100%;touch-action:none;'></canvas>" +
        "<div id='s' style='position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);color:#aaa;font:14px sans-serif;z-index:10;pointer-events:none;text-align:center;'>Loading GS...</div>" +
        "<div id='btns' style='position:absolute;bottom:12px;right:12px;display:flex;gap:8px;z-index:20;'>" +
        "<button id='btnR' style='width:40px;height:40px;border-radius:20px;border:1px solid rgba(255,255,255,.2);background:rgba(0,0,0,.5);color:#ccc;font-size:16px;'>&#8634;</button>" +
        "<button id='btnF' style='width:40px;height:40px;border-radius:20px;border:1px solid rgba(255,255,255,.2);background:rgba(0,0,0,.5);color:#ccc;font-size:16px;'>&#9974;</button>" +
        "</div>" +
        "<script>" +
        "var W=window.innerWidth,H=window.innerHeight,D=devicePixelRatio||2;" +
        "var PLY=" + plyJs + ";" +
        "var BASE='" + BASE_URL + "';" +
        "</script>" +
        "<script src='" + BASE_URL + "/data/threejs/playcanvas.min.js'></script>" +
        "<script>" +
        "(function(){" +
        "var canvas=document.getElementById('c');" +
        "canvas.width=W*Math.min(D,2);canvas.height=H*Math.min(D,2);" +
        "var statusEl=document.getElementById('s');" +

        // ---- orbit camera state ----
        "var theta=0,phi=Math.PI/3,radius=3;" +
        "var tx=0,ty=0,tz=0;" +
        "var initTheta=0,initPhi=Math.PI/3,initRadius=3,initTx=0,initTy=0,initTz=0;" +
        "var cam=null,app=null;" +

        "function camPos(){" +
        "  var sp=Math.sin(phi),cp=Math.cos(phi),st=Math.sin(theta),ct=Math.cos(theta);" +
        "  return{x:tx+radius*sp*ct,y:ty+radius*cp,z:tz+radius*sp*st};" +
        "}" +

        "function applyCam(){" +
        "  if(!cam)return;" +
        "  var p=camPos();" +
        "  cam.setPosition(p.x,p.y,p.z);" +
        "  cam.lookAt(tx,ty,tz);" +
        "}" +

        // ---- touch handling ----
        "var touches={},lastPinch=0,lastMX=0,lastMY=0,panning=false;" +

        "canvas.addEventListener('touchstart',function(e){" +
        "  e.preventDefault();" +
        "  for(var i=0;i<e.changedTouches.length;i++){" +
        "    var t=e.changedTouches[i];" +
        "    touches[t.identifier]={x:t.clientX,y:t.clientY};" +
        "  }" +
        "  var ids=Object.keys(touches);" +
        "  if(ids.length>=2){" +
        "    var a=touches[ids[0]],b=touches[ids[1]];" +
        "    var dx=b.x-a.x,dy=b.y-a.y;" +
        "    lastPinch=Math.sqrt(dx*dx+dy*dy);" +
        "    lastMX=(a.x+b.x)/2;lastMY=(a.y+b.y)/2;" +
        "    panning=true;" +
        "  }else{panning=false;}" +
        "},{passive:false});" +

        "canvas.addEventListener('touchmove',function(e){" +
        "  e.preventDefault();" +
        "  var ids=Object.keys(touches);" +
        "  for(var i=0;i<e.changedTouches.length;i++){" +
        "    var t=e.changedTouches[i];" +
        "    if(touches[t.identifier])touches[t.identifier]={x:t.clientX,y:t.clientY};" +
        "  }" +
        "  ids=Object.keys(touches);" +
        "  if(ids.length===1&&!panning){" +
        "    var t=e.changedTouches[0];if(!t)return;" +
        "    var p=touches[ids[0]];" +
        "    var dx=t.clientX-p.x,dy=t.clientY-p.y;" +
        "    theta-=dx*0.005;phi-=dy*0.005;" +
        "    phi=Math.max(0.01,Math.min(Math.PI-0.01,phi));" +
        "    p.x=t.clientX;p.y=t.clientY;" +
        "  }else if(ids.length>=2){" +
        "    var a=touches[ids[0]],b=touches[ids[1]];" +
        "    var pdx=b.x-a.x,pdy=b.y-a.y;" +
        "    var dist=Math.sqrt(pdx*pdx+pdy*pdy);" +
        "    if(lastPinch>0){radius*=lastPinch/dist;radius=Math.max(0.0001,Math.min(1e9,radius));}" +
        "    lastPinch=dist;" +
        "    var mx=(a.x+b.x)/2,my=(a.y+b.y)/2;" +
        "    if(lastMX!==0){" +
        "      var panDx=mx-lastMX,panDy=my-lastMY;" +
        "      var p=camPos();" +
        "      var fx=tx-p.x,fy=ty-p.y,fz=tz-p.z;" +
        "      var fl=Math.sqrt(fx*fx+fy*fy+fz*fz)||1;fx/=fl;fy/=fl;fz/=fl;" +
        "      var rx=-fz,ry=0,rz=fx;" +
        "      var rl=Math.sqrt(rx*rx+rz*rz);" +
        "      if(rl>0.001){rx/=rl;rz/=rl;}else{rx=1;ry=0;rz=0;}" +
        "      var ux=ry*fz-rz*fy,uy=rz*fx-rx*fz,uz=rx*fy-ry*fx;" +
        "      var s=radius*0.001;" +
        "      tx-=(rx*panDx+ux*panDy)*s;" +
        "      ty-=(ry*panDx+uy*panDy)*s;" +
        "      tz-=(rz*panDx+uz*panDy)*s;" +
        "    }" +
        "    lastMX=mx;lastMY=my;" +
        "  }" +
        "  applyCam();" +
        "},{passive:false});" +

        "canvas.addEventListener('touchend',function(e){" +
        "  for(var i=0;i<e.changedTouches.length;i++)delete touches[e.changedTouches[i].identifier];" +
        "  if(Object.keys(touches).length<2){panning=false;lastPinch=0;lastMX=0;lastMY=0;}" +
        "},{passive:false});" +

        // ---- reset ----
        "document.getElementById('btnR').onclick=function(){" +
        "  theta=initTheta;phi=initPhi;radius=initRadius;" +
        "  tx=initTx;ty=initTy;tz=initTz;" +
        "  applyCam();" +
        "};" +

        // ---- fullscreen ----
        "var fs=false;" +
        "document.getElementById('btnF').onclick=function(){" +
        "  fs=!fs;" +
        "  if(fs){document.body.requestFullscreen().catch(function(){});}" +
        "  else{document.exitFullscreen().catch(function(){});}" +
        "};" +

        // ---- main ----
        "console.log('PC: init, PLY='+PLY);" +

        "if(typeof pc==='undefined'){" +
        "  statusEl.textContent='PlayCanvas not loaded';" +
        "  console.error('PC: pc is undefined - script load failed');" +
        "  return;" +
        "}" +

        "pc.createGraphicsDevice(canvas,{" +
        "  deviceTypes:[]," +
        "  antialias:false," +
        "  depth:true," +
        "  stencil:false," +
        "  preserveDrawingBuffer:true," +
        "  powerPreference:'high-performance'" +
        "}).then(function(device){" +
        "  console.log('PC: device='+device.deviceType);" +

        "  var ao=new pc.AppOptions();" +
        "  ao.graphicsDevice=device;" +
        "  ao.componentSystems=[" +
        "    pc.CameraComponentSystem," +
        "    pc.LightComponentSystem," +
        "    pc.RenderComponentSystem," +
        "    pc.GSplatComponentSystem," +
        "    pc.ScriptComponentSystem" +
        "  ];" +
        "  ao.resourceHandlers=[" +
        "    pc.ContainerHandler," +
        "    pc.TextureHandler," +
        "    pc.GSplatHandler," +
        "    pc.BinaryHandler" +
        "  ];" +

        "  app=new pc.AppBase(canvas);" +
        "  app.init(ao);" +
        "  app.scene.ambientLight.set(0.5,0.5,0.5);" +

        // light entity for better shading
        "  var light=new pc.Entity('light');" +
        "  light.setEulerAngles(35,45,0);" +
        "  light.addComponent('light',{color:new pc.Color(1,0.98,0.96),intensity:1});" +
        "  app.root.addChild(light);" +

        // camera
        "  cam=new pc.Entity('camera');" +
        "  cam.addComponent('camera',{" +
        "    clearColor:new pc.Color(0.067,0.067,0.2)," +
        "    nearClip:0.0001," +
        "    farClip:10000" +
        "  });" +
        "  app.root.addChild(cam);" +

        "  app.start();" +
        "  app.autoRender=true;" +
        "  console.log('PC: app started');" +

        "  if(!PLY||PLY==='null'){" +
        "    statusEl.textContent='No PLY';" +
        "    applyCam();" +
        "  }else{" +
        "    console.log('PC: loading '+PLY);" +
        "    var asset=new pc.Asset('splat','gsplat',{url:PLY,filename:'model.ply'});" +

        "    asset.on('progress',function(rcv,len){" +
        "      var pct=Math.round(rcv/Math.max(1,len)*100);" +
        "      statusEl.textContent='Loading... '+pct+'%';" +
        "    });" +

        "    asset.on('load',function(){" +
        "      console.log('PC: GS asset loaded');" +
        "      var ent=new pc.Entity('gsplat');" +
        "      ent.addComponent('gsplat',{asset:asset,unified:true});" +
        "      app.root.addChild(ent);" +
        "      console.log('PC: splat entity added to scene');" +

        // Try to get bounds from splat resource
        "      try{" +
        "        var r=asset.resource;" +
        "        if(r&&r.splat){" +
        "          var s=r.splat;" +
        "          var cx=(s.centerX||0),cy=(s.centerY||0),cz=(s.centerZ||0);" +
        "          var hx=(s.halfExtentsX||1),hy=(s.halfExtentsY||1),hz=(s.halfExtentsZ||1);" +
        "          var sz=Math.sqrt(hx*hx+hy*hy+hz*hz)*2;" +
        "          tx=cx;ty=cy;tz=cz;radius=Math.max(0.1,sz*0.8);" +
        "          console.log('PC: bounds center=('+cx.toFixed(2)+','+cy.toFixed(2)+','+cz.toFixed(2)+') size='+sz.toFixed(2));" +
        "        }" +
        "      }catch(e){console.log('PC: bounds failed: '+e);}" +

        "      initTheta=theta;initPhi=phi;initRadius=radius;" +
        "      initTx=tx;initTy=ty;initTz=tz;" +
        "      applyCam();" +
        "      statusEl.style.display='none';" +
        "      console.log('PC: READY');" +
        "    });" +

        "    asset.on('error',function(err){" +
        "      console.error('PC: GS load error: '+err);" +
        "      statusEl.textContent='GS load failed: '+err;" +
        "    });" +

        "    app.assets.add(asset);" +
        "    app.assets.load(asset);" +
        "  }" +
        "}).catch(function(err){" +
        "  console.error('PC: device error: '+err);" +
        "  statusEl.textContent='Device error: '+err.message;" +
        "});" +

        "})();" +
        "</script></body></html>"

    AndroidView(
        modifier = modifier,
        factory = { ctx ->
            WebView(ctx).apply {
                setLayerType(android.view.View.LAYER_TYPE_HARDWARE, null)
                settings.javaScriptEnabled = true
                settings.domStorageEnabled = true
                settings.allowFileAccess = true
                setWebChromeClient(object : WebChromeClient() {
                    override fun onConsoleMessage(msg: ConsoleMessage): Boolean {
                        val sdf = SimpleDateFormat("HH:mm:ss.SSS", Locale.US)
                        val line = "[${msg.messageLevel()}] ${msg.message()} (${msg.sourceId()}:${msg.lineNumber()})"
                        android.util.Log.w("ECHO_WEB", line)
                        try { File(ctx.filesDir, "webview.log").appendText(sdf.format(Date()) + " " + line + "\n") } catch (_: Exception) {}
                        return true
                    }
                })
                setOnTouchListener { _, event ->
                    when (event.action) {
                        MotionEvent.ACTION_DOWN -> parent.requestDisallowInterceptTouchEvent(true)
                        MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> parent.requestDisallowInterceptTouchEvent(false)
                    }
                    false
                }
                loadDataWithBaseURL(BASE_URL + "/", html, "text/html", "utf-8", null)
            }
        },
        update = { webView ->
            webView.loadDataWithBaseURL(BASE_URL + "/", html, "text/html", "utf-8", null)
        },
    )
}
