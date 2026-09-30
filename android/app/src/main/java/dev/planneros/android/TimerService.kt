package dev.planneros.android

import android.app.*
import android.content.*
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.*
import android.provider.Settings
import android.view.*
import android.widget.*
import androidx.core.app.NotificationCompat
import org.json.JSONObject

object TimerStore {
    fun boot(c:Context)=Settings.Global.getInt(c.contentResolver,Settings.Global.BOOT_COUNT,0)
    fun read(c:Context):TimerState?= c.getSharedPreferences("focus",Context.MODE_PRIVATE).getString("state",null)?.let{runCatching{
        val j=JSONObject(it); TimerState(j.getString("id"),j.getString("title"),j.getLong("duration"),j.getLong("elapsed"),j.getLong("anchor"),j.getLong("wall"),j.getInt("boot"),j.getBoolean("running"))
    }.getOrNull()}
    fun save(c:Context,s:TimerState?){val p=c.getSharedPreferences("focus",Context.MODE_PRIVATE).edit();if(s==null)p.remove("state") else p.putString("state",JSONObject().put("id",s.taskId).put("title",s.title).put("duration",s.durationMs).put("elapsed",s.elapsedBeforeMs).put("anchor",s.anchorElapsedMs).put("wall",s.anchorWallMs).put("boot",s.bootCount).put("running",s.running).toString());p.commit()}
    fun remaining(c:Context,s:TimerState)=s.remaining(SystemClock.elapsedRealtime(),System.currentTimeMillis(),boot(c))
    fun start(c:Context,t:Task){val i=Intent(c,TimerService::class.java).setAction("START").putExtra("id",t.id).putExtra("title",t.title).putExtra("minutes",t.minutes);c.startForegroundService(i)}
    fun action(c:Context,action:String){c.startForegroundService(Intent(c,TimerService::class.java).setAction(action))}
}

