# Corporium Windows 0.9.01101

**当前发行（2026-11-02同号重建）**：版本仍0.9.01101（Windows 0.9.1101.0），纳入此前全部SQL检索优化，以及附加层正负内部行距、MPW和附着成分单独计词选项。中英文界面同步，应用身份及安装路径规则保持。

安装包 `release/Corporium-0.9.01101-Windows-x64-Setup.exe`，本轮大小 **256,624,953** 字节，SHA-256：`D8EBFD72F17CCAE92C70F1CF5A9E2B5203105D0DBD788EE724542CF48E0FBF3C`。两份源码各169项相关后端、579项前端通过；包内源码比对、冻结程序自检及中英文首次／恢复／无项目首屏验证见[本轮报告](../build/mpw-line-spacing-20261102/REPORT.html)。未自动安装、升级或卸载用户系统。下方记录保留对应旧构建语义。

**前次发行（2026-11-01）**：0.9.01101（Windows 0.9.1101.0），纳入截至11-01的全部源码补充及本轮英文校对。旧0.9.01030安装包保留。本轮构建、校验值与验证边界见[发布报告](../build/release-01101-20261101/REPORT.html)。

**11-01前次构建验证：**安装包 `release/Corporium-0.9.01101-Windows-x64-Setup.exe`，256,561,219字节，SHA-256：`E15DF36C2B8D4CFAE392084DDC1B0C53160D41494DAC8E2D0075241E2661A8C4`。应用及安装器文字版本均0.9.01101，Windows数值0.9.1101.0；101个生产Python模块、118份网页资源与当前源码一致，61份许可及四份Junicode字体核对通过。冻结自检、中英首次／恢复及三种无项目首屏共8项启动探针通过。旧0.9.01030安装包及冻结EXE哈希不变。

更新于 **2026-10-30**。本次同号重建纳入例句样式／音频轮播、空表／数字继承／重做、词典布局及其他此前源码补充。两份源码各36项发布相关后端、527项完整前端通过；新冻结程序自检、中英首次／恢复启动及无项目首屏通过。

面向 Windows 10（1809 及以后）／Windows 11 x64。安装包包含 Python、应用依赖、Junicode 字体及 WebView2 离线安装程序。用户无需安装 Python。

**版本约定：** 只有用户要求时才更新版本号。其他修改保持当前版本，重建后直接覆盖同名安装包，并更新当前校验和与验证记录。不要因日期、功能或修复自行递增版本号。

附加层字号按全局比例相乘：110%×110%=121%。管理窗口排序和当前例句相关刷新已做真实浏览器检查；原生壳中英文自检／恢复启动通过。实际安装、旧版升级、卸载及干净系统离线验收仍需单独进行。

## 使用

每次安装（包括升级）均显示目录选择页，可自行选择安装位置；默认保留当前用户 Programs/Corporium，已安装时预填原目录。请把语料项目保存在安装目录之外。

首次打开 Corporium，选择“新建项目”并选择空文件夹，或“打开项目”选择包含 `data/corpus.sqlite3` 的既有语料库目录。以后启动会自动恢复上次成功打开的项目，默认呈现主页；主动勾选“下次直接进入工作区”时沿用该偏好。兼容旧最近项目记录，项目缺失／损坏时回到选择页并提示，不自动改开其他项目。原有网页项目可以直接打开；打开前会自动创建一致的 SQLite 备份。可通过“从完整备份恢复到新项目”恢复 `.corporium-backup` 或旧完整 JSON 备份，目标必须为空文件夹。

项目文件夹存储 `data/corpus.sqlite3`、`data/backups`、`font`，正式录音位于并列的 `media/recordings`；试音不自动落盘。安装目录只存程序。卸载不删除用户项目。最近项目和窗口缓存位于 `%LOCALAPPDATA%/Corporium`，启动错误日志为该目录的 `desktop.log`。

