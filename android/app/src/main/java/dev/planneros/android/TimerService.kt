package dev.planneros.android

import android.app.*
import android.content.*
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.content.res.Configuration
import android.os.*
import android.provider.Settings
import android.view.*
import android.widget.*
import androidx.core.app.NotificationCompat
import org.json.JSONObject

object TimerStore {
    private val lock=Any()
    private fun epoch(c:Context):String=synchronized(lock){
        val p=c.getSharedPreferences("focus",Context.MODE_PRIVATE)
        p.getString("epoch",null)?:java.util.UUID.randomUUID().toString().also{p.edit().putString("epoch",it).commit()}
    }
    fun intent(c:Context,action:String)=Intent(c,TimerService::class.java).setAction(action)
        .putExtra("connection_generation",SecureConfig(c).generation).putExtra("epoch",epoch(c))
    fun accepts(c:Context,i:Intent)=i.getLongExtra("connection_generation",-1)==SecureConfig(c).generation&&i.getStringExtra("epoch")==epoch(c)
    fun boot(c:Context)=Settings.Global.getInt(c.contentResolver,Settings.Global.BOOT_COUNT,0)
    fun read(c:Context):TimerState?= c.getSharedPreferences("focus",Context.MODE_PRIVATE).getString("state",null)?.let{runCatching{
        val j=JSONObject(it); TimerState(j.getString("id"),j.getString("title"),j.getLong("duration"),j.getLong("elapsed"),j.getLong("anchor"),j.getLong("wall"),j.getInt("boot"),j.getBoolean("running"))
    }.getOrNull()}
    fun save(c:Context,s:TimerState?){val p=c.getSharedPreferences("focus",Context.MODE_PRIVATE).edit();if(s==null)p.remove("state").putString("epoch",java.util.UUID.randomUUID().toString()) else p.putString("state",JSONObject().put("id",s.taskId).put("title",s.title).put("duration",s.durationMs).put("elapsed",s.elapsedBeforeMs).put("anchor",s.anchorElapsedMs).put("wall",s.anchorWallMs).put("boot",s.bootCount).put("running",s.running).toString());p.commit()}
    fun remaining(c:Context,s:TimerState)=s.remaining(SystemClock.elapsedRealtime(),System.currentTimeMillis(),boot(c))
    fun start(c:Context,t:Task){val i=intent(c,"START").putExtra("id",t.id).putExtra("title",t.title).putExtra("minutes",t.minutes);c.startForegroundService(i)}
    fun action(c:Context,action:String){c.startForegroundService(intent(c,action))}
    fun reset(c:Context){
        // No new foreground service is started merely to stop the old one.
        save(c,null)
        c.stopService(Intent(c,TimerService::class.java))
        c.getSystemService(NotificationManager::class.java).cancel(TimerService.FOCUS_ID)
    }
    fun refresh(c:Context,t:Task){
        val current=read(c)?:return
        if(current.taskId!=t.id)return
        val duration=t.minutes.coerceIn(1,1440).toLong()*60_000
        if(current.title==t.title&&current.durationMs==duration)return
        c.startForegroundService(intent(c,"UPDATE")
            .putExtra("id",t.id).putExtra("title",t.title).putExtra("minutes",t.minutes))
    }
}

