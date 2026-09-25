package com.sqzytc.timetable;

import android.app.Activity;
import android.content.IntentFilter;
import android.content.BroadcastReceiver;
import android.app.DownloadManager;
import android.app.Notification;
import android.app.PendingIntent;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Intent;
import android.content.Context;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.Settings;
import android.net.Uri;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.util.Log;
import android.view.KeyEvent;
import android.view.ViewGroup;
import android.webkit.JavascriptInterface;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;

public class MainActivity extends Activity {
    /* 一键更新：记住最近一次下载的 id，完成时自动拉起安装界面 */
    private long lastDownloadId = -1L;
    private String lastApkName = null;
    private BroadcastReceiver dlDone = null;

    // ==================== 自动更新配置 ====================
    // 码云仓库的 raw 地址（结尾带 /），留空表示关闭自动更新。
    // 例：private static final String UPDATE_BASE = "https://gitee.com/zhangsan/sqzy-timetable/raw/master/";
    private static final String UPDATE_BASE = "https://gitee.com/xyz-225648/sqbwzxsj/raw/master/";
    private static final int TIMEOUT_MS = 8000;
    private static final String UA =
            "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) " +
            "Chrome/120.0.0.0 Mobile Safari/537.36";
    private static final String[] MARKERS = {"宿迁职业技术学院作息时间表", "<html"};
    private static final int MIN_HTML = 5000;
    private static final String BASE_URL = "https://gitee.com/";
    /* 页面本体的备用来源（见 pageUrls）：发行版附件 + 码云 contents API */
    private static final String RELEASE_DL = "https://gitee.com/xyz-225648/sqbwzxsj/releases/download/";
    private static final String API_PAGE =
            "https://gitee.com/api/v5/repos/xyz-225648/sqbwzxsj/contents/index.html?ref=master";
    private static final java.util.regex.Pattern API_CONTENT =
            java.util.regex.Pattern.compile("\"content\"\\s*:\\s*\"([^\"]+)\"");
    private static final java.util.regex.Pattern VER_IN_LATEST =
            java.util.regex.Pattern.compile("\"v\"\\s*:\\s*\"(v?[0-9.]+)\"");

    private WebView web;
    private volatile boolean alive = true;
    private static final String CHANNEL_ID = "sqzy_timetable";
    /* 原子自增：原来的 timeMillis()%500 会撞号，两条提醒互相顶掉 */
    private static final java.util.concurrent.atomic.AtomicInteger NEXT_ID =
            new java.util.concurrent.atomic.AtomicInteger(8800);

    /** 暴露给网页：window.SQZY_ANDROID.notify(标题, 内容) */
    public class WebBridge {
        @JavascriptInterface
        public boolean notify(String title, String body) {
            return postNotification(title, body);
        }

        @JavascriptInterface
        public boolean nativeNotifyAvailable() {
            return true;
        }

        @JavascriptInterface
        public String platform() {
            return "android";
        }

        /** 页面读远程文本（版本文件）：HttpURLConnection 不看 MIME、不受 CORS 限制，
            正好绕开 gitee raw 的 text/plain + nosniff（issue IKHWKA #1） */
        @JavascriptInterface
        public String fetchUrl(String url) {
            if (url == null || !url.startsWith("https://gitee.com/")) {
                return null;
            }
            try {
                HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
                c.setInstanceFollowRedirects(true);
                c.setConnectTimeout(8000);
                c.setReadTimeout(8000);
                c.setRequestProperty("User-Agent", UA);
                if (c.getResponseCode() != 200) {
                    return null;
                }
                InputStream in = c.getInputStream();
                ByteArrayOutputStream bo = new ByteArrayOutputStream();
                byte[] buf = new byte[8192];
                int n;
                while ((n = in.read(buf)) > 0) {
                    bo.write(buf, 0, n);
                }
                in.close();
                c.disconnect();
                return new String(bo.toByteArray(), "UTF-8");
            } catch (Exception t) {
                return null;
            }
        }

        /** 一键下载并按「目标版本」命名（原来用当前安装版本命名，通知里看着像下错了版本） */
        @JavascriptInterface
        public String downloadApkAs(String url, String ver) {
            return downloadApk(url, ver);
        }

        /** 页内重载：切换作息后由页面调用，避免 location.reload() 被当成外链丢给系统浏览器 */
        @JavascriptInterface
        public void reloadPage() {
            runOnUiThread(new Runnable() {
                public void run() {
                    try { web.reload(); } catch (Exception ignored) { }
                }
            });
        }

