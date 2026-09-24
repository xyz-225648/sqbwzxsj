package com.sqzytc.timetable;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;

/**
 * 前台服务：让进程在后台不被系统回收，页面里的提醒定时器才能一直跑（issue IKHWKA #4）。
 * 只做一件事——挂一条常驻通知把进程钉住；提醒逻辑仍在页面里。
 */
public class KeepAliveService extends Service {

    public static final String CHANNEL_ID = "sqzy_keepalive";
    private static final int NOTICE_ID = 8801;

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        startForeground(NOTICE_ID, buildNotice());
        return START_STICKY;      /* 被系统杀掉后尽量自己起来 */
    }

    private Notification buildNotice() {
        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && nm != null
                && nm.getNotificationChannel(CHANNEL_ID) == null) {
            NotificationChannel ch = new NotificationChannel(
                    CHANNEL_ID, "后台常驻", NotificationManager.IMPORTANCE_MIN);
            ch.setDescription("保持课表提醒在后台运行（可随时在设置里关掉）");
            nm.createNotificationChannel(ch);
        }
        Intent open = new Intent(this, MainActivity.class);
        open.setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP);
        int piFlags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= 23) {
            piFlags |= PendingIntent.FLAG_IMMUTABLE;
        }
        PendingIntent pi = PendingIntent.getActivity(this, 0, open, piFlags);

        Notification.Builder b;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            b = new Notification.Builder(this, CHANNEL_ID);
        } else {
            b = new Notification.Builder(this);
        }
        b.setContentTitle("课表提醒运行中")
         .setContentText("点这里回到时间表；不需要的话在设置里关掉「后台常驻」")
         .setSmallIcon(R.mipmap.ic_launcher)
         .setContentIntent(pi)
         .setOngoing(true);
        return b.build();
    }
}