安装最后一页显示简短 Corporium 许可、WebView2 与 SmartScreen 说明，点击“同意并安装”接受本包附带的许可。可点“查看许可说明”阅读全文，不增加独立许可页或额外勾选。安装后在“管理 → 关于与许可”离线阅读；项目选择页同样提供入口，原文保存在安装目录 `_internal/licenses`。静默部署须先阅读许可，再显式传入 `/ACCEPTLICENSES=1`；缺少此参数将停止安装。应用标识与旧版相同；程序签名按计划留到正式发布。

安装包只额外包含经指定的虚构示例语言 Tëlira（573 词条、2 文本、168 句），不包含正式调查语料、test_media 媒体或自定义字体。可在「语言选项 → 导入语言数据包 → 使用内置示例 Tëlira」选择导入，不自动改写用户项目。只附带 Junicode；打开现有项目时使用该项目 font 中的 IPA 和其他字体。新项目没有 IPAPANNEW 时暂用 Junicode 显示，可将自有字体放进项目 font 后扫描。

JSON 备份恢复语料及设置，不包含字体文件。迁移现有项目时，复制整个项目文件夹可以保留自定义字体；仅恢复 JSON 时，请另行复制原项目的 font 文件夹。

本版包含时间轴、多层轨道、音视频播放和对齐；媒体支持“复制进项目”或“链接原位置”。语言交换包可选携带媒体，内置 Tëlira 示例不携带媒体。

## 日常开发测试（无需安装或打包）

在项目根目录双击 `Open-Corporium-Dev.cmd`，使用本项目 `.desktop-venv` 环境直接运行最新源码，并打开当前项目文件夹。窗口标题为“Corporium · 开发版”。修改代码后先关闭开发版窗口，再双击启动，即可测试更新。重复双击只唤起已有窗口，不会重新加载后端代码。

开发版使用独立端口 18766，设置和日志位于 `%LOCALAPPDATA%/Corporium-dev`，不会误唤起已安装的正式版。它直接读写所打开项目的真实数据；需要试验性增删改时，可使用“从完整备份恢复到新项目”创建测试副本。不必在每轮开发后构建安装包。

此入口依赖本机已经配置的 `.desktop-venv`，适用于开发电脑，不作为其他用户的免安装发行版。若环境丢失，可按下方构建说明重建依赖环境。

## 构建安装包

开发者需要 Windows、Python 3.12 x64 和 Inno Setup。运行 `packaging/build-windows.ps1 -Python <python.exe> -Iscc <ISCC.exe>`。脚本创建独立环境，按锁定依赖构建 EXE，再生成安装包。

提前将微软官方 WebView2 x64 Evergreen Standalone Installer 放到 `build-tools/MicrosoftEdgeWebView2RuntimeInstallerX64.exe`；脚本验证微软数字签名。下载：https://developer.microsoft.com/microsoft-edge/webview2/ 。Inno Setup：https://jrsoftware.org/isdl.php 。

产物：`release/Corporium-0.9.01101-Windows-x64-Setup.exe`；可直接运行的应用目录：`release/app-0.9.01101/Corporium`（必须保留整个目录）。应用／关于页和版本字符串为0.9.01101，Windows数值版本为0.9.1101.0。内置 Tëlira 沿用已对齐的示例材料；原 AppId 不变，应用仍未签名。

构建会收集依赖许可并校验必需文件。更新随包 WebView2 安装器时，应同时核对 `licenses/Microsoft-WebView2-Runtime-LICENSE.txt` 是否仍与该发行包适用条款一致。许可文件来源及隐私链接见 `licenses/THIRD-PARTY-NOTICES.txt`。

`Corporium.exe --self-test <临时目录>` 检查打包运行时、资源、建库和项目记忆；`--smoke-test <另一个临时目录>` 使用隐藏 WebView2 窗口加载真实界面并输出 `Corporium/ui-test.json`，同目录再次运行会恢复第一次的测试项目，可核对 resumed 和 homeVisible。两者均使用隔离设置／项目，不访问用户语料。正式发布还需在无 Python、无 WebView2 的干净 Windows 虚拟机中测试离线安装、升级、下载、卸载与数据保留。当前安装包未进行代码签名。

新版构建按版本输出到 `release/app-<版本>/Corporium`，不覆盖旧版 `release/app`。安装器通过 AppSource 参数使用对应目录。
