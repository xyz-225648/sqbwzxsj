package com.sqzytc.timetable;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;

import java.io.File;
import java.io.FileNotFoundException;

/**
 * 极简文件提供者（#G 分享安装包用）。
 *
 * 为什么自己写一个：本工程不带 AndroidX，用不了 FileProvider；而 API 24 之后直接
 * 分享 file:// 会被 FileUriExposedException 拦下，所以必须走 content://。
 * 只暴露 cacheDir/share 目录下的文件，且 authorities 声明为 exported=false ——
 * 只有本应用通过授权（FLAG_GRANT_READ_URI_PERMISSION）交给接收方的那次才读得到。
 */
public class ApkProvider extends ContentProvider {
    public static final String AUTHORITY = "com.sqzytc.timetable.files";

    @Override
    public boolean onCreate() {
        return true;
    }

    @Override
    public String getType(Uri uri) {
        return "application/vnd.android.package-archive";
    }

    @Override
    public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        String name = uri.getLastPathSegment();
        if (name == null || name.contains("/") || name.contains("..")) {
            throw new FileNotFoundException("bad name");
        }
        File f = new File(new File(getContext().getCacheDir(), "share"), name);
        return ParcelFileDescriptor.open(f, ParcelFileDescriptor.MODE_READ_ONLY);
    }

    @Override
    public Cursor query(Uri uri, String[] projection, String selection,
                        String[] selectionArgs, String sortOrder) {
        return null;
    }

    @Override
    public Uri insert(Uri uri, ContentValues values) {
        return null;
    }

    @Override
    public int delete(Uri uri, String selection, String[] selectionArgs) {
        return 0;
    }

    @Override
    public int update(Uri uri, ContentValues values, String selection, String[] selectionArgs) {
        return 0;
    }
}
