# Corporium 磁盘占用盘点与整理记录

**2026-11-01执行更新：**build 按授权完成整理：第一批清理 2.29 GiB，退役四个早期原始合成库／索引副本 0.50 GiB，其余旧库、备份与配套日志 26.75 GiB 压缩为 5.44 GiB。build 约 35.93→11.84 GiB；共用19个基线与最新4个性能工作库保留，9,104个保护文件哈希一致。新增按用途归档索引与校验恢复入口，旧引导按需恢复；两份源码各18项相关测试通过，业务功能与安装包不变。 [本轮清理与恢复记录](build/storage-cleanup-20261101/REPORT.html)。 下方只读复盘数字为清理前快照。

**2026-11-01只读复盘：**build约35.92 GiB。已确认28.74 GiB SQLite、4.67 GiB JSON；建议先处理约2.29 GiB可再生／完全重复候选，再对旧工作库和测试备份归集、压缩。共用基线和近期4个工作库保留。本轮未删除、移动或改写已有材料。[当前盘点与逐项建议](build/storage-review-20261101/REPORT.html)。下方旧轮次数值与授权只代表当时。

**2026-10-24 更新：**用户已在新一轮只读排查后授权整理，已归集共用测试基线、调整旧脚本并清理重复副本、临时产物及旧安装包。正式资料、正式备份、媒体、示例和开发环境保留，完成测试与文件哈希验证。当前清单、净变化和复现见[整理报告](build/storage-consolidation-20261024/REPORT.html)。下方2026-10-15的数字和“未删除”只描述当时，不代表当前状态。

日期：2026-10-15。按普通文件Length求和，含隐藏文件；这是逻辑字节量，不是NTFS实际占用／压缩／硬链接去重后的物理空间。四舍五入，1MiB=1024²字节、1GiB=1024³字节。测量时测试服务可能仍运行，文件大小会变化。

总计 **9.58 GiB（10.28 GB）**。没有执行删除、移动、数据库压缩或备份裁剪。

## 顶层分布

| 目录 | 大小 |
| --- | ---: |
| `test_media` | 4,238.5 MiB |
| `build` | 3,533.6 MiB |
| `release` | 807.7 MiB |
| `data` | 571.3 MiB |
| `build-tools` | 246.8 MiB |
| `font` | 165.7 MiB |
| `.desktop-venv` | 150.3 MiB |
| `test_lang` | 79.4 MiB |
| `assets` | 9.3 MiB |
| `packaging` | 1.0 MiB |
| `tests` | 0.8 MiB |
| `__pycache__` | 0.7 MiB |

## 可清理或迁移候选（每行互不重叠）

目录整项大小是上限，保留报告／脚本后释放量略小。不是删除授权。