        /** 分享安装包（#G）：把本机这份 apk 通过微信 / QQ / 蓝牙发给同学 */
        @JavascriptInterface
        public String shareApk() {
            try {
                final String name = "sqzy-timetable-" + version() + ".apk";
                File dir = new File(getCacheDir(), "share");
                if (!dir.exists() && !dir.mkdirs()) return "fail";
                File out = new File(dir, name);
                File src = new File(Environment.getExternalStoragePublicDirectory(
                        Environment.DIRECTORY_DOWNLOADS), name);
                if (!src.exists()) src = new File(getPackageCodePath());
                copyFile(src, out);
                final Intent it = new Intent(Intent.ACTION_SEND);
                it.setType("application/vnd.android.package-archive");
                it.putExtra(Intent.EXTRA_STREAM,
                        Uri.parse("content://com.sqzytc.timetable.files/" + name));
                it.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                runOnUiThread(new Runnable() {
                    public void run() {
                        startActivity(Intent.createChooser(it, "把安装包发给"));
                    }
                });
                return "ok";
            } catch (Exception t) {
                return "fail";
            }
        }

        private void copyFile(File src, File dst) throws Exception {
            java.io.InputStream in = new java.io.FileInputStream(src);
            java.io.OutputStream os = new java.io.FileOutputStream(dst);
            try {
                byte[] buf = new byte[8192];
                int n;
                while ((n = in.read(buf)) > 0) os.write(buf, 0, n);
            } finally {
                try { in.close(); } catch (Exception ignored) { }
                try { os.close(); } catch (Exception ignored) { }
            }
        }

        /** 一键后台下载安装包（#3）：交给系统 DownloadManager，下完点通知安装 */
        @JavascriptInterface
        public String downloadApk(String url) {
            return downloadApk(url, null);
        }

        public String downloadApk(String url, String ver) {
            final String tag = (ver == null || ver.isEmpty()) ? version() : ver.replace("v", "");
            try {
                if (url == null || !url.startsWith("https://gitee.com/")) {
                    return "bad-url";
                }
                DownloadManager dm = (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
                if (dm == null) {
                    return "no-dm";
                }
                String name = "sqzy-timetable-" + version() + ".apk";
                DownloadManager.Request req = new DownloadManager.Request(Uri.parse(url));
                lastApkName = name;
                req.setTitle("宿迁职业技术学院作息时间表 " + tag)
                   .setDescription("下载完成后点这条通知即可安装")
                   .setMimeType("application/vnd.android.package-archive")
                   .setNotificationVisibility(
                           DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                   .setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name);
                lastDownloadId = dm.enqueue(req);
                registerDownloadReceiver();
                return "ok";
            } catch (Exception t) {
                return "fail";
            }
        }

        /** 后台常驻开关（#4）：页面设置里可关 */
        @JavascriptInterface
        public void keepAlive(boolean on) {
            try {
                if (on) {
                    startForegroundService(new Intent(MainActivity.this, KeepAliveService.class));
                } else {
                    stopService(new Intent(MainActivity.this, KeepAliveService.class));
                }
            } catch (Exception ignored) {
            }
        }

        @JavascriptInterface
        public boolean ignoringBattery() {
            try {
                android.os.PowerManager pm =
                        (android.os.PowerManager) getSystemService(Context.POWER_SERVICE);
                return pm != null && pm.isIgnoringBatteryOptimizations(getPackageName());
            } catch (Exception t) {
                return false;
            }
        }

        /** 打开系统里本应用的详情页：各厂商的自启动/后台管理入口基本都从这里进 */
        @JavascriptInterface
        public void openAppSettings() {
            try {
                Intent it = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                        Uri.parse("package:" + getPackageName()));
                it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                startActivity(it);
            } catch (Exception ignored) {
            }
        }

