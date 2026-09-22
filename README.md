# 宿迁职业技术学院作息时间表

四个学院（信息设计 / 信息基础 / 通识教育 / 女子教育）的一日作息时间轴，**Windows 桌面版 / 安卓手机版 / 浏览器网页版** 三端通用。

当前版本：**v2.1.1**

## 下载使用

到 [发行版页面](https://gitee.com/xyz-225648/sqbwzxsj/releases) 下载（链接永远指向最新版）：

| 平台 | 文件 | 说明 |
|---|---|---|
| **Windows** | 宿迁职业技术学院作息时间表.exe | 双击即用，免安装（需 WebView2，Win11 自带） |
| **安卓手机** | 宿迁职业技术学院作息时间表.apk | 允许「安装未知来源应用」后安装 |
| **浏览器** | index.html（仓库根目录） | 任意浏览器直接打开 |

> 仓库里只放源码、网页和自检脚本；体积大的 exe / apk 只放在发行版附件里，免得每次 clone 都要拖下十几 MB 的二进制。

## 功能

- 全天时间轴，**横版 / 竖版**自动切换（窗口变窄自动立起来，手机自动用竖版）
- **当前时段高亮** + 「还有几分钟下课 / 还有几分钟上课」倒计时
- 鼠标悬停预览任意时刻，**点一下钉住**，四学院当时的状态一览
- 点学院名跳到下方对应卡片；桌面版有**回到顶部**按钮和 Ctrl + 滚轮缩放（会被记住）
- **完全离线可用**（页面零外部依赖，校徽图标是内嵌的）

### 桌面版（Windows）额外功能

- **窗口置顶**：页头按钮或 Ctrl + T，设置面板里也能开关
- **关闭到托盘**：点 ✕ 只隐藏，课表提醒照常在后台跑；双击托盘图标恢复
- **开机自启动**：登录 Windows 后自动在**托盘**运行（不弹窗口），设置面板里随时开关
- **单实例**：重复双击 exe 不会开出第二个窗口，只会把原来那个（哪怕藏在托盘里）叫到前台
- **Windows 系统通知**：带校徽图标，可在「设置 → 系统 → 通知」里管理

### 手机版（安卓）额外功能

- 走**安卓系统通知**（首次启动会申请通知权限）
- 打开后 1~2 秒自动刷新成仓库里的最新课表
- 手机版不显示「置顶 / 切换横竖版」这类只对桌面有意义的按钮

## 设置

设置面板里的开关**改动即时生效并自动保存**，关掉窗口下次打开还在：
按学院分别开关通知、下课前提醒（可调提前几分钟）、上课前 / 开始上课 / 下课时提醒，
还能发一条测试通知验证通道是否正常。

## 自动更新

软件启动时先秒开本地版本，再后台去码云问一句「有没有新版本」，有就静默替换新页面。

仓库里还有一份 `program.txt`：它记录当前发布的 **exe / apk 版本**。网页能自动热更新、程序本体不能，所以页面会拿它比一次 —— 发现自己落后就在「设置 → 关于」提示「程序本体有新版」并给出下载入口。

**改课表只需要动 index.html 和 version.txt**，所有人下次打开就是最新的，不用重装。
换 exe / apk 才算「发新版」，那时才需要在发行版里替换附件。

详见 [自动更新使用说明.md](自动更新使用说明.md)。

## 版本号规范

    V主.次.补丁

| 段位 | 什么时候加 | 例子 |
|---|---|---|
| **主版本** | 架构改动、重大功能新增或重构 | V1 → V2 |
| **次版本** | 新增普通功能、界面优化 | V2.0 → V2.1 |
| **补丁号** | Bug 修复、微小调整（不新增功能） | V2.0.0 → V2.0.1 |

页面里的 APP_VERSION、version.txt、安卓 versionName 三处必须一致；
发布脚本直接从页面里读版本号写进 version.txt，不会对不上。

## 仓库文件说明

| 文件 | 用途 |
|---|---|
| index.html | 网页主体，也是自动更新的内容源（本地开发时页面源码叫「宿迁职业技术学院作息时间表.html」，publish.sh 会把它复制成 index.html；仓库里只保留一份，避免重复） |
| version.txt | 版本标记，内容变了才触发更新 |
| app.py | Windows 桌面版源码（pywebview + WebView2） |
| publish.sh | 一键发布：先过全部自检，再生成 release/ 里的两个文件 |
| set-update-url.sh | 给二次开发者用：改自动更新地址并重新打包 |
| check_live.py | 发布之后核验线上：网页、版本号、两个下载链接跟本地是否一致 |
| gitee_repo.py | 维护者工具：仓库文件 / 分支 / Pull Request / Issue / 发行版，一条命令管一种动作（令牌读本机 .gitee_token，不会进仓库） |
| 自动更新使用说明.md | 自动更新的原理和日常操作 |
| CHANGELOG.md | 每个版本改了什么 |

## 自检脚本

发布前 publish.sh 会依次强制跑一遍，任何一项不过就中止发布：

| 脚本 | 作用 |
|---|---|
| check_page.py | 页面内联脚本语法检查（node --check） |
| smoke_page.py | 无头浏览器渲染冒烟：三档视口 + 安卓 UA，抓未捕获异常和「功能没渲染出来」 |
| functest_page.py | 无头浏览器 + CDP **交互遍历**：悬停/钉住、设置保存、通知判定、更新弹窗、缩放、防调试… |
| selftest_api.py | 桌面版本地接口自检：/ping /state /notify /latest /quit |
| functest_app.py | 桌面外壳端到端：真的开一个窗口，验单实例、托盘、置顶、退出 |
| check_live.py | 发布**之后**跑：核验线上网页 / version.txt / exe、apk 下载链接与本地一致 |

```bash
python functest_app.py                        # 测源码
python functest_app.py --exe 宿迁职业技术学院作息时间表.exe   # 测打包好的 exe
```

## 开发流程（issue → 分支 → Pull Request → 合并）

改这个仓库的代码一律走 Pull Request，不直接推 master，改动可追溯、可回滚：

1. **提 issue**：说清问题或想要的功能（仓库菜单「Issues → 新建」）。
2. **开分支**：`python gitee_repo.py branch new fix/xxx`
3. **改代码 + 过闸门**：本地跑 `bash publish.sh` —— 页面语法 / 渲染冒烟 / 交互遍历 / 本地接口
   四项自检全过才允许提交；桌面外壳改动另外跑 `python functest_app.py`。
4. **提交 PR**：`python gitee_repo.py --branch=fix/xxx push <改动文件>` 把改动提上分支，
   再 `python gitee_repo.py pr new fix/xxx "<标题>" <说明.md>`（说明里写清改了什么、
   怎么验证的，并关联 issue 编号）。
5. **过门槛 + 合并**：本仓库开了「合并前必须通过审查 / 测试」，所以顺序是
   `python gitee_repo.py pr approve <编号>`（一次点掉「审查通过」「测试通过」）→
   `python gitee_repo.py pr merge <编号>`。合并后在 PR 页面能看到 diff、审查与测试记录。
6. **回 issue**：`python gitee_repo.py issue comment <编号> "<版本 + 结论>"`，
   然后 `python gitee_repo.py issue close <编号>`。

### 发布也走 PR

**发布**就是一次普通的改动，同样走上面的流程，不要图快直接推 master（已经犯过一次：v2.1.1 的改动绕过 PR 直推了 master）：

- `index.html`（网页主体）、`version.txt`、`program.txt` 连同代码一起放进同一个 PR；
  合并进 master 的那一刻，所有人的自动更新就会拿到新版本
- 打 tag、发发行版、上传 exe / apk 附件是 **PR 之外** 的步骤（附件是二进制，没法评审）
- 工具层已经堵死直推：`gitee_repo.py push` 不带 `--branch=` 会被拒绝，
  只有线上出故障要立刻回滚这种急事才用 `--direct` 绕过

### PR 说明写到哪

仓库里有 `.gitee/PULL_REQUEST_TEMPLATE.md`：改了什么 / 为什么（关联 issue）/ 怎么验证（跑过哪些闸门、结果如何）
—— 三项都要如实填，不跑闸门的 PR 不合并。

## GitHub 镜像

同一份仓库在 GitHub 上也有一份：https://github.com/xyz-225648/sqbwzxsj

两边**双向同步**，谁领先就推给谁，规则写死在 `.github/workflows/mirror-sync.yml` 里：

| 情况 | 动作 |
|---|---|
| 两边相同 | 什么都不做（只对齐 tag） |
| GitHub 领先（在 GitHub 合并了 PR） | 推给 Gitee |
| Gitee 领先（在 Gitee 合并了 PR） | 推给 GitHub |
| 两边各有新提交 | 先自动合并；**合不干净就报错停下，谁都不动** |

- 触发时机：每 6 小时一次 / GitHub 上 push 到 master（合并 PR 后立刻）/ 也可以在工作流页面手动点
- 往 Gitee 推需要 GitHub 仓库里的 Actions secret `GITEE_TOKEN`（Gitee 私人令牌，勾 projects 权限）；没配的话只有 Gitee → GitHub 单向可用，反向那步会明确报错而不是假装成功
- 主仓库仍然是 Gitee：产品改动按上面的「开发流程」在 Gitee 走 PR；在 GitHub 上开发也可以，合并后会由这个工作流推回 Gitee
### 在 GitHub 上开发

1. 照常在 GitHub 上开分支、提 PR（讨论、评审都留在 GitHub）
2. 合并进 master 后，同步工作流会自动跑一次，把这次改动推回 Gitee
3. 如果同一时间 Gitee 那边也有新提交，工作流会先把两边的提交合并起来；
   **合不干净就直接报错停下**，两边都不会被覆盖，等人工处理

> 两边都可以当开发入口，主仓库是 Gitee（自动更新、发行版、issue 都在那边）。

## 许可

MIT，见 [LICENSE](LICENSE)。