class TimerService:Service(){
    private val handler=Handler(Looper.getMainLooper())
    private var state:TimerState?=null
    private var bubble:LinearLayout?=null
    private var timeView:TextView?=null
    private var toggleView:TextView?=null
    private var titleView:TextView?=null
    private var bubbleDark:Boolean?=null
    private lateinit var windows:WindowManager
    private var hidden=false
    private val ticker=object:Runnable{override fun run(){val s=state?:return;if(bubble!=null&&!Settings.canDrawOverlays(this@TimerService))removeBubble();titleView?.text=s.title.take(32);timeView?.text=timerText(TimerStore.remaining(this@TimerService,s));toggleView?.text=if(s.running) "Ⅱ Pause" else "▶ Resume";getSystemService(NotificationManager::class.java).notify(FOCUS_ID,notification(s));handler.postDelayed(this,1000)}}
    override fun onCreate(){super.onCreate();windows=getSystemService(WindowManager::class.java);getSystemService(NotificationManager::class.java).createNotificationChannel(NotificationChannel("focus","Focus timer",NotificationManager.IMPORTANCE_LOW))}
    override fun onBind(intent:Intent?)=null
    override fun onStartCommand(intent:Intent?,flags:Int,startId:Int):Int{
        // A queued action from a prior connection or already-ended timer
        // must not restore that old task after a settings change or STOP.
        if(intent!=null&&!TimerStore.accepts(this,intent)){
            if(state==null){stopSelf();return START_NOT_STICKY}
            return START_STICKY
        }
        state=state?:TimerStore.read(this)
        state=state?.recover(SystemClock.elapsedRealtime(),System.currentTimeMillis(),TimerStore.boot(this))
        when(intent?.action){
            "START"->{val id=intent.getStringExtra("id")?:return START_NOT_STICKY
                // Starting an already active block keeps its elapsed time.
                val title=intent.getStringExtra("title")?:"Focus"
                val duration=intent.getIntExtra("minutes",30).coerceIn(1,1440).toLong()*60_000
                if(state?.taskId!=id){state=TimerState(id,title,duration,anchorElapsedMs=SystemClock.elapsedRealtime(),anchorWallMs=System.currentTimeMillis(),bootCount=TimerStore.boot(this));hidden=false;removeBubble()}
                else state=state?.metadata(title,duration)}
            "UPDATE"->{if(state?.taskId==intent.getStringExtra("id"))state=state?.metadata(intent.getStringExtra("title")?:state!!.title,intent.getIntExtra("minutes",30).coerceIn(1,1440).toLong()*60_000)}
            "TOGGLE"->state=state?.toggle(SystemClock.elapsedRealtime(),System.currentTimeMillis(),TimerStore.boot(this))
            "STOP"->{TimerStore.save(this,null);state=null;removeBubble();stopForeground(STOP_FOREGROUND_REMOVE);stopSelf();return START_NOT_STICKY}
            "SHOW"->{hidden=false}
        }
        val s=state?:run{stopSelf();return START_NOT_STICKY}
        TimerStore.save(this,s);startForeground(FOCUS_ID,notification(s));if(!hidden&&Settings.canDrawOverlays(this))showBubble(s)
        handler.removeCallbacks(ticker);handler.post(ticker);return START_STICKY
    }
    private fun action(action:String,code:Int)=PendingIntent.getService(this,code,TimerStore.intent(this,action),PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    private fun notification(s:TimerState):Notification {
        val open=PendingIntent.getActivity(this,0,Intent(this,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val finish=PendingIntent.getActivity(this,1,Intent(this,MainActivity::class.java).putExtra("finish_timer",s.taskId).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        return NotificationCompat.Builder(this,"focus").setSmallIcon(dev.planneros.android.R.drawable.ic_notification).setContentTitle(s.title)
            .setContentText("${timerText(TimerStore.remaining(this,s))} · ${if(s.running) "Focusing" else "Paused"}")
            .setOngoing(true).setOnlyAlertOnce(true).setSilent(true).setContentIntent(open)
            .addAction(0,if(s.running) "Pause" else "Resume",action("TOGGLE",2)).addAction(0,"Finish",finish).build()
    }
    private fun dp(value:Int)=(value*resources.displayMetrics.density).toInt()
    private fun darkMode():Boolean=when(getSharedPreferences("appearance",MODE_PRIVATE).getString("theme","system")){
        "dark"->true;"light"->false;else->(resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK)==Configuration.UI_MODE_NIGHT_YES
    }
    private fun label(text:String,size:Float)=TextView(this).apply{this.text=text;textSize=size;setTextColor(if(darkMode())Color.rgb(247,242,245)else Color.rgb(41,42,53));setPadding(dp(8),dp(4),dp(8),dp(4))}
    private fun showBubble(s:TimerState){
        val dark=darkMode()
        if(bubble!=null){if(bubbleDark==dark)return else removeBubble()}
        val wine=if(dark)Color.rgb(242,134,168)else Color.rgb(163,44,83)
        val box=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;elevation=dp(8).toFloat();padding(dp(6));background=GradientDrawable().apply{setColor(if(dark)Color.rgb(32,33,39)else Color.WHITE);setStroke(dp(1),wine);cornerRadius=dp(16).toFloat()}}
        val title=label(s.title.take(32),13f).apply{typeface=Typeface.DEFAULT_BOLD}
        titleView=title
        timeView=label(timerText(TimerStore.remaining(this,s)),26f).apply{typeface=Typeface.MONOSPACE;setTextColor(wine)}
        val buttons=LinearLayout(this)
        toggleView=label("Ⅱ Pause",12f).apply{minimumHeight=dp(48);minimumWidth=dp(64);gravity=Gravity.CENTER;setOnClickListener{TimerStore.action(this@TimerService,"TOGGLE")}}
        val finish=label("✓ Finish",12f).apply{minimumHeight=dp(48);minimumWidth=dp(64);gravity=Gravity.CENTER;setOnClickListener{val launch=Intent(this@TimerService,MainActivity::class.java).putExtra("finish_timer",s.taskId).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP);startActivity(launch)}}
        val close=label("×",18f).apply{minimumHeight=dp(48);minimumWidth=dp(48);gravity=Gravity.CENTER;contentDescription="Hide floating timer, keep timer running";setOnClickListener{hidden=true;removeBubble()}}
        buttons.addView(toggleView);buttons.addView(finish);buttons.addView(close)
        box.addView(title);box.addView(timeView);box.addView(buttons)
        val position=getSharedPreferences("focus",MODE_PRIVATE)
        val p=WindowManager.LayoutParams(WindowManager.LayoutParams.WRAP_CONTENT,WindowManager.LayoutParams.WRAP_CONTENT,WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,PixelFormat.TRANSLUCENT).apply{gravity=Gravity.TOP or Gravity.START;x=position.getInt("bubble_x",dp(12)).coerceIn(0,(resources.displayMetrics.widthPixels-dp(200)).coerceAtLeast(0));y=position.getInt("bubble_y",dp(90)).coerceIn(0,(resources.displayMetrics.heightPixels-dp(180)).coerceAtLeast(0))}
        var startX=0;var startY=0;var touchX=0f;var touchY=0f
        val drag=View.OnTouchListener{view,event->when(event.action){MotionEvent.ACTION_DOWN->{startX=p.x;startY=p.y;touchX=event.rawX;touchY=event.rawY;true};MotionEvent.ACTION_MOVE->{p.x=(startX+event.rawX-touchX).toInt().coerceIn(0,(resources.displayMetrics.widthPixels-box.width).coerceAtLeast(0));p.y=(startY+event.rawY-touchY).toInt().coerceIn(0,(resources.displayMetrics.heightPixels-box.height).coerceAtLeast(0));runCatching{windows.updateViewLayout(box,p)};true};MotionEvent.ACTION_UP->{position.edit().putInt("bubble_x",p.x).putInt("bubble_y",p.y).apply();if(kotlin.math.abs(event.rawX-touchX)<dp(4)&&kotlin.math.abs(event.rawY-touchY)<dp(4))view.performClick();true};else->true}}
        title.setOnClickListener{startActivity(Intent(this,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP))};timeView?.setOnClickListener{title.performClick()};title.setOnTouchListener(drag);timeView?.setOnTouchListener(drag)
        try{windows.addView(box,p);bubble=box;bubbleDark=dark}catch(_:SecurityException){removeBubble()}catch(_:WindowManager.BadTokenException){removeBubble()}
    }
    private fun LinearLayout.padding(value:Int){setPadding(value,value,value,value)}
    private fun removeBubble(){bubble?.let{runCatching{windows.removeView(it)}};bubble=null;timeView=null;toggleView=null;titleView=null;bubbleDark=null}
    override fun onDestroy(){handler.removeCallbacks(ticker);removeBubble();super.onDestroy()}
    companion object{const val FOCUS_ID=51}
}
