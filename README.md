# Corporium

Corporium 是面向田野语言学调查的本地多语言语料工作区，提供中文／English界面。当前源码版本为 **0.9.01030**，桌面安装版面向 Windows 10/11 x64；尚未提供或验收macOS安装版。

文本、独立例句、词典与共享语素、语法调查、音视频时间轴和分析共用资料及稳定引用，数据保存在本地SQLite。

截至2026-10-30的同号源码包含下划线单一标注及模板继承修正、词典删除状态刷新、快捷入典语法标签／词类下拉、保存例句同步右侧面板，以及候选批量范围及未选原因说明、例句操作位置跟随、词典删除内容后确认保存及失效关联解除、形态表模板自动同步、整篇文本复制、共用复制选择、例句统一字号／保存后对齐；另含分类与释义标签、统计筛选、音系重归类、搜索及播放缩放修正。已纳入2026-10-30的0.9.01030安装包。

**最新安装包已同号重建（2026-10-30）**：版本保持0.9.01030，已纳入下方全部近期源码修正，包括时间轴配色／下划线、主页音频轮播、空形态表、数字标签继承、重做恢复及词典布局等。两份源码各36项发布相关后端和527项完整前端通过；新冻结程序自检、中英文首次／恢复启动及无项目Docoid首屏通过。历史段落中的“仅源码”描述指当时状态，现已纳入本次安装包。

The Windows installer has been rebuilt from the latest source while retaining version 0.9.01030. It includes all recent source updates listed below. Frozen runtime checks, Chinese and English first launch, project restoration and the projectless Docoid start screen passed. Earlier source-only notes describe the development stages before this rebuild.

**此前例句样式与主页轮播（当时仅源码）**：时间轴采用原句完整显示数据，分析复用共享词格；重叠配色、整词关联下划线及基底解除后的状态与文本／独立例句一致。主页播放音频时暂停累计10秒计时，播放结束后继续剩余时间；IPA加大12%，翻译缩小8%，只作用于轮播区。中英文核对，两份源码各126项相关后端和527项完整前端通过。版本0.9.01030，本轮不重建安装包。

Timeline sentences now use the source sentence's enriched display data, and analysis uses the shared word renderer. Reduplication colors and completed-link underlines follow the same source state. Home rotation pauses its accumulated ten-second countdown while audio loads or plays, then resumes the remaining time on completion, stop or failure. Home IPA is 12% larger and translations 8% smaller, while ordinary example sizes remain unchanged. Both interfaces are supported; these changes are source-only.

**此前空表、重做与标注继承修正（仅源码）**：形态表允许空词形，整表为空时可保留、移除或取消保存；空项不匹配例句。重做创建后恢复词条／语素详情。数字结尾继承标签直接连写，自动关联兼容3sg；旧派生标注更新而保留本句覆盖。移除各例句底部重叠计数行，快捷表支持方向键。中英文实测，186项相关后端及518项完整前端通过，不重建安装包。

Inflection tables may be partially or entirely empty. Saving an empty table offers Keep, Remove, or Cancel; blank forms never auto-link. Redo restores entry and morpheme details. Digit-final inherited glosses join the next label directly (pron.3 + SG.DAT → pron.3SG.DAT), with matching support and preserved local overrides. Sentence footers omit reduplication counts, and quick tables support arrow-key navigation. These updates are source-only; the installer is unchanged.

**此前移除失效关联检查（仅源码）**：“标签与检查”移除历史失效关联卡片、检查类型及统计，结果数量和分页同步；词条与语素共用，原记录保留。中英文实测，53项相关后端及511项完整前端通过。不重建安装包。

Labels & checks no longer reports obsolete dictionary links as review items. Their filter, count and dedicated navigation are removed together; remaining checks, label frequencies and pagination remain available. Historical records are preserved. This update is source-only; the installer is unchanged.

**此前编辑与例证精简（仅源码）**：词条备注、词类用法备注及义项用法说明默认折叠，点击可展开编辑；再次打开编辑器仍默认折叠，内容完整保留。语素沿用原有单层备注折叠，不增加嵌套。压缩“书写形式”“词类用法与义项”标题和说明之间的留白。语言／词形、附加标签／登记语法标签、基本条目／关系三组单行控件统一高度；大量词条时把基本条目筛选框提到成对字段上方，保证两侧选择框对齐。词典例证不再显示自动／候选匹配写入的“批量关联”“须人工确认”等操作说明，也不生成空备注段落；移除无条件显示的旧核对说明和重复关联记录说明。用户手写研究备注继续显示。新建普通、多部分及独立例句的自动关联不再把匹配原因写入备注；匹配预览仍显示选择依据。旧资料仅按显示规则过滤已知机器说明，不改写原记录，实际失效关联的定位提示保留。中英文实测，121项相关后端和511项完整前端通过；按要求不重建安装包。

