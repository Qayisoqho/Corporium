# 旧测试材料的压缩归档

`build/test-materials` 是未压缩的共用基线，不是缓存；`build/test-archives` 是旧轮次独有状态的冷归档。正式 `data`、正式备份、媒体、发行文件与开发环境不属于清理范围。近期四个性能工作库继续保留原路径和未压缩文件。

归档的 `catalog.json` 记录原路径、用途、来源轮次、大小、时间和 SHA-256。`purposes/` 下按性能、词典形态、搜索统计、语法调查、时间轴媒体、数据交换存储、界面和其他回归分类列出材料；`objects/` 保存 gzip 对象，相同内容可共用对象。每份压缩流均完整解压并校验后才移除原文件。SQLite 与其 `-journal`、`-wal`、`-shm` 按同组保存，不在归档阶段打开数据库或丢弃恢复日志。

从仓库根目录使用当前 Python 环境：

```powershell
# 查看某类或全部归档，路径使用清单中的原始相对路径。
python tools/test_archives.py list --purpose performance
python tools/test_archives.py list

# 完整解压到校验器，不写入工作库。
python tools/test_archives.py verify build/performance-final-20261013/synthetic-1000.sqlite3

# 恢复到原位置，或另一处独立工作位置；自动带上配套日志。
python tools/test_archives.py restore build/performance-final-20261013/synthetic-1000.sqlite3
python tools/test_archives.py restore build/performance-final-20261013/synthetic-1000.sqlite3 --destination build/recheck/corpus.sqlite3
```

恢复拒绝覆盖现有工作文件，也拒绝写入正式数据、共用基线、归档本身及保留的近期工作库。压缩包损坏、内容校验错误或组内任一成员异常时，不发布部分数据库。带恢复日志的历史现场应先恢复到新的工作目录，再使用 SQLite 检查／恢复；压缩校验只证明原始字节保留，不等同于数据库逻辑检查。

已有 `enable_legacy` 引导的旧脚本会按引用自动恢复缺失输入；没有引导的脚本可通过以下入口运行：

```powershell
python tools/test_materials.py run build/某轮次/check.py
```

自动恢复的未修改副本在正常退出时清理；修改后的结果、未结束的事务及新的恢复日志继续留作现场。显式 `restore` 的副本由开发者管理。路径由运行参数拼接、脚本间接导入或旧函数动态决定时，选择器不能保证识别全部依赖，应先显式恢复所需原路径。原有 reports、fixture JSON、脚本及 before-source 保持原位置。

2026-11-01 另行退役了 `build/performance-20261013` 下三份第一代原始合成库及一份索引试验副本，具体名单见归档清单 `retired`。它们不再逐字节可恢复；同轮优化／最终状态已归档，普通千／万／五万句基线仍可取用，原始生成器 `tests/benchmark_corpus.py` 和历史结果均保留。不要把该生成器生成的新库当作旧计时的原始文件。

后续测试优先从共用基线取得独立副本，在少量工作库上运行。保留小型结果和失败现场，避免每轮长期堆放整库及自动备份。应用的正常备份、撤销和业务逻辑没有因本次整理改变。
