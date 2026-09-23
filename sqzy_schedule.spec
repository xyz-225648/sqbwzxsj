# -*- mode: python ; coding: utf-8 -*-
# 版本信息资源直接从这里生成，版本号取自页面里的 APP_VERSION —— 三处版本号（页面 / version.txt /
# 安卓 versionName）本来就要一致，exe 的属性页也跟着它走，省得单独维护一个 version_info.txt。
# 说明：版本信息**不能**消除 SmartScreen 的「无法识别的应用」弹窗 —— 「发布者」那一栏只有代码签名能填。
import io as _io
import re as _re
from PyInstaller.utils.win32.versioninfo import (
    VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct,
    VarFileInfo, VarStruct)

_src = _io.open('宿迁职业技术学院作息时间表.html', encoding='utf-8').read()
_m = _re.search(r"var APP_VERSION = 'v([0-9]+)\.([0-9]+)\.([0-9]+)'", _src)
_maj, _min, _pat = ((int(_m.group(1)), int(_m.group(2)), int(_m.group(3))) if _m else (0, 0, 0))
# 字段按常见 Windows 软件的属性面板对齐（参考 QQ Chat Exporter 那种）：
#   文件说明 = 应用名；文件版本 = 四段 2.2.1.0；产品名称 = 应用名；产品版本 = 三段 2.2.1；
#   版权 = Copyright © 年份 作者；语言 = 语言中性（LangID 0x0000 + Unicode 0x04B0）。
#   属性面板里的「类型 / 大小 / 修改日期」是 Windows 自己算的，填不了。
_ver4 = '%d.%d.%d.0' % (_maj, _min, _pat)
_ver3 = '%d.%d.%d' % (_maj, _min, _pat)
_vi = VSVersionInfo(
    ffi=FixedFileInfo(filevers=(_maj, _min, _pat, 0), prodvers=(_maj, _min, _pat, 0),
                      mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
    kids=[StringFileInfo([StringTable('000004b0', [
        StringStruct('CompanyName', '宿迁职业技术学院作息时间表（学生自制）'),
        StringStruct('FileDescription', '宿迁职业技术学院作息时间表'),
        StringStruct('FileVersion', _ver4),
        StringStruct('InternalName', 'sqzy_schedule'),
        StringStruct('LegalCopyright', 'Copyright © 2026 xyz-225648'),
        StringStruct('OriginalFilename', '宿迁职业技术学院作息时间表.exe'),
        StringStruct('ProductName', '宿迁职业技术学院作息时间表'),
        StringStruct('ProductVersion', _ver3)])]),
        VarFileInfo([VarStruct('Translation', [0, 1200])])])


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[('宿迁职业技术学院作息时间表.html', '.')],
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
    # 关掉 UPX：压缩壳是杀软误报的重灾区（尤其国产杀软 + PyInstaller onefile 组合）。
    # 代价是 exe 大一两 MB，换的是少被拦。
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
    # 版本信息资源（见文件开头，版本号从页面 APP_VERSION 生成）
    version=_vi,
)
