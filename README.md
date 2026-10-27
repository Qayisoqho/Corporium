# Corporium

Corporium 是面向田野语言学调查的本地多语言语料工作区，提供中文／English界面。当前源码版本为 **0.9.01026.4**，桌面安装版面向 Windows 10/11 x64；尚未提供或验收macOS安装版。

文本、独立例句、词典与共享语素、语法调查、音视频时间轴和分析共用资料及稳定引用，数据保存在本地SQLite。

## 当前功能

- 查找替换支持单个／全部自定义标注层，以及词条／语素中指定书写类型；逐词和整句附行分别处理，保留稳定身份与引用。自动关联执行一种操作后自动更新剩余候选，保留有效的勾选／未勾选状态，可直接继续另一种关联。
- 文本与独立例句共用逐词编辑、语素分析、附加标注层、检索替换和标签检查。附加层在管理窗口拖动排序；字号按全局比例×本层比例叠加，110%×110%=121%。
- 独立例句有固定编号，默认按添加顺序排列，可切为新到旧；可将已有句子组成例句组，保留a／b／c、Q／A、合法性和媒体关联，调查可整组引用。文本句不参与分组。
- 顶部“带格式复制”选择本页例句，确认复制到Word；保留字体、逐词对齐、组内标号和判断，复制主编号按所选顺序连续排列。语素／标注各占一行；超过表格限制时提示并分表，不丢词格。
- 词典／语素支持词类、义项、变体、词形变化表、多部分形式和重叠分析。具体关联默认继承释义，本句覆盖和解除关联时冻结标注；删除、复制、语言交换和撤销保留关系。
- “补全空白标注”可选择词典候选或已有完整整词分析，涵盖`-、=、+、~、<>`，保留中缀音段和有效分析／关联。“收入词典”可选择已有词类或输入新类随保存登记；词典例句区保存保留页码及位置。[使用与范围](docs/WORD_ANALYSIS_REUSE.md)。
- 词典／语素、独立例句及时间轴可现场录音。试音不自动保存，可手动下载；正式录音保存在项目`media/recordings`并直接关联，文本句不提供单独录音。[录音说明](docs/RECORDING.md)。
- 支持Typst、Excel及标准DOCX文本交换、语法调查、调查笔记、句级时间对齐、音视频播放、波形、语料分析、按语言撤销重做和项目备份。[DOCX约定](docs/DOCX_TEXT_FORMAT.md)。

语言切换位于“工作区域与备份设置 → 全局设置 → 语言设置”，项目选择页也可选择。切换界面语言不翻译研究材料。[界面语言与维护](docs/INTERFACE_LOCALIZATION.md)。

## 从源码运行

建议使用Windows x64、Python 3.12和Microsoft Edge WebView2 Runtime。在本目录打开PowerShell：

```powershell
python -m venv .desktop-venv
.\.desktop-venv\Scripts\python.exe -m pip install -r requirements.txt
.\.desktop-venv\Scripts\python.exe -B desktop.py --dev
```

安装依赖后也可双击`Open-Corporium-Dev.cmd`。首次选择新建／打开项目；下次恢复上次成功打开的项目。开发配置与正常安装版分开。

浏览器调试可运行`start.ps1`，访问`http://localhost:8765/`。此方式使用本目录的`data/`；修改后端须停止旧服务再启动。个人项目建议放在源码目录以外。

## 示例与测试

`packaging/examples/Telira.corporium`是虚构的Tëlira示例语言，不含音视频或本机来源路径。通过语言选项导入内置示例，不会自动写入已有项目。

测试使用临时数据库和合成输入。前端测试需要Node.js，不需额外npm包：

```powershell
.\.desktop-venv\Scripts\python.exe -B run_tests.py backend
.\.desktop-venv\Scripts\python.exe -B run_tests.py frontend
.\.desktop-venv\Scripts\python.exe -B tools/test_materials.py generate --profile smoke --sentences 100 --output build/smoke/corpus.sqlite3
```

`run_tests.py`默认运行两组测试，将后端数据库访问限制在本副本`build/`内。生成器支持`smoke`、`ordinary`、`dense`、`research`及`reduplication`，句数1–50000；媒体输入可由合成生成器提供。开发说明见[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)，本副本实际核对结果见[docs/VERIFICATION.md](docs/VERIFICATION.md)。

## 构建与版本

[Windows构建说明](packaging/README.md)包含外部工具要求。输出为`release/app-0.9.01026.4/Corporium/`和同版本安装包；源码不携带构建工具、环境或安装包。

版本号只在作者明确决定时更新；同版本修正覆盖同名安装包，同时更新校验和及验证记录。资料项目保存在安装目录以外，卸载不删除外部项目。

## 目录与许可

本副本包含运行代码、前端、回归测试、合成材料工具、构建配置、许可、四款Junicode字体和虚构示例。内部开发交接／历史、个人项目、备份、研究工作表及机器专用验证材料不包含在此。公开更新见[CHANGELOG.md](CHANGELOG.md)。

许可见[LICENSE](LICENSE)。本副本沿用现有使用许可，没有另行选定MIT或GPL等标准开源协议；是否采用其他协议由作者决定。第三方组件使用各自许可，见`packaging/licenses/`；Junicode见`font/Junicode/OFL.txt`。