| 项目 | 路径 | 整项空间上限 | 条件及影响 |
| --- | --- | ---: | --- |
| 旧性能合成数据（三轮） | `build/performance-20261013`<br>`build/performance-optimized-20261013`<br>`build/performance-final-20261013` | 1,355.4 MiB | 保留results、计时报告、profile和截图；清理合成SQLite／fixture。先确认无预览服务占用，基线对照库清理后需重新生成。 |
| 旧时间轴预览项目 | `build/timeline-preview` | 808.5 MiB | 合成项目；先核实无人工新增需保留材料、无服务占用。 |
| 调查／近期UI预览项目 | `build/survey-preview` | 606.3 MiB | 近期8775等预览曾使用；暂优先保留，换成更小验收项目后再清。 |
| 分析测试数据库 | `build/analysis-benchmark.sqlite3`<br>`build/analysis-preview.sqlite3` | 402.5 MiB | 合成库；保留benchmark脚本和结果，确认相关服务停止。 |
| 早期媒体独立虚拟环境 | `build/media-venv` | 120.4 MiB | 可重建；正式开发使用.desktop-venv。旧媒体实验若依赖该解释器需调整。 |
| 媒体技术验证输出 | `build/media-lab` | 92.8 MiB | 波形／语谱原型、短代理等可重建；保留inventory、playback和proxy结果报告，不删原素材。 |
| PyInstaller中间产物 | `build/windows` | 21.5 MiB | 下次构建自动重建，增加构建时间。 |
| 失败示例准备残留 | `build/sample-stage-zmbg4wkw` | 15.2 MiB | 示例库副本残留；当前打包示例和源test_lang另在，不影响二者。 |
| 旧0.1.0／0.3.0安装包 | `release/Corporium-0.1.0-Windows-x64-Setup.exe`<br>`release/Corporium-0.3.0-Windows-x64-Setup.exe` | 434.8 MiB | 保留0.8.0；旧包可先移出仓库供升级测试，删除后不能直接回测旧安装流程；校验清单也需同步。 |
| 可再生正式媒体缓存 | `data/media-cache` | 32.8 MiB | 关闭媒体任务／播放器后可重建，首次波形／兼容播放会重新处理；不是媒体原件。 |
| 正式自动备份（10份） | `data/backups` | 487.8 MiB | 不是普通冗余。总计487.8MiB；若决定只留最新3份，理论释放341.5MiB。先确认最新备份可恢复及额外副本，本次不修改保留策略。 |
| 免安装发行目录 | `release/app` | 129.3 MiB | 129.3MiB，可由构建恢复，但是当前免安装应用及打包输入，建议保留。 |
| WebView2离线安装依赖 | `build-tools/MicrosoftEdgeWebView2RuntimeInstallerX64.exe` | 204.2 MiB | 204.2MiB，重新下载安装需要联网，后续离线打包要用，建议保留。 |
| 已安装Inno与下载器 | `build-tools/inno`<br>`build-tools/innosetup.exe` | 42.7 MiB | inno编译器继续打包需要；仅innosetup.exe安装下载件约10.1MiB可单独考虑。 |

性能三轮中，单独的SQLite／fixture JSON共有20个、**1,355.2 MiB**；保留其他结果与profile的情况下可将这部分列为候选。

建议第一批候选：上述性能数据、旧timeline-preview、两个分析合成库、media-venv、build/windows、sample-stage残留及两个旧安装包，合计约 **3.08 GiB**。这是确认无占用且不需保留试验修改后的空间估算；尚未删除。survey-preview、正式备份、正式缓存、原媒体和开发环境不在这批合计内。

## 原材料与应保留内容

- `test_media`：**4.14GiB**，14份用户专门收集的测试音视频。不是自动生成缓存。不建议直接删；若有另一份已核验副本，可迁到外置盘释放同等本机空间。链接到这些文件的时间轴／实验路径将失效，需重新定位。不在上述候选合计内。
- `data/corpus.sqlite3`：约48.8MiB正式数据，保留；同目录SQLite sidecar不要单独删除。
- `test_lang`：约79.4MiB，包含示例源项目和生成／导入材料；prepare_example.py构建需要源项目，保留。
- `font`约165.7MiB、`.desktop-venv`约150.3MiB：字体与日常桌面开发依赖，保留。
- `release/Corporium-0.8.0-Windows-x64-Setup.exe`约243.6MiB：本次成果，保留。
- `assets`、源码、tests、tools、packaging、import typ以及模板／研究资料均不按缓存处理。
- build内还有多个小型WebView2自检用户目录（约2–12MiB/项）、截图、日志和复现脚本。收益较小，不建议为凑空间全部清空；先归档v080验收证据与性能报告。

## 执行清理前的核实

本次尝试读取进程命令行时，当前环境的CIM接口不可访问，因此**未证明这些目录目前无人使用**。今后清理前必须另行确认后台服务、桌面窗口、媒体任务和测试进程均不使用目标。不得仅凭目录名字删除。删除／移动前解析绝对路径，限定在用户确认的目录；保留最新发行版、正式数据和可恢复备份。迁到同一磁盘其他目录只减少仓库体积，不释放该磁盘空间。
