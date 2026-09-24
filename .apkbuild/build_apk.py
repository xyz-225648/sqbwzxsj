# -*- coding: utf-8 -*-
"""打包 APK（不依赖 Git Bash 的版本，等价于 build_apk.sh）。

用法: python .apkbuild/build_apk.py
为什么另写一份：build_apk.sh 在受限环境里跑不起来（MSYS 的 bash 需要命名管道），
而这些步骤本身全都只是调用 aapt2 / javac / d8 / zipalign / apksigner，Python 直接调即可。
"""
import os, shutil, subprocess, sys, zipfile

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, 'app')
BT = os.path.join(HERE, 'tools', 'sdk', 'build-tools', '34.0.0')
PLATFORM = os.path.join(HERE, 'tools', 'sdk', 'platforms', 'android-34')
AJAR = os.path.join(PLATFORM, 'android.jar')
JDKBIN = os.path.join(HERE, 'tools', 'jdk', 'bin')
BUILD = os.path.join(HERE, 'build')
OUT = os.path.normpath(os.path.join(HERE, '..', '宿迁职业技术学院作息时间表.apk'))
PAGE = os.path.normpath(os.path.join(HERE, '..', '宿迁职业技术学院作息时间表.html'))


def run(cmd, **kw):
    env = dict(os.environ)
    env['JAVA_HOME'] = os.path.join(HERE, 'tools', 'jdk')
    env['PATH'] = JDKBIN + os.pathsep + env.get('PATH', '')
    p = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kw)
    out = p.stdout.decode('utf-8', 'replace')
    if p.returncode != 0:
        print('  ✗ %s\n%s' % (' '.join(cmd[:2]), out[-1500:]))
        sys.exit(1)
    return out


def main():
    for d in ('gen', 'classes', 'dex'):
        path = os.path.join(BUILD, d)
        shutil.rmtree(path, ignore_errors=True)
        os.makedirs(path)
    assets = os.path.join(APP, 'assets')
    os.makedirs(assets, exist_ok=True)
    shutil.copyfile(PAGE, os.path.join(assets, 'index.html'))
    print('  页面已拷进 assets（%d 字节）' % os.path.getsize(os.path.join(assets, 'index.html')))

    print('  aapt2 compile ...')
    run([os.path.join(BT, 'aapt2.exe'), 'compile', '--dir', os.path.join(APP, 'res'),
         '-o', os.path.join(BUILD, 'res.zip')])
    print('  aapt2 link ...')
    run([os.path.join(BT, 'aapt2.exe'), 'link', '-o', os.path.join(BUILD, 'base.apk'),
         '-I', AJAR, '--manifest', os.path.join(APP, 'AndroidManifest.xml'),
         '-R', os.path.join(BUILD, 'res.zip'), '-A', assets,
         '--java', os.path.join(BUILD, 'gen'), '--auto-add-overlay',
         '--min-sdk-version', '21', '--target-sdk-version', '34'])
    print('  javac ...')
    # 编译 app/java 下**全部** .java（MainActivity / KeepAliveService / BootReceiver …），
    # 只列 MainActivity 的话新加的类会报「找不到符号」（踩过）
    srcs = [os.path.join(BUILD, 'gen', 'com', 'sqzytc', 'timetable', 'R.java')]
    for root, _dirs, files in os.walk(os.path.join(APP, 'java')):
        for f in sorted(files):
            if f.endswith('.java'):
                srcs.append(os.path.join(root, f))
    print('  javac 源文件 %d 个' % len(srcs))
    run([os.path.join(JDKBIN, 'javac.exe'), '-encoding', 'UTF-8', '-source', '8', '-target', '8',
         '-nowarn', '-bootclasspath', AJAR, '-d', os.path.join(BUILD, 'classes')] + srcs)
    print('  d8 ...')
    classes = os.path.join(BUILD, 'classes', 'com', 'sqzytc', 'timetable')
    run(['cmd', '/c', os.path.join(BT, 'd8.bat'), '--lib', AJAR, '--min-api', '21',
         '--output', os.path.join(BUILD, 'dex')] +
        [os.path.join(classes, f) for f in os.listdir(classes) if f.endswith('.class')])
    print('  classes.dex 装进 apk ...')
    shutil.copyfile(os.path.join(BUILD, 'base.apk'), os.path.join(BUILD, 'withdex.apk'))
    with zipfile.ZipFile(os.path.join(BUILD, 'withdex.apk'), 'a', zipfile.ZIP_DEFLATED) as z:
        z.write(os.path.join(BUILD, 'dex', 'classes.dex'), 'classes.dex')
    print('  zipalign ...')
    run([os.path.join(BT, 'zipalign.exe'), '-f', '4', os.path.join(BUILD, 'withdex.apk'),
         os.path.join(BUILD, 'aligned.apk')])
    ks = os.path.join(HERE, 'release.keystore')
    if not os.path.exists(ks):
        run([os.path.join(JDKBIN, 'keytool.exe'), '-genkeypair', '-keystore', ks,
             '-storepass', 'android', '-keypass', 'android', '-alias', 'androiddebugkey',
             '-keyalg', 'RSA', '-keysize', '2048', '-validity', '10000',
             '-dname', 'CN=Android Debug,O=Android,C=CN'])
    print('  apksigner ...')
    if os.path.exists(OUT):
        os.remove(OUT)
    run(['cmd', '/c', os.path.join(BT, 'apksigner.bat'), 'sign', '--ks', ks,
         '--ks-pass', 'pass:android', '--key-pass', 'pass:android',
         '--ks-key-alias', 'androiddebugkey', '--v1-signing-enabled', 'true',
         '--v2-signing-enabled', 'true', '--out', OUT, os.path.join(BUILD, 'aligned.apk')])
    idsig = OUT + '.idsig'
    if os.path.exists(idsig):
        os.remove(idsig)
    print('  打包完成：%s（%d 字节）' % (OUT, os.path.getsize(OUT)))
    return 0


sys.exit(main())