package dev.planneros.android

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Path
import android.graphics.PathMeasure
import android.graphics.Typeface
import android.os.SystemClock
import android.view.View
import kotlin.math.*

/** A local, monotonic animation: rendering never writes state or calls the API. */
class StopwatchDialView(context:Context):View(context) {
    private val paint=Paint(Paint.ANTI_ALIAS_FLAG)
    private var faceBitmap:Bitmap?=null
    private val measure=PathMeasure()
    private val remainingTrack=Path()
    private val point=FloatArray(2)
    private val medium=Typeface.create("sans-serif-medium",Typeface.NORMAL)
    private val condensed=Typeface.create("sans-serif-condensed",Typeface.BOLD)
    private val regular=Typeface.create("sans-serif",Typeface.NORMAL)
    private var cx=0f;private var cy=0f;private var radius=0f
    private var trackLength=0f
    private var model:TimerState?=null
    private var receivedAt=0L
    private var receivedRemaining=0L
    private var dark=false
    private val density=resources.displayMetrics.density
    fun palette(isDark:Boolean){if(dark!=isDark){dark=isDark;faceBitmap?.recycle();faceBitmap=null};invalidate()}
    fun display(state:TimerState,remainingMillis:Long){
        model=state;receivedRemaining=remainingMillis;receivedAt=SystemClock.elapsedRealtime()
        contentDescription="${state.title}, ${timerText(remainingMillis)} remaining, ${if(state.running)"running" else "paused"}"
        invalidate()
    }
    override fun onMeasure(widthMeasureSpec:Int,heightMeasureSpec:Int){
        setMeasuredDimension(resolveSize((204*density).roundToInt(),widthMeasureSpec),resolveSize((220*density).roundToInt(),heightMeasureSpec))
    }
    private fun color(light:String,night:String)=Color.parseColor(if(dark)night else light)
    override fun onSizeChanged(w:Int,h:Int,oldw:Int,oldh:Int){super.onSizeChanged(w,h,oldw,oldh);faceBitmap?.recycle();faceBitmap=null}
    private fun prepareFace(){
        if(width<=0||height<=0)return
        val bitmap=Bitmap.createBitmap(width,height,Bitmap.Config.ARGB_8888)
        val canvas=Canvas(bitmap)
        cx=width/2f;cy=height/2f+6*density
        radius=min(width*.45f,height*.42f)
        val outer=RectF(cx-radius,cy-radius,cx+radius,cy+radius)
        val edge=18*density
        paint.style=Paint.Style.FILL;paint.color=color("#C69A70","#79533C")
        canvas.drawRoundRect(outer,edge,edge,paint)
        paint.color=color("#E4BD94","#A27351")
        canvas.drawRoundRect(cx-12*density,outer.top-10*density,cx+12*density,outer.top-3*density,3*density,3*density,paint)
        val clip=Path().apply{addRoundRect(outer,edge,edge,Path.Direction.CW)}
        canvas.save();canvas.clipPath(clip)
        // Deterministic grain is painted locally: no downloaded texture or network.
        paint.style=Paint.Style.STROKE;paint.strokeWidth=.7f*density;paint.color=color("#AD7B52","#573A2D");paint.alpha=85
        for(row in 0..26){
            val grain=Path();val y=outer.top+row*7*density
            for(step in 0..24){val x=outer.left+step*outer.width()/24;val gy=y+sin(step*.55+row*.9).toFloat()*2.4f*density
                if(step==0)grain.moveTo(x,gy)else grain.lineTo(x,gy)}
            canvas.drawPath(grain,paint)
        }
        canvas.restore();paint.alpha=255
        val face=RectF(outer.left+8*density,outer.top+8*density,outer.right-8*density,outer.bottom-8*density)
        paint.style=Paint.Style.FILL;paint.color=color("#FFFBF4","#26212A")
        canvas.drawRoundRect(face,12*density,12*density,paint)
        val rim=RectF(face.left+4*density,face.top+4*density,face.right-4*density,face.bottom-4*density)
        val corner=9*density
        // Start at twelve o'clock; a shrinking distance moves backwards on a square dial.
        val track=Path().apply{
            moveTo(cx,rim.top);lineTo(rim.right-corner,rim.top);quadTo(rim.right,rim.top,rim.right,rim.top+corner)
            lineTo(rim.right,rim.bottom-corner);quadTo(rim.right,rim.bottom,rim.right-corner,rim.bottom)
            lineTo(rim.left+corner,rim.bottom);quadTo(rim.left,rim.bottom,rim.left,rim.bottom-corner)
            lineTo(rim.left,rim.top+corner);quadTo(rim.left,rim.top,rim.left+corner,rim.top);lineTo(cx,rim.top)
        }
        measure.setPath(track,true);trackLength=measure.length;val length=trackLength
        paint.style=Paint.Style.STROKE;paint.strokeWidth=2.5f*density;paint.color=color("#E7DAD1","#4C3443")
        canvas.drawPath(track,paint)
        for(tick in 0 until 60){
            measure.getPosTan(length*tick/60f,point,null)
            val dx=cx-point[0];val dy=cy-point[1];val norm=hypot(dx,dy).coerceAtLeast(1f)
            val major=tick%5==0;val inset=5*density;val size=(if(major)7 else 3)*density
            paint.color=if(major)color("#8A727D","#C5ABB7") else color("#DCC8C1","#654956");paint.strokeWidth=(if(major)1.5f else .8f)*density
            canvas.drawLine(point[0]+dx/norm*inset,point[1]+dy/norm*inset,point[0]+dx/norm*(inset+size),point[1]+dy/norm*(inset+size),paint)
        }
        faceBitmap=bitmap
    }
    override fun onDraw(canvas:Canvas){
        super.onDraw(canvas)
        val state=model?:return
        if(faceBitmap==null)prepareFace()
        faceBitmap?.let{canvas.drawBitmap(it,0f,0f,null)}
        val left=receivedRemaining-if(state.running)(SystemClock.elapsedRealtime()-receivedAt).coerceAtLeast(0)else 0
        val wine=color("#A32C53","#F286A8")
        val ink=color("#292A35","#F7F2F5")
        val muted=color("#8A727D","#C5ABB7")
        val length=trackLength
        val progress=(left.toDouble()/state.durationMs.coerceAtLeast(1)).coerceIn(0.0,1.0).toFloat()
        remainingTrack.rewind();measure.getSegment(0f,length*progress,remainingTrack,true)
        paint.style=Paint.Style.STROKE;paint.strokeWidth=2.5f*density;paint.color=wine;paint.strokeCap=Paint.Cap.ROUND
        canvas.drawPath(remainingTrack,paint)
        val phase=Math.floorMod(left,60_000L).toFloat()/60_000f
        measure.getPosTan(length*phase,point,null)
        val dx=cx-point[0];val dy=cy-point[1];val norm=hypot(dx,dy).coerceAtLeast(1f)
        paint.color=wine;paint.strokeWidth=2.5f*density;paint.strokeCap=Paint.Cap.ROUND
        canvas.drawLine(point[0]+dx/norm*3*density,point[1]+dy/norm*3*density,point[0]+dx/norm*20*density,point[1]+dy/norm*20*density,paint)
        paint.style=Paint.Style.FILL;canvas.drawCircle(point[0],point[1],3*density,paint)
        paint.textAlign=Paint.Align.CENTER;paint.typeface=medium
        paint.textSize=10*resources.displayMetrics.scaledDensity;paint.color=muted
        canvas.drawText(if(!state.running)"PAUSED" else if(left<0)"OVERTIME" else "TIME LEFT",cx,cy-24*density,paint)
        val seconds=abs(left)/1000
        val digits=(if(left<0)"+" else "")+if(seconds>=3600)"%d:%02d:%02d".format(seconds/3600,(seconds/60)%60,seconds%60)else"%02d:%02d".format(seconds/60,seconds%60)
        paint.typeface=condensed
        paint.textSize=32*resources.displayMetrics.scaledDensity
        val maxWidth=radius*1.5f
        if(paint.measureText(digits)>maxWidth)paint.textSize*=maxWidth/paint.measureText(digits)
        paint.color=ink;canvas.drawText(digits,cx,cy+12*density,paint)
        paint.typeface=regular;paint.textSize=12*resources.displayMetrics.scaledDensity;paint.color=wine
        canvas.drawText(".%02d".format((abs(left)%1000)/10),cx,cy+32*density,paint)
        paint.color=color("#D6EADF","#3B5A4D");canvas.drawCircle(cx,cy+49*density,3*density,paint)
        if(state.running&&isShown)postInvalidateDelayed(50)
    }
}