class TimerService:Service(){
    private val handler=Handler(Looper.getMainLooper())
    private var state:TimerState?=null
    private var bubble:LinearLayout?=null
    private var timeView:TextView?=null
    private var toggleView:TextView?=null
    private lateinit var windows:WindowManager
    private var hidden=false
    private val ticker=object:Runnable{override fun run(){val s=state?:return;timeView?.text=timerText(TimerStore.remaining(this@TimerService,s));toggleView?.text=if(s.running) "Ⅱ Pause" else "▶ Resume";getSystemService(NotificationManager::class.java).notify(FOCUS_ID,notification(s));handler.postDelayed(this,1000)}}
    override fun onCreate(){super.onCreate();windows=getSystemService(WindowManager::class.java);getSystemService(NotificationManager::class.java).createNotificationChannel(NotificationChannel("focus","Focus timer",NotificationManager.IMPORTANCE_LOW))}
    override fun onBind(intent:Intent?)=null
    override fun onStartCommand(intent:Intent?,flags:Int,startId:Int):Int{
        state=state?:TimerStore.read(this)
        when(intent?.action){
            "START"->{val id=intent.getStringExtra("id")?:return START_NOT_STICKY
                // Starting an already active block keeps its elapsed time.
                if(state?.taskId!=id){state=TimerState(id,intent.getStringExtra("title")?:"Focus",intent.getIntExtra("minutes",30).toLong()*60_000,anchorElapsedMs=SystemClock.elapsedRealtime(),anchorWallMs=System.currentTimeMillis(),bootCount=TimerStore.boot(this));hidden=false;removeBubble()}}
            "TOGGLE"->state=state?.toggle(SystemClock.elapsedRealtime(),System.currentTimeMillis(),TimerStore.boot(this))
            "STOP"->{TimerStore.save(this,null);state=null;removeBubble();stopForeground(STOP_FOREGROUND_REMOVE);stopSelf();return START_NOT_STICKY}
            "SHOW"->{hidden=false}
        }
        val s=state?:run{stopSelf();return START_NOT_STICKY}
        TimerStore.save(this,s);startForeground(FOCUS_ID,notification(s));if(!hidden&&Settings.canDrawOverlays(this))showBubble(s)
        handler.removeCallbacks(ticker);handler.post(ticker);return START_STICKY
    }
    private fun action(action:String,code:Int)=PendingIntent.getService(this,code,Intent(this,TimerService::class.java).setAction(action),PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    private fun notification(s:TimerState):Notification {
        val open=PendingIntent.getActivity(this,0,Intent(this,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val finish=PendingIntent.getActivity(this,1,Intent(this,MainActivity::class.java).putExtra("finish_timer",s.taskId).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        return NotificationCompat.Builder(this,"focus").setSmallIcon(dev.planneros.android.R.drawable.ic_notification).setContentTitle(s.title)
            .setContentText("${timerText(TimerStore.remaining(this,s))} · ${if(s.running) "Focusing" else "Paused"}")
            .setOngoing(true).setOnlyAlertOnce(true).setSilent(true).setContentIntent(open)
            .addAction(0,if(s.running) "Pause" else "Resume",action("TOGGLE",2)).addAction(0,"Finish",finish).build()
    }
    private fun label(text:String,size:Float)=TextView(this).apply{this.text=text;textSize=size;setTextColor(Color.rgb(41,42,53));setPadding(16,8,16,8)}
    private fun showBubble(s:TimerState){
        if(bubble!=null)return
        val box=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;elevation=12f;padding(6);background=GradientDrawable().apply{setColor(Color.WHITE);setStroke(2,Color.rgb(222,209,255));cornerRadius=22f}}
        val title=label(s.title.take(32),13f).apply{typeface=Typeface.DEFAULT_BOLD}
        timeView=label(timerText(TimerStore.remaining(this,s)),26f).apply{typeface=Typeface.MONOSPACE;setTextColor(Color.rgb(140,99,236))}
        val buttons=LinearLayout(this)
        toggleView=label("Ⅱ Pause",12f).apply{setOnClickListener{TimerStore.action(this@TimerService,"TOGGLE")}}
        val finish=label("✓ Finish",12f).apply{setOnClickListener{val launch=Intent(this@TimerService,MainActivity::class.java).putExtra("finish_timer",s.taskId).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP);startActivity(launch)}}
        val close=label("×",18f).apply{contentDescription="Hide floating timer, keep timer running";setOnClickListener{hidden=true;removeBubble()}}
        buttons.addView(toggleView);buttons.addView(finish);buttons.addView(close)
        box.addView(title);box.addView(timeView);box.addView(buttons)
        val p=WindowManager.LayoutParams(WindowManager.LayoutParams.WRAP_CONTENT,WindowManager.LayoutParams.WRAP_CONTENT,WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,PixelFormat.TRANSLUCENT).apply{gravity=Gravity.TOP or Gravity.START;x=24;y=180}
        var startX=0;var startY=0;var touchX=0f;var touchY=0f
        val drag=View.OnTouchListener{view,event->when(event.action){MotionEvent.ACTION_DOWN->{startX=p.x;startY=p.y;touchX=event.rawX;touchY=event.rawY;true};MotionEvent.ACTION_MOVE->{p.x=(startX+event.rawX-touchX).toInt().coerceIn(0,(resources.displayMetrics.widthPixels-box.width).coerceAtLeast(0));p.y=(startY+event.rawY-touchY).toInt().coerceIn(0,(resources.displayMetrics.heightPixels-box.height).coerceAtLeast(0));runCatching{windows.updateViewLayout(box,p)};true};MotionEvent.ACTION_UP->{if(kotlin.math.abs(event.rawX-touchX)<8&&kotlin.math.abs(event.rawY-touchY)<8)view.performClick();true};else->true}}
        title.setOnClickListener{startActivity(Intent(this,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP))};timeView?.setOnClickListener{title.performClick()};title.setOnTouchListener(drag);timeView?.setOnTouchListener(drag)
        try{windows.addView(box,p);bubble=box}catch(_:SecurityException){bubble=null}
    }
    private fun LinearLayout.padding(value:Int){setPadding(value,value,value,value)}
    private fun removeBubble(){bubble?.let{runCatching{windows.removeView(it)}};bubble=null;timeView=null;toggleView=null}
    override fun onDestroy(){handler.removeCallbacks(ticker);removeBubble();super.onDestroy()}
    companion object{const val FOCUS_ID=51}
}
