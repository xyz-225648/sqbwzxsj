package com.sqzytc.timetable;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** 开机自启：开机后把前台服务拉起来（issue IKHWKA #4） */
public class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        try {
            context.startForegroundService(new Intent(context, KeepAliveService.class));
        } catch (Exception ignored) {
        }
    }
}
