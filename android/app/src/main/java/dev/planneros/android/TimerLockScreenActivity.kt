package dev.planneros.android

import android.app.Activity
import android.app.KeyguardManager
import android.content.Intent
import android.content.res.Configuration
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView

/** User-opened timer surface above keyguard; opening the planner still requires unlock. */
class TimerLockScreenActivity : Activity() {
    private val handler=Handler(Looper.getMainLooper())
    private lateinit var title:TextView
    private lateinit var status:TextView
    private lateinit var pause:Button
    private lateinit var dial:StopwatchDialView
    private val refresh=object:Runnable{override fun run(){
        val state=TimerStore.read(this@TimerLockScreenActivity)?:run{finish();return}
        title.text=state.title
        status.text=if(state.running)"Focus timer" else "Timer paused"
        pause.text=if(state.running)"Pause" else "Resume"
        dial.display(state,TimerStore.remaining(this@TimerLockScreenActivity,state))
        handler.postDelayed(this,1000)
    }}
    override fun onCreate(savedInstanceState:Bundle?){
        super.onCreate(savedInstanceState)
        if(android.os.Build.VERSION.SDK_INT>=27)setShowWhenLocked(true)
        else window.addFlags(android.view.WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED)
        val dark=when(getSharedPreferences("appearance",MODE_PRIVATE).getString("theme","system")){
            "dark"->true;"light"->false
            else->(resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK)==Configuration.UI_MODE_NIGHT_YES
        }
        val brown=if(dark)Color.rgb(210,165,112)else Color.rgb(128,80,47)
        val ink=if(dark)Color.rgb(255,245,228)else Color.rgb(60,43,31)
        val background=if(dark)Color.rgb(40,32,26)else Color.rgb(255,251,245)
        window.statusBarColor=background
        window.navigationBarColor=background
        val box=LinearLayout(this).apply{
            orientation=LinearLayout.VERTICAL;gravity=Gravity.CENTER
            setPadding(dp(24),dp(40),dp(24),dp(40));setBackgroundColor(background)
        }
        title=TextView(this).apply{
            textSize=24f;setTextColor(ink);gravity=Gravity.CENTER
            typeface=Typeface.DEFAULT_BOLD;maxLines=3
        }
        status=TextView(this).apply{textSize=14f;setTextColor(brown);gravity=Gravity.CENTER;setPadding(0,dp(12),0,dp(12))}
        dial=StopwatchDialView(this).apply{palette(dark)}
        fun button(label:String,action:()->Unit)=Button(this).apply{
            text=label;isAllCaps=false;textSize=15f;setTextColor(ink)
            minimumHeight=dp(48);setPadding(dp(16),dp(8),dp(16),dp(8))
            this.background=GradientDrawable().apply{
                setColor(if(dark)Color.rgb(55,44,35)else Color.rgb(242,232,217))
                setStroke(dp(1),brown);cornerRadius=dp(12).toFloat()
            }
            setOnClickListener{action()}
        }
        pause=button("Pause"){TimerStore.action(this,"TOGGLE");handler.removeCallbacks(refresh);handler.postDelayed(refresh,100)}
        val cancel=button("Cancel timer"){TimerStore.action(this,"STOP");finish()}
        val controls=LinearLayout(this).apply{
            gravity=Gravity.CENTER
            addView(pause,LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1f).apply{marginEnd=dp(6)})
            addView(cancel,LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1f).apply{marginStart=dp(6)})
        }
        box.addView(title,LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT))
        box.addView(status)
        box.addView(dial)
        box.addView(controls,LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT).apply{topMargin=dp(24)})
        box.addView(button("Open planner"){openPlanner()},LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT).apply{topMargin=dp(12)})
        setContentView(box)
    }
    private fun openPlanner(){
        val keyguard=getSystemService(KeyguardManager::class.java)
        if(!keyguard.isKeyguardLocked){launchPlanner();return}
        keyguard.requestDismissKeyguard(this,object:KeyguardManager.KeyguardDismissCallback(){
            override fun onDismissSucceeded(){launchPlanner()}
        })
    }
    private fun launchPlanner(){
        startActivity(Intent(this,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP))
        finish()
    }
    override fun onResume(){super.onResume();handler.removeCallbacks(refresh);handler.post(refresh)}
    override fun onPause(){handler.removeCallbacks(refresh);super.onPause()}
    override fun onDestroy(){handler.removeCallbacksAndMessages(null);super.onDestroy()}
    private fun dp(value:Int)=(value*resources.displayMetrics.density).toInt()
}
