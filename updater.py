# -*- coding: utf-8 -*-
"""独立更新器：下载新安装包 → 校验 → 结束旧进程 → 原位置替换 → 启动新程序 → 自我删除。

主程序把更新器从自身释放出来后用下面参数启动：
    sqzy_updater.exe --url <下载直链> --sha256 <sha256> --target <旧exe路径> [--version <版本>]
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time

LOG = os.path.join(tempfile.gettempdir(), 'sqzy_updater.log')


def log(text):
    try:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write('%s %s\n' % (time.strftime('%H:%M:%S'), text))
    except Exception:
        pass


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def download(url, dest):
    import urllib.request
    req = urllib.request.Request(url, headers={'User-Agent': 'sqzy-updater/1.0'})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, 'wb') as f:
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
    return os.path.getsize(dest)


def kill_old(target):
    name = os.path.basename(target)
    try:
        subprocess.run(['taskkill', '/IM', name, '/F'],
                       capture_output=True, timeout=20)
    except Exception:
        pass


def move_with_retry(src, dst, tries=40):
    for i in range(tries):
        try:
            os.replace(src, dst)
            return True
        except Exception:
            try:
                shutil.move(src, dst)
                return True
            except Exception:
                time.sleep(0.5)
    return False


def delete_self():
    """更新器自我删除：直接 spawn 的 cmd 会随父进程退出被杀掉，
    所以写一个小 vbs，由 wscript 在父进程退出后继续执行删除。"""
    me = os.path.abspath(sys.argv[0])
    vbs = os.path.join(tempfile.gettempdir(), 'sqzy_del.vbs')
    try:
        with open(vbs, 'w', encoding='gbk', newline='\r\n') as f:
            # 先 ping 3 秒等更新器进程完全退出、文件解锁，再删更新器和 vbs 自己
            f.write('CreateObject("WScript.Shell").Run '
                    '"cmd /c ping -n 4 127.0.0.1 >nul & del /f /q ""%s"" >nul 2>nul & del /f /q ""%s"" >nul 2>nul", 0, False\r\n'
                    % (me, vbs))
        subprocess.Popen(['wscript.exe', vbs], creationflags=0x08000000, close_fds=True)
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', required=True)
    ap.add_argument('--sha256', required=True)
    ap.add_argument('--target', required=True)
    ap.add_argument('--version', default='')
    args = ap.parse_args()

    log('updater start target=%s version=%s' % (args.target, args.version))
    time.sleep(1.5)                      # 给主程序退出留时间
    kill_old(args.target)

    tmp = os.path.join(tempfile.gettempdir(), 'sqzy_new.exe')
    try:
        download(args.url, tmp)
    except Exception as exc:
        log('download failed: %r' % exc)
        return 1
    got = sha256_of(tmp).lower()
    if got != (args.sha256 or '').lower():
        log('sha256 mismatch: %s != %s' % (got, args.sha256))
        try:
            os.remove(tmp)
        except Exception:
            pass
        return 2

    if not move_with_retry(tmp, args.target):
        log('replace failed, new file still at %s' % tmp)
        return 3

    log('replace ok, starting %s' % args.target)
    try:
        subprocess.Popen([args.target])
    except Exception as exc:
        log('start failed: %r' % exc)
    delete_self()
    return 0


if __name__ == '__main__':
    sys.exit(main())
