<!-- 每一条都请如实填写；不跑闸门的 PR 不合并 -->

## 改了什么

<!-- 一句话说清这次改了什么 -->

## 为什么

<!-- 关联 issue，例如 Fixes #IKHS2W；说明问题或需求 -->

## 怎么验证

<!-- 写跑过的命令和结果，别只写「已测试」 -->

- [ ] `bash publish.sh` 全过（页面语法 / 渲染冒烟 / 交互遍历 / 本地接口）
- [ ] 动了桌面外壳：`python functest_app.py`（源码与打包后的 exe 各一遍）
- [ ] 动了页面：`APP_VERSION` 按 V主.次.补丁 升过号，且与 `CHANGELOG.md` 对得上
- [ ] 动了发布数据：`index.html` / `version.txt` / `program.txt` 与本地一致（`python check_live.py`）
