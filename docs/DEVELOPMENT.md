# 开发说明

## 目录

- 根目录 Python 模块：服务端、数据模型、导入导出与桌面外壳。
- `web/`：前端脚本、样式和页面；不需要 npm 构建步骤。
- `tests/`：后端与前端回归测试。
- `tools/`：合成数据库生成器及跨模块性能实验工具。
- `packaging/`：Windows 安装包配置、许可和虚构示例。
- `font/Junicode/`：附带许可的字体资源。

## 隔离验证

推荐通过根目录的 `run_tests.py` 运行测试。后端测试新建临时数据库，不接触现有用户项目；数据库访问被限制在此目录的 `build/` 内。不要将正式数据库放入测试目录。

源码自检可用 `python -B desktop.py --self-test build/desktop-check`，不会使用正常桌面配置。实际窗口验证应使用独立测试项目。

公开测试中的 Typst、无译文 Excel 和媒体输入均为合成材料；字体测试使用附带的 Junicode。它们覆盖相应格式与操作，不包含内部开发时使用的个人原始材料。

## 大规模材料

```powershell
python -B tools/test_materials.py generate --profile dense --sentences 10000 --output build/dense-10000/corpus.sqlite3
```

`smoke` 组合常用关联功能，`ordinary` 生成一般规模关联，`dense` 为每个适用词格建立词典关联，`research` 增加语法调查、时间轴和标签，`reduplication` 生成重叠形态。输出不得覆盖已有文件，并须位于 `build/` 内。

`tools/benchmark_modules.py --output build/performance --sizes 1000 10000` 可运行 Windows 下的跨模块实验。它会生成自己的数据库和短音频。单项耗时含服务端处理与序列化，不包含实际界面渲染；首次测量不清空操作系统文件缓存。需要实测后再报告性能，不能把内部旧材料上的数字直接用于此生成器。

`tools/migrate_paradigm_inheritance.py` 提供旧形态表释义的转换计划，并供相应回归测试使用。传入数据库路径时默认只预览；显式添加 `--apply` 才会备份并应用能精确还原原标注的转换。

## 修改与发布

新增数据关系时同时核对删除、复制、跨语言交换、撤销重做、检索、分析与导出。更改前端交互时补充能检测实际行为的回归用例。

版本号只有作者明确决定时才更新；同步核对 `app_info.py`、`packaging/Corporium.iss` 和 `packaging/version.txt`，其余修正覆盖同名产物并重做校验。构建前验证内置示例，使用独立依赖环境，保留第三方许可。不要提交 `data/`、`build/`、`release/`、本地环境或个人媒体。

## 当前共享入口

- 整词补全：`sentence_dictionary.py`、`word_analysis_memory.py`及`web/sentence-dictionary.js`；边界取自`segmentation.FORM_MARKERS`，业务预览可维护派生索引，但不能修改研究资料。采用分析须核对稳定词格、局部结构身份、具体关联及撤销。
- 独立句：`example_groups.py`与`example_numbering.py`；固定编号不是引用身份，组成员和调查本处资料分别保存。复制编号只作用于输出。
- 录音：`recorder.py`、`audio_capture.py`、`web/recorder.js`；试音只在内存，正式录音才自动归档。模拟PCM和设备枚举不能代替实际音质验收。
- 界面语言：`ui_localization.py`、`web/i18n.js`与`web/i18n-messages.json`；只翻译作者界面文案，用户材料、类名和备注保持原文。新文案可用现有的双语消息接口，不运行历史一次性全源转换。
- 管理层排序／字号：`annotations.py`、`web/layer-order.js`及共享`layerStyle`；正文比例基于全局rem，不能重新按父容器缩小或写回层设置。
- 词典入典后刷新：证据区`refreshCurrentExamples`保留页码及其他详情DOM，目录和计数独立刷新；更换词条／工作区后不能恢复旧滚动位置。

[整词分析](WORD_ANALYSIS_REUSE.md)、[录音](RECORDING.md)和[界面语言](INTERFACE_LOCALIZATION.md)说明当前能力及限制。
