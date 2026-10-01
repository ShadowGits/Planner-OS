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
        val j=JSONObject(it);val saved=TimerState(j.getString("id"),j.getString("title"),j.getLong("duration"),j.getLong("elapsed"),j.getLong("anchor"),j.getLong("wall"),j.getInt("boot"),j.getBoolean("running"))
        // Upgrading an already expired old timer must not play a retrospective tone.
        saved.copy(completionAlerted=j.optBoolean("completion_alerted",saved.remaining(SystemClock.elapsedRealtime(),System.currentTimeMillis(),boot(c))<=0))
    }.getOrNull()}
    fun save(c:Context,s:TimerState?){val p=c.getSharedPreferences("focus",Context.MODE_PRIVATE).edit();if(s==null)p.remove("state").putString("epoch",java.util.UUID.randomUUID().toString()) else p.putString("state",JSONObject().put("id",s.taskId).put("title",s.title).put("duration",s.durationMs).put("elapsed",s.elapsedBeforeMs).put("anchor",s.anchorElapsedMs).put("wall",s.anchorWallMs).put("boot",s.bootCount).put("running",s.running).put("completion_alerted",s.completionAlerted).toString());p.commit()}
    fun remaining(c:Context,s:TimerState)=s.remaining(SystemClock.elapsedRealtime(),System.currentTimeMillis(),boot(c))
    fun start(c:Context,t:Task){val i=intent(c,"START").putExtra("id",t.id).putExtra("title",t.title).putExtra("minutes",t.minutes);c.startForegroundService(i)}
    fun action(c:Context,action:String){c.startForegroundService(intent(c,action))}
    fun reset(c:Context){
        // No new foreground service is started merely to stop the old one.
        save(c,null)
        c.stopService(Intent(c,TimerService::class.java))
        c.getSystemService(NotificationManager::class.java).cancel(TimerService.FOCUS_ID);TimerSounds.clear(c)
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
    private var dialView:StopwatchDialView?=null
    private var toggleView:TextView?=null
    private var titleView:TextView?=null
    private var bubbleDark:Boolean?=null
    private lateinit var windows:WindowManager
    private var hidden=false
    private val ticker=object:Runnable{override fun run(){
        var s=state?:return
        s.claimCompletion(SystemClock.elapsedRealtime(),System.currentTimeMillis(),TimerStore.boot(this@TimerService))?.let{finished->
            s=finished;state=finished;TimerStore.save(this@TimerService,finished);TimerSounds.completed(this@TimerService,finished)
        }
        if(bubble!=null&&!Settings.canDrawOverlays(this@TimerService))removeBubble()
        titleView?.text=s.title;dialView?.display(s,TimerStore.remaining(this@TimerService,s));toggleView?.text=if(s.running)"Ⅱ Pause" else "▶ Resume"
        getSystemService(NotificationManager::class.java).notify(FOCUS_ID,notification(s));handler.postDelayed(this,1000)
    }}
    override fun onCreate(){
        super.onCreate();TimerSounds.setup(this);windows=getSystemService(WindowManager::class.java)
        val manager=getSystemService(NotificationManager::class.java)
        val previous=manager.getNotificationChannel("focus")
        // LOW can disappear entirely from the lockscreen. A new channel is
        // needed because Android does not let an app raise an existing channel.
        // Carry forward an explicit user restriction from the old channel.
        val importance=if(previous!=null&&(previous.importance==NotificationManager.IMPORTANCE_NONE||(Build.VERSION.SDK_INT>=29&&previous.hasUserSetImportance())))previous.importance else NotificationManager.IMPORTANCE_DEFAULT
        manager.createNotificationChannel(NotificationChannel(FOCUS_CHANNEL,"Focus timer",importance).apply{
            lockscreenVisibility=Notification.VISIBILITY_PUBLIC;setSound(null,null);enableVibration(false);setShowBadge(false)
        })
    }
    override fun onBind(intent:Intent?)=null
    override fun onStartCommand(intent:Intent?,flags:Int,startId:Int):Int{
        // A queued action from a prior connection or already-ended timer
        // must not restore that old task after a settings change or STOP.
        val automatic=if(intent?.action=="AUTO_START")AutoFocusScheduler.claim(this,intent)else null
        if(intent?.action=="AUTO_START"&&automatic==null){if(state==null)stopSelf();return if(state==null)START_NOT_STICKY else START_STICKY}
        if(intent!=null&&intent.action!="AUTO_START"&&!TimerStore.accepts(this,intent)){
            if(state==null){stopSelf();return START_NOT_STICKY}
            return START_STICKY
        }
        state=state?:TimerStore.read(this)
        state=state?.recover(SystemClock.elapsedRealtime(),System.currentTimeMillis(),TimerStore.boot(this))
        // Adjacent blocks can arrive before the next tick. Claim the old end
        // event before replacement so its completion tone is never lost.
        val nextId=if(intent?.action=="AUTO_START")automatic?.id else if(intent?.action=="START")intent.getStringExtra("id") else null
        var adjacentCompletion=false
        if(nextId!=null&&state?.taskId!=nextId){
            state?.claimCompletion(SystemClock.elapsedRealtime(),System.currentTimeMillis(),TimerStore.boot(this))?.let{
                state=it;TimerStore.save(this,it);TimerSounds.completed(this,it);adjacentCompletion=true
            }
        }
        var newTimer=false
        when(intent?.action){
            "AUTO_START"->{val block=automatic!!
                if(state?.taskId!=block.id){newTimer=true;val now=System.currentTimeMillis();state=TimerState(block.id,block.title,block.endMillis-block.startMillis,elapsedBeforeMs=block.elapsed(now),anchorElapsedMs=SystemClock.elapsedRealtime(),anchorWallMs=now,bootCount=TimerStore.boot(this));hidden=false;removeBubble()}
            }
            "START"->{val id=intent.getStringExtra("id")?:return START_NOT_STICKY
                // Starting an already active block keeps its elapsed time.
                AutoFocusScheduler.suppressTask(this,id)
                val title=intent.getStringExtra("title")?:"Focus"
                val duration=intent.getIntExtra("minutes",30).coerceIn(1,1440).toLong()*60_000
                if(state?.taskId!=id){newTimer=true;state=TimerState(id,title,duration,anchorElapsedMs=SystemClock.elapsedRealtime(),anchorWallMs=System.currentTimeMillis(),bootCount=TimerStore.boot(this));hidden=false;removeBubble()}
                else state=state?.metadata(title,duration)}
            "UPDATE"->{if(state?.taskId==intent.getStringExtra("id"))state=state?.metadata(intent.getStringExtra("title")?:state!!.title,intent.getIntExtra("minutes",30).coerceIn(1,1440).toLong()*60_000)}
            "TOGGLE"->{state?.let{AutoFocusScheduler.suppressTask(this,it.taskId)};state=state?.toggle(SystemClock.elapsedRealtime(),System.currentTimeMillis(),TimerStore.boot(this))}
            "STOP"->{state?.let{AutoFocusScheduler.suppressTask(this,it.taskId)};TimerStore.save(this,null);TimerSounds.clear(this);state=null;removeBubble();stopForeground(STOP_FOREGROUND_REMOVE);stopSelf();return START_NOT_STICKY}
            "SHOW"->{hidden=false}
        }
        val s=state?:run{stopSelf();return START_NOT_STICKY}
        TimerStore.save(this,s);startForeground(FOCUS_ID,notification(s));if(!hidden&&Settings.canDrawOverlays(this))showBubble(s)
        if(newTimer){
            if(adjacentCompletion){
                // Give the short completion bell room to finish before the new
                // block's start bell. A canceled/replaced timer cannot ring later.
                handler.postDelayed({if(state?.taskId==s.taskId&&state?.anchorElapsedMs==s.anchorElapsedMs)TimerSounds.started(this,s)},1200)
            }else TimerSounds.started(this,s)
        }
        handler.removeCallbacks(ticker);handler.post(ticker);return START_STICKY
    }
    private fun action(action:String,code:Int)=PendingIntent.getService(this,code,TimerStore.intent(this,action),PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    private fun notification(s:TimerState):Notification {
        val open=PendingIntent.getActivity(this,0,Intent(this,TimerLockScreenActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP),PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val finish=PendingIntent.getActivity(this,1,Intent(this,MainActivity::class.java).putExtra("finish_timer",s.taskId).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        return NotificationCompat.Builder(this,FOCUS_CHANNEL).setSmallIcon(dev.planneros.android.R.drawable.ic_notification).setContentTitle(s.title)
            .setContentText("${timerText(TimerStore.remaining(this,s))} · ${if(s.running) "Focusing" else "Paused"}")
            .setOngoing(true).setOnlyAlertOnce(true).setContentIntent(open)
            .setCategory("stopwatch").setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            // The documented stable key is public in SDK 36.1; using its value
            // keeps compileSdk 36 compatible and older systems ignore it.
            .addExtras(Bundle().apply{if(Build.VERSION.SDK_INT>=36)putBoolean("android.requestPromotedOngoing",true)})
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setWhen(System.currentTimeMillis()+TimerStore.remaining(this,s).coerceAtLeast(0))
            .setUsesChronometer(s.running&&TimerStore.remaining(this,s)>0).setChronometerCountDown(true)
            .setShowWhen(s.running&&TimerStore.remaining(this,s)>0)
            .addAction(0,if(s.running) "Pause" else "Resume",action("TOGGLE",2))
            .addAction(0,"Cancel timer",action("STOP",3)).addAction(0,"Finish",finish).build()
    }
    private fun dp(value:Int)=(value*resources.displayMetrics.density).toInt()
    private fun darkMode():Boolean=when(getSharedPreferences("appearance",MODE_PRIVATE).getString("theme","system")){
        "dark"->true;"light"->false;else->(resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK)==Configuration.UI_MODE_NIGHT_YES
    }
    private fun label(text:String,size:Float)=TextView(this).apply{this.text=text;textSize=size;setTextColor(if(darkMode())Color.rgb(247,242,245)else Color.rgb(41,42,53));setPadding(dp(8),dp(4),dp(8),dp(4))}
    private fun showBubble(s:TimerState){
        val dark=darkMode()
        if(bubble!=null){if(bubbleDark==dark)return else removeBubble()}
        val wine=if(dark)Color.rgb(210,165,112)else Color.rgb(128,80,47)
        val box=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;elevation=dp(10).toFloat();padding(dp(8));background=GradientDrawable().apply{setColor(if(dark)Color.rgb(40,32,26)else Color.rgb(255,251,245));setStroke(dp(1),wine);cornerRadius=dp(16).toFloat()}}
        val title=label(s.title,13f).apply{typeface=Typeface.DEFAULT_BOLD;maxLines=2;ellipsize=android.text.TextUtils.TruncateAt.END;maxWidth=dp(176)}
        titleView=title
        dialView=StopwatchDialView(this).apply{palette(dark);display(s,TimerStore.remaining(this@TimerService,s))}
        val buttons=LinearLayout(this)
        toggleView=label("Ⅱ Pause",11f).apply{minimumHeight=dp(48);minimumWidth=dp(64);gravity=Gravity.CENTER;setOnClickListener{TimerStore.action(this@TimerService,"TOGGLE")}}
        val finish=label("✓ Finish",11f).apply{minimumHeight=dp(48);minimumWidth=dp(64);gravity=Gravity.CENTER;setOnClickListener{val launch=Intent(this@TimerService,MainActivity::class.java).putExtra("finish_timer",s.taskId).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP);startActivity(launch)}}
        val cancel=label("Cancel",11f).apply{minimumHeight=dp(48);minimumWidth=dp(60);gravity=Gravity.CENTER;contentDescription="Cancel timer without completing task";setOnClickListener{TimerStore.action(this@TimerService,"STOP")}}
        val close=label("×",18f).apply{minimumHeight=dp(48);minimumWidth=dp(48);gravity=Gravity.CENTER;contentDescription="Hide floating timer, keep timer running";setOnClickListener{hidden=true;removeBubble()}}
        buttons.addView(toggleView);buttons.addView(cancel);buttons.addView(finish)
        val header=LinearLayout(this).apply{gravity=Gravity.CENTER_VERTICAL;addView(title,LinearLayout.LayoutParams(0,LinearLayout.LayoutParams.WRAP_CONTENT,1f));addView(close)}
        box.addView(header);box.addView(dialView);box.addView(buttons)
        val position=getSharedPreferences("focus",MODE_PRIVATE)
        val p=WindowManager.LayoutParams(WindowManager.LayoutParams.WRAP_CONTENT,WindowManager.LayoutParams.WRAP_CONTENT,WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,PixelFormat.TRANSLUCENT).apply{gravity=Gravity.TOP or Gravity.START;x=position.getInt("bubble_x",dp(12)).coerceIn(0,(resources.displayMetrics.widthPixels-dp(200)).coerceAtLeast(0));y=position.getInt("bubble_y",dp(90)).coerceIn(0,(resources.displayMetrics.heightPixels-dp(180)).coerceAtLeast(0))}
        var startX=0;var startY=0;var touchX=0f;var touchY=0f
        val drag=View.OnTouchListener{view,event->when(event.action){MotionEvent.ACTION_DOWN->{startX=p.x;startY=p.y;touchX=event.rawX;touchY=event.rawY;true};MotionEvent.ACTION_MOVE->{p.x=(startX+event.rawX-touchX).toInt().coerceIn(0,(resources.displayMetrics.widthPixels-box.width).coerceAtLeast(0));p.y=(startY+event.rawY-touchY).toInt().coerceIn(0,(resources.displayMetrics.heightPixels-box.height).coerceAtLeast(0));runCatching{windows.updateViewLayout(box,p)};true};MotionEvent.ACTION_UP->{position.edit().putInt("bubble_x",p.x).putInt("bubble_y",p.y).apply();if(kotlin.math.abs(event.rawX-touchX)<dp(4)&&kotlin.math.abs(event.rawY-touchY)<dp(4))view.performClick();true};else->true}}
        title.setOnClickListener{startActivity(Intent(this,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP))};dialView?.setOnClickListener{title.performClick()};title.setOnTouchListener(drag);dialView?.setOnTouchListener(drag)
        try{windows.addView(box,p);bubble=box;bubbleDark=dark}catch(_:SecurityException){removeBubble()}catch(_:WindowManager.BadTokenException){removeBubble()}
    }
    private fun LinearLayout.padding(value:Int){setPadding(value,value,value,value)}
    private fun removeBubble(){bubble?.let{runCatching{windows.removeView(it)}};bubble=null;dialView=null;toggleView=null;titleView=null;bubbleDark=null}
    override fun onDestroy(){handler.removeCallbacksAndMessages(null);state=null;removeBubble();super.onDestroy()}
    companion object{const val FOCUS_ID=51;const val FOCUS_CHANNEL="focus-timer"}
}