Entry, POS-group and sense notes now start collapsed, without losing their saved content. Paired controls have equal heights, and dictionary evidence cards omit generated matching-operation notes and empty paragraphs while retaining research notes. These changes are source-only; the installer is unchanged.

**此前词典标题布局（仅源码）**：词条标题与“尚未分类”等分类文字改为按自身内容排列，不再套用整块详情栏的固定两列；分类不拆成单字竖排，长标题可换行。操作按钮作为独立组保留完整文字，空间不足时整组移到下一行，组内再紧凑换行。词条和语素的编辑、复制、录音、媒体管理、删除及转换／归并按钮统一字号、间距和高度。书写形式与义项的原有对齐保持。中英文19组布局及509项完整前端通过，按要求不重建安装包。

Dictionary entry and morpheme headings now keep titles, classification labels and action buttons from squeezing one another. Action groups wrap when needed; long titles, 150% text size and narrow panels are supported. This is a source-only update; the installer is unchanged.

此前整词重叠与同形下标补充也仅源码，尚未纳入安装包：补齐上一轮遗漏的整词重叠：整个词格都是已确认的重叠成分时，其有效基底范围已关联词典，即显示关联完成下划线；解除基底关联后同步消失，撤销／重做同步恢复。支持跨词格基底、指向具体语素／组合及连续重叠关系。基底只关联其他片段、未覆盖被选范围时不算完成；失效／待核对关系不传播完成状态。显示计算不生成重叠部分自己的词典关联。删除两个同形词条之一后，自动清除剩余词条不再需要的下标，列表与详情同步；撤销恢复两项及原编号，重做再次清除。三个以上只删除一项时保留其余编号，不影响其他语言／大小写不同的形式。词条转为语素、离开原同形组时也清理原组。语素条目原有display_number按当前同形数量隐藏下标的逻辑保留，已验证删除任一同形项、列表／详情／统一词典读取及撤销重做；内部number保持稳定。

Whole-word reduplicants now follow their linked bases, including unlink, undo and redo. Deleting one of two homonymous entries clears the remaining subscript; morpheme display numbering is also verified. These changes are source-only and are not included in the existing 0.9.01030 installer.

## 当前功能

- **首屏 Docoid／语言选择与重叠词格关联完成（2026-10-30，同号重建）**：桌面首次选择项目的界面默认使用Docoid，与工作区共用主题样式，保留已保存的皮肤偏好。顶部常驻“语言 / Language”选择，可在打开项目之前切换中文／English，选择写入桌面偏好，创建项目及再次启动时继续沿用。词格中已确认重叠关系的重叠部分不再要求单独入典；其余成分全部关联词典后显示关联完成下划线。例：`je~jepasu`中确认je重叠自jepasu，只关联jepasu即可完成；`je~jepasu-na`中的na仍须关联。仅有`~`候选、失效／待核对关系不免除要求；没有实际词典关联的纯重叠词格不会凭空完成。不修改已存词典关联或统计次数。文本、独立例句、词典例证、调查、时间轴及分析共用此判断，重叠关系编辑、删除及撤销后随读取刷新。中英文界面共用；已纳入同号安装包。[验证范围](docs/VERIFICATION.md)。

The first project-selection screen now defaults to Docoid and provides a visible Chinese / English selector before a project is opened. Confirmed reduplicants need no separate dictionary link for the word to be underlined as complete; every other component must still be linked. Language choices persist across project creation and restart. These changes are included in the rebuilt 0.9.01030 installer.

- 0.9.01030已于2026-10-30重新打包，收录下列全部近期修改；安装器和程序版本一致，保留安装目录选择及项目恢复。冻结自检、中英首次和恢复启动通过。[实际范围](docs/VERIFICATION.md)。

- 下划线`_`按同一标注内的空格替代字符保留，旧例句在编辑中自动合为单格，不是语素或标签边界。标签、匹配、统计、复制和变形表模板继承同步，中英文共用；原文、引用和导出拼写保留。

- 解除关联后立即更新词条／语素删除状态；快捷入典支持独立语法标签及持续显示全部词类的下拉；保存例句同步右侧面板并保留有效草稿。语法标签与简短标注分别保存，可选是否显示；原单位失效时关闭旧面板，中英文同步。

