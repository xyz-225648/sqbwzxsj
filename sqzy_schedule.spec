# -*- mode: python ; coding: utf-8 -*-
# 版本信息资源直接从这里生成，版本号取自 app.py 里的 SHELL_VERSION（程序本体版本，
# 与页面版本分开算）—— exe 的属性页跟它走，不用单独维护一个 version_info.txt。
# 说明：版本信息**不能**消除 SmartScreen 的「无法识别的应用」弹窗 —— 「发布者」那一栏只有代码签名能填。
import io as _io
import os as _os
import re as _re

from PyInstaller.utils.win32.versioninfo import (
    VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct,
    VarFileInfo, VarStruct)


def _page_file():
    """页面文件名（P2）：本地开发叫「宿迁职业技术学院作息时间表.html」，仓库里是 index.html。
    仓库只保留一份（避免两份内容漂移），所以这里按顺序找，clone 下来就能直接跑。"""
    for _n in ('宿迁职业技术学院作息时间表.html', 'index.html'):
        if _os.path.exists(_n):
            return _n
    raise SystemExit('找不到页面文件：宿迁职业技术学院作息时间表.html 或 index.html（请在仓库根目录执行）')


_src = _io.open('app.py', encoding='utf-8').read()
_m = _re.search(r"SHELL_VERSION = 'v([0-9]+)\.([0-9]+)\.([0-9]+)'", _src)
_maj, _min, _pat = ((int(_m.group(1)), int(_m.group(2)), int(_m.group(3))) if _m else (0, 0, 0))
_ver4 = '%d.%d.%d.0' % (_maj, _min, _pat)
_ver3 = '%d.%d.%d' % (_maj, _min, _pat)
_vi = VSVersionInfo(
    ffi=FixedFileInfo(filevers=(_maj, _min, _pat, 0), prodvers=(_maj, _min, _pat, 0),
                      mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
    kids=[StringFileInfo([StringTable('080404b0', [
        StringStruct('FileDescription', '宿迁职业技术学院作息时间表'),
        StringStruct('FileVersion', _ver4),
        StringStruct('InternalName', 'sqzy_schedule'),
        StringStruct('LegalCopyright', ''),
        StringStruct('OriginalFilename', '宿迁职业技术学院作息时间表.exe'),
        StringStruct('ProductName', '宿迁职业技术学院作息时间表'),
        StringStruct('ProductVersion', _ver3)])]),
        VarFileInfo([VarStruct('Translation', [2052, 1200])])])


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[('sqzy_updater.exe', '.')],
    datas=[(_page_file(), '.')],
    hiddenimports=['webview.platforms.edgechromium'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='sqzy_schedule',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['app.ico'],
    version=_vi,
)