        /** 请求加入电池优化白名单（被拒就退回列表页让用户自己选） */
        @JavascriptInterface
        public void requestIgnoreBattery() {
            try {
                if (Build.VERSION.SDK_INT >= 23) {
                    Intent it = new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                            Uri.parse("package:" + getPackageName()));
                    it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    startActivity(it);
                }
            } catch (Exception e) {
                try {
                    Intent it = new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS);
                    it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    startActivity(it);
                } catch (Exception ignored) {
                }
            }
        }

        /** 页面用它比对 program.txt，判断这个安装包本体是不是旧了 */
        @JavascriptInterface

        /** 下载完成后自动打开安装界面：把包从「下载」目录复制到缓存，再用 content:// 拉起系统安装器。
         *  为什么绕这一层：Android 7 起不允许用 file:// 安装（FileUriExposedException），必须走 ContentProvider。 */
        private void registerDownloadReceiver() {
            try {
                if (dlDone == null) {
                    dlDone = new BroadcastReceiver() {
                        public void onReceive(Context c, Intent i) {
                            try {
                                if (!DownloadManager.ACTION_DOWNLOAD_COMPLETE.equals(i.getAction())) return;
                                long id = i.getLongExtra(DownloadManager.EXTRA_DOWNLOAD_ID, -1L);
                                if (id != lastDownloadId) return;
                                DownloadManager dm = (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
                                DownloadManager.Query q = new DownloadManager.Query().setFilterById(id);
                                android.database.Cursor cur = dm.query(q);
                                if (cur == null || !cur.moveToFirst()) return;
                                int st = cur.getInt(cur.getColumnIndex(DownloadManager.COLUMN_STATUS));
                                cur.close();
                                if (st != DownloadManager.STATUS_SUCCESSFUL) return;
                                openInstaller();
                            } catch (Exception ignored) { }
                        }
                    };
                }
                IntentFilter f = new IntentFilter(DownloadManager.ACTION_DOWNLOAD_COMPLETE);
                if (Build.VERSION.SDK_INT >= 33) registerReceiver(dlDone, f, Context.RECEIVER_NOT_EXPORTED);
                else registerReceiver(dlDone, f);
            } catch (Exception ignored) { }
        }

        private void openInstaller() {
            try {
                File dir = new File(getCacheDir(), "share");
                if (!dir.exists() && !dir.mkdirs()) return;
                File src = new File(Environment.getExternalStoragePublicDirectory(
                        Environment.DIRECTORY_DOWNLOADS), lastApkName);
                if (!src.exists()) return;
                File out = new File(dir, lastApkName);
                copyFile(src, out);
                Intent it = new Intent(Intent.ACTION_VIEW);
                it.setDataAndType(Uri.parse("content://com.sqzytc.timetable.files/" + lastApkName),
                        "application/vnd.android.package-archive");
                it.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
                startActivity(it);
            } catch (Exception t) {
                try { openAppSettings(); } catch (Exception ignored) { }
            }
        }

        public String version() {
            try {
                return getPackageManager().getPackageInfo(getPackageName(), 0).versionName;
            } catch (Exception t) {
                return "";
            }
        }
    }

    private void ensureChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
            if (nm != null && nm.getNotificationChannel(CHANNEL_ID) == null) {
                NotificationChannel ch = new NotificationChannel(
                        CHANNEL_ID, "上课下课提醒", NotificationManager.IMPORTANCE_HIGH);
                ch.setDescription("课前/课后的时间提醒");
                nm.createNotificationChannel(ch);
            }
        }
    }

    @SuppressWarnings("deprecation")
    private boolean postNotification(String title, String body) {
        try {
            /* 安卓 13+ 必须先拿到通知权限，否则 notify() 会静默丢弃而我们却报成功 */
            if (Build.VERSION.SDK_INT >= 33
                    && checkSelfPermission("android.permission.POST_NOTIFICATIONS")
                       != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"}, 1001);
                return false;
            }
            ensureChannel();
            NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
            if (nm == null) {
                return false;
            }
            Notification.Builder b;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                b = new Notification.Builder(this, CHANNEL_ID);
            } else {
                b = new Notification.Builder(this);
            }
            // 点通知要能回到软件（issue IKHWKA #2）：以前没有 contentIntent，点了没反应
            Intent openApp = new Intent(this, MainActivity.class);
            openApp.setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP);
            int piFlags = PendingIntent.FLAG_UPDATE_CURRENT;
            if (Build.VERSION.SDK_INT >= 23) {
                piFlags |= PendingIntent.FLAG_IMMUTABLE;
            }
            b.setContentIntent(PendingIntent.getActivity(this, 0, openApp, piFlags))
             .setContentTitle(title == null ? "作息提醒" : title)
             .setContentText(body == null ? "" : body)
             .setSmallIcon(R.mipmap.ic_launcher)
             .setAutoCancel(true)
             .setDefaults(Notification.DEFAULT_ALL);
            try {
                /* 右侧大图标用校徽：小图标在安卓 5+ 会被系统涂成纯白剪影 */
                b.setLargeIcon(android.graphics.BitmapFactory.decodeResource(
                        getResources(), R.mipmap.ic_launcher));
            } catch (Exception ignored) {
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.JELLY_BEAN) {
                b.setStyle(new Notification.BigTextStyle().bigText(body == null ? "" : body));
            }
            nm.notify(NEXT_ID.getAndIncrement(), b.build());
            return true;
        } catch (Exception t) {
            return false;
        }
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(true);
        s.setAllowContentAccess(true);
        s.setBuiltInZoomControls(false);
        s.setSupportZoom(false);
        s.setTextZoom(100);
        web.setBackgroundColor(Color.parseColor("#f1f5f9"));
        web.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageFinished(WebView v, String url) {
                /* 页面是「HTML 文本 + 基地址」塞进去的，每次热替换都会多一条历史，
                   不清掉的话按返回键会退回到替换前那版界面 */
                v.clearHistory();
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView v, String url) {
                /* 下载链接（gitee / github）交给系统浏览器：WebView 里点开会把页面顶掉 */
                if (url != null && (url.startsWith("https://gitee.com/")
                        || url.startsWith("https://github.com/"))) {
                    try {
                        startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
                    } catch (Exception ignored) {
                    }
                    return true;
                }
                return false;
            }
        });

        // 本地缓存优先（可能是上次更新拿到的新版本），否则用内置版本 —— 秒开，不等网络。
        // 两条路都必须走 loadDataWithBaseURL：内置版如果用 file:// 打开，
        // 它的 origin 跟更新后的 https origin 不是同一个，localStorage（也就是设置）
        // 会分成两份；而且首次启动几乎马上就会被热替换掉，刚改的设置等于白改。
        String startHtml = readText(new File(getFilesDir(), "index.html"));
        if (!isValid(startHtml)) {
            startHtml = readAsset("index.html");
        }
        if (isValid(startHtml)) {
            web.loadDataWithBaseURL(BASE_URL, startHtml, "text/html", "utf-8", null);
        } else {
            web.loadUrl("file:///android_asset/index.html");
        }
        web.addJavascriptInterface(new WebBridge(), "SQZY_ANDROID");
        setContentView(web);

        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission("android.permission.POST_NOTIFICATIONS")
                   != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"}, 1001);
        }
        ensureChannel();
        // 默认开启后台常驻（#4）；页面设置里可以关
        try {
            startForegroundService(new Intent(this, KeepAliveService.class));
        } catch (Exception ignored) {
        }
        startUpdateCheck();
    }

    private void startUpdateCheck() {
        if (UPDATE_BASE == null || UPDATE_BASE.length() == 0) {
            return;
        }
        Thread t = new Thread(new Runnable() {
            @Override
            public void run() {
                doUpdateCheck();
            }
        });
        t.setDaemon(true);
        t.start();
    }

    /** master / main 两个分支都试一下，避免默认分支猜错导致更新失效 */
    private static String[] baseCandidates() {
        String b = UPDATE_BASE.endsWith("/") ? UPDATE_BASE : UPDATE_BASE + "/";
        if (b.contains("/master/")) {
            return new String[]{b, b.replace("/master/", "/main/")};
        }
        if (b.contains("/main/")) {
            return new String[]{b, b.replace("/main/", "/master/")};
        }
        return new String[]{b};
    }

    /** 后台线程：查版本 -> 下载新页面 -> 校验 -> 落盘 -> 回主线程热替换 */
    private void doUpdateCheck() {
        for (String base : baseCandidates()) {
            String html = checkOnce(base);
            if (html != null) {
                final String fresh = html;
                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        if (alive && web != null) {
                            web.loadDataWithBaseURL(BASE_URL, fresh, "text/html", "utf-8", null);
                        }
                    }
                });
                return;
            }
        }
    }

    /** 单个地址试一次；没有新版本或出错都返回 null */
    private String checkOnce(String base) {
        try {
            String remoteVer = http(base + "version.txt").trim();
            int nl = remoteVer.indexOf('\n');
            if (nl >= 0) {
                remoteVer = remoteVer.substring(0, nl).trim();
            }
            if (remoteVer.length() == 0) {
                return null;
            }
            String localVer = readText(new File(getFilesDir(), "version.txt"));
            if (localVer != null && remoteVer.equals(localVer.trim())) {
                return null;
            }
            String html = fetchPage(tagOf(remoteVer));
            if (!isValid(html)) {
                return null;
            }
            writeText(new File(getFilesDir(), "index.html"), html);
            writeText(new File(getFilesDir(), "version.txt"), remoteVer);
            return html;
        } catch (Exception ignored) {
            return null;
        }
    }

    /** 从 version.txt 的内容里取出版本号（window.SQZY_LATEST={"v": "v2.3.15", ...}） */
    private static String tagOf(String latest) {
        java.util.regex.Matcher m = VER_IN_LATEST.matcher(latest == null ? "" : latest);
        if (!m.find()) {
            return "";
        }
        String v = m.group(1);
        return v.startsWith("v") ? v : "v" + v;
    }

    /**
     * 页面本体的取法，按可靠性排序。
     * 为什么要一串：码云 raw 对**大文件**直接返回
     *   451 The content may contain violation information
     * （2026-09-25 实测：同一个仓库里 ≤24 KB 正常、≥39 KB 全被挡，跟内容无关），
     * 而页面有 148 KB —— 只走 raw 的话「网页热更新」等于断了。
     *   1) 发行版附件：index.html 也挂一份到 release 上，tag 就是版本号
     *   2) contents API：匿名可读、内容永远跟仓库一致（base64）
     *   3) raw：小文件最快；大文件会 451，留着不亏
     */
    private static String[] pageUrls(String tag) {
        java.util.List<String> out = new java.util.ArrayList<String>();
        if (tag != null && tag.length() > 1) {
            out.add(RELEASE_DL + tag + "/index.html");
        }
        out.add(API_PAGE);
        for (String b : baseCandidates()) {
            out.add(b + "index.html");
        }
        return out.toArray(new String[0]);
    }

    /** 取页面：按 pageUrls() 依次试，返回第一个通过校验的；都失败返回 null */
    private static String fetchPage(String tag) {
        for (String u : pageUrls(tag)) {
            try {
                String body = http(u);
                if (u.contains("/contents/")) {
                    java.util.regex.Matcher m = API_CONTENT.matcher(body);
                    if (!m.find()) {
                        continue;
                    }
                    body = new String(android.util.Base64.decode(
                            m.group(1).replace("\\n", "").replace("\n", ""),
                            android.util.Base64.DEFAULT), "UTF-8");
                }
                if (isValid(body)) {
                    Log.i("sqzy", "页面取自 " + u.substring(0, Math.min(60, u.length()))
                            + "（" + body.length() + " 字节）");
                    return body;
                }
            } catch (Exception ignored) {
            }
        }
        return null;
    }

    private static boolean isValid(String html) {
        if (html == null || html.length() < MIN_HTML) {
            return false;
        }
        for (String m : MARKERS) {
            if (html.indexOf(m) < 0) {
                return false;
            }
        }
        return true;
    }

    private static String http(String url) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        try {
            c.setInstanceFollowRedirects(true);
            c.setConnectTimeout(TIMEOUT_MS);
            c.setReadTimeout(TIMEOUT_MS);
            c.setRequestProperty("User-Agent", UA);
            c.setRequestProperty("Cache-Control", "no-cache");
            int code = c.getResponseCode();
            if (code != 200) {
                throw new IllegalStateException("HTTP " + code);
            }
            InputStream in = c.getInputStream();
            ByteArrayOutputStream bo = new ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) {
                bo.write(buf, 0, n);
            }
            in.close();
            return new String(bo.toByteArray(), "UTF-8");
        } finally {
            c.disconnect();
        }
    }

    private String readAsset(String name) {
        try {
            InputStream in = getAssets().open(name);
            ByteArrayOutputStream bo = new ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) {
                bo.write(buf, 0, n);
            }
            in.close();
            return new String(bo.toByteArray(), "UTF-8");
        } catch (Exception t) {
            return null;
        }
    }

    private static String readText(File f) {
        try {
            if (!f.exists()) {
                return null;
            }
            FileInputStream in = new FileInputStream(f);
            ByteArrayOutputStream bo = new ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) {
                bo.write(buf, 0, n);
            }
            in.close();
            return new String(bo.toByteArray(), "UTF-8");
        } catch (Exception t) {
            return null;
        }
    }

    private static void writeText(File f, String text) {
        try {
            FileOutputStream out = new FileOutputStream(f);
            out.write(text.getBytes("UTF-8"));
            out.close();
        } catch (Exception ignored) {
        }
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK && web != null && web.canGoBack()) {
            web.goBack();
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    @Override
    protected void onDestroy() {
        alive = false;
        if (web != null) {
            ViewGroup p = (ViewGroup) web.getParent();
            if (p != null) {
                p.removeView(web);
            }
            web.destroy();
            web = null;
        }
        super.onDestroy();
    }
}