- 自动关联候选的“全选”原来只选择无歧义且无冲突的项，现明确改名为“选择全部无歧义项”。同一用例的多个目标标出“候选1/2、2/2，请选一项”；共用语素片段的候选另说明须手选。底部明确提示哪些用例未被自动勾选。单处只保留一个目标，批量选择保留已有手选，取消勾选仍清空选择；尚未展开的无歧义候选也参与。中英文同步。

- 共用例句在打开右侧关联面板、切换词格／页签、保存或解除关联及原位保存标注时，跟随正在操作的句子和词格。切换词格保持侧栏连续打开，避免正文先变宽再缩窄；保存刷新实际来源页面，词典例证保留当前页。时间轴同时保持句子内部滚动和外层位置。主动滚动、换语言／工作区或选择其他词条／语素时停止旧定位，未保存草稿沿用原保护。中英文共用。

- 删除义项、用法、词形或变形表后，保存时列出将失效的例句关联并确认；确认后允许保存，只解除失效关联，保留例句当前词形和标注（包括空白本句覆盖）。仍有效的关联继续跟随词典；取消保留编辑草稿，整次修改可一步撤销重做。词条完整／快捷编辑及原生语素均支持，中英文同步。

- 形态表模板修改自动同步到已使用的词条；有内容的删除先列出影响并确认，草稿连续编辑，整次可撤销。未删行、自建行和本句标注保留，中英文同步。

- 带格式复制共用文本操作勾选框，句头更紧凑；简要、独立句组与窄窗大字号同步。新建菜单支持复制整篇文本，保留句序、标注、词典关联、发言人和独立音频对齐，可一步撤销。中英文同步。

- 例句四行使用同一默认字号，语言各行比例独立计算；阅读、原位编辑和分析例句同步；首页轮播另将IPA加大12%、译文缩小8%。编辑按语素边界对齐，点号标签属于同一语素；保存清理空格并重新检查。附加标签、显示开关与分类管理支持英文界面。

- 简短释义与可选语法标签分别保存，可按义项决定是否显示，完整／快捷编辑共用。空词格的等号、重叠和中缀边界正确清理；类列表支持同级拖动排序并记忆，管理类时保留词条／语素草稿；删除解除绑定，主要词形保留。文本新句保存后原位保留。

- 左上角语言名称跟随全局界面字体与变体，本地名称保留语言IPA字体；词形变化表在中文完整编辑中显示“变形表”，英文界面使用原英文标题。
- 统计可选词典词条或语素，复用侧栏的条目字段与分类条件：如只看后缀、某个自建形态类／语义类，再按条目、分类或字段汇总。支持全部／任一条件、例证定位、收藏、快照与JSON；未分类另列、多归属提示重叠，统计条件仅匹配条目自身。符合条件条目数和范围中实际出现条目数分开，总体词形统计保留材料范围语义。
- 语料分析的“词次、词形与语素统计”显示总词次、不同词形数、分篇词形数，以及词形／语素／词根／词干／词缀频率，可筛选排序、查看原句、保存快照和导出完整JSON。完整词形保留声调和边界，默认区分大小写；语素依据当前有效关联，变体按同一条目归并，同形不同条目保留，不按字符串剥除词缀。分别显示语素次数、涉及词次及关联覆盖数；自然文本与诱导材料应按来源分别选择。
- 同音语素表修改音系后，仍适用的确认归类保留；失效记录按当前清单重新匹配，唯一候选可整批确认，歧义／无匹配留待处理，支持撤销重做，原读音不改写。
- 词条快捷／完整编辑中的语素关联及合并／转换目标选择，仅搜索条目自身信息；例句、附加标注和媒体内容不会带出无关候选，过滤先于分页。语素目录仍支持例证全文检索。
- 播放中连续缩放按帧合并，复用已有轨道与区间，不再反复完整加载时间轴。相同词条／用法中，基本形式和变形表的词形、完整标注一致时，自动关联及空白补全仅保留基本义项候选；真正的同形词／多义仍须选择。
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

2026-10-30发布0.9.01030：98个Python运行模块和114个前端资源与开发目录一致；本副本实际通过35项发布相关后端和506项完整前端。公开便携入口、示例验证器及合成夹具适配保留；内置示例同步为清理来源路径的新包。未重跑完整后端，各功能轮次另行保留。[实际验证范围](docs/VERIFICATION.md)。

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
