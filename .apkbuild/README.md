# 安卓构建源码（APK 打包）

这里是**打 APK 需要的全部源码与脚本**。以前它们只在维护者本机、仓库里只有打包好的 apk ——
这几件入库后，任何人拿到仓库都能自己重打一个 APK。

## 目录

| 路径 | 作用 |
|---|---|
| `build_apk.py` | 打包脚本：aapt2 compile/link → javac → d8 → zipalign → apksigner，一条命令出 apk |
| `app/AndroidManifest.xml` | 清单：版本号（要跟页面 APP_VERSION 一致）、权限、前台服务、开机自启接收器、分享用的 ContentProvider |
| `app/java/com/sqzytc/timetable/` | 源码：`MainActivity`（窗口/通知/桥）、`KeepAliveService`（后台常驻）、`BootReceiver`（开机自启）、`ApkProvider`（分享安装包） |
| `app/res/` | 图标与字符串（**未入库**，见下） |

## 不在仓库里的东西（以及为什么）

- **`tools/sdk/`**：Android SDK 的 build-tools 与 platform，几百 MB，不入库。
  本地放好之后，改 `build_apk.py` 顶部的 `BT` / `PLATFORM` 两个路径指过去即可。
- **`release.keystore`**：签名钥匙，**绝对不要入库、也不要丢**。
  它决定"覆盖安装能不能成功"：换了钥匙，已装用户点安装会直接失败（提示签名不一致），只能卸载重装。
  ⚠️ 请自己额外备份一份（U 盘 / 私人仓库 / 密码管理器都行）。
  脚本首次运行若找不到钥匙会**自动生成一把**——那意味着换钥匙，所以只在全新环境才允许这样。

## 打包

```bash
python .apkbuild/build_apk.py        # 产出 宿迁职业技术学院作息时间表.apk
```

版本号两处要一起改（脚本不会自动同步）：`app/AndroidManifest.xml` 的 `versionCode/versionName`
与页面里的 `APP_VERSION`。`versionCode = 主*10000 + 次*100 + 补丁`（例：v2.3.3 → 20303）。

## 签名说明

安卓 APK 本来就是**自签名**的，不需要 CA 证书（CA 签名只针对 Windows exe 的 SmartScreen）。
所以这里的关键只有一条：**同一把钥匙，一直用下去**。
