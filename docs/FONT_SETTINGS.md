# 字体顺序与标注行设置

## 使用

在“管理 → 全局设置 → 字体设置”中搜索字体，点击候选即可加入全局顺序。标签左边的序号表示优先级；拖动把手，或聚焦把手后使用方向键、Home、End 调整顺序。× 移除字体，“恢复默认顺序”回到 STIX Two Text → Microsoft JhengHei（微软正黑体，使用系统字体）。末尾始终保留通用无衬线回退。字体按缺字情况逐步回退，预览包含中文、拉丁字母、IPA 和组合附标。

候选区可按随附、本机系统、font 文件夹等来源筛选。同名的不同来源可以分别选择；系统字体不会复制进项目或安装包。`font` 文件夹继续支持 TTF、OTF、WOFF 和子文件夹；本轮没有新增 TTC、OTC、WOFF2 文件解析器。Windows 系统字体由操作系统枚举，不受这个文件解析器格式列表的限制。新装字体后点击“重新扫描字体”；返回窗口时也会检查更新。

改变顺序、增删字体或选择界面变体只影响设置页预览，点击“保存设置”后应用到主界面。取消修改会立即恢复已保存的字体标签及顺序，并取消尚未落下的拖动。搜索和来源筛选不会被当作未保存的字体设置。

在“语言信息与设置”中，IPA、语素、标注、自由翻译各行可以选择“跟随全局字体”，也可以指定一个优先字体；指定字体缺字时继续尝试全局字体。四行的变体和字号比例保持独立。“标注层管理”的逐词、IPA 附行、翻译附行也可以跟随全局，层自己的变体、字号和间距继续生效。

Corporium品牌字样固定使用Junicode，包括主页大标题、进入按钮中的品牌文字和底栏品牌；更换全局字体不会改变它们。首页滚动例句的IPA和翻译分别使用该句所属语言的对应行字体；只有该行选择“跟随全局字体”时才继承全局链，没有IPA的原文采用该语言的语素字体。字形变体和行字号比例也按语言设置。来源、说明和操作文字等界面文字跟随本机全局字体顺序，保存后生效。语料正式阅读／编辑中的语言行与附加层仍按各自设置显示，不因首页展示而改写。

找不到字体时保留原选择并继续回退。全局顺序属于本机偏好；语言和附加层中的“跟随全局”随研究数据保存，换一台电脑后跟随那台电脑的全局设置。项目中的 `font` 文件和本机字体不会自动包含在研究数据包或完整备份中，迁移时仍需单独处理。

English UI: **Manage → Global settings → Fonts**. Click fonts to add tags; drag handles or use arrow keys to reorder. **Follow global fonts** is available for the four language rows and extra tiers. Save applies the draft; Discard restores the saved order. System fonts remain on the computer.

## 默认字体与授权（2026-11-07）

STIX Two Text 2.13 b171按SIL OFL1.1随附，包含正体／斜体的Regular、Medium、SemiBold、Bold。`font/STIXTwoText`保存原始字体、OFL、版权／来源／校验记录；不安装到系统。原随附Noto Sans及思源黑体从当前字体目录与安装包移除，其他用户字体保留。

Microsoft JhengHei即微软正黑体，仅通过字体名调用系统现有字体，不复制、转换、提供下载或打包。Windows允许在CSS回退链中引用字体名，随软件分发文件则需额外授权；文档嵌入许可不能用于应用打包。缺少微软正黑体时继续用系统通用回退，中文外观会因系统而异。[微软官方说明](https://learn.microsoft.com/en-us/typography/fonts/font-faq) · [STIX官方许可](https://github.com/stipub/stixfonts/blob/master/OFL.txt)。

恰为旧默认Noto Sans → Source Han Sans SC的全局链在读取时采用新默认，不立即写入存储；其他自定义链和单字体选择保持。旧字体名称保留为系统预设，系统中安装后仍可使用。各标注行的独立字体及变体／字号不变，不批量修改语料或语言设置。

## 开发接续

- `system_fonts.py` 通过 Windows DirectWrite 的系统集合读取家族名称、所有本地化别名及字面名称、字重、斜体、宽度；只返回元数据，不读取或提供系统字体文件下载。引用在各自作用域释放。30 秒进程缓存，显式扫描强制刷新；读取失败保留最近目录并返回错误状态，非 Windows 返回 unsupported。
- `systemfont-<UTF-8 hex>` 为有界可逆标识。名称不依赖本机是否安装而验证，因此缺失字体能保存、交换并保留名字。系统字面注册为独立 CSS 别名，以 `local(完整名称)`／PostScript 名称调用，避免同名随附字体或 font 文件夹字体覆盖系统选择。既有 `localfont-<hash>`、内置名称不变。
- `font_catalog.scan()` 在原目录上附加 `system` 字段，不改原文件服务范围。`valid_font()` 接受内置、文件夹及合法系统标识；`valid_row_font()` 额外接受 `@global`，仅语言四行及附加层使用，书写形式仍用具体字体。
- `web/fonts.js` 统一目录、来源、验证、旧单字体迁移及全局 CSS 链。`web/font-stack.js` 管理草稿标签、指针／键盘排序、搜索及预览。新静态资源 `font-stack.js`／`.css` 显式注册为不访问数据库的路由；仍沿用桌面认证。
- `corporium-typography.uiFonts` 保存有序标识数组，`uiFontNames` 保留标签名，`ui` 兼容保留第一项，`uiVariant` 继续独立。仅存在旧 `ui` 时迁移为单项优先链；旧语言字体及旧行变体／比例不改写，不进行项目数据库批量迁移。
- 隐藏输入 `global-ui-font` 参与原全局设置快照；搜索／来源控件标记为 transient。设置页的字体草稿不调用 `applyTypography()`；保存后写本机偏好，更新 `--global-font-stack`／`--ui-font`。所有行通过 `rowFontCSS()` 复用全局链，行样式不继承全局字重或斜体。
- `corporium-settings-discard` 直接恢复字体草稿，与配色回滚并行，避免依赖异步备份设置读取。指针拖动只有有效松开才变更顺序；Escape、取消、失去捕获、窗口失焦或目录刷新取消悬而未决的拖动。
- 带格式复制将应用内部别名还原为真实字体名数组，输出有序 font-family；Word 的通用家族映射保留。复制不嵌入字体文件，不改变材料。尚未为本轮新增回退数组执行真实 Word 粘贴专项验收；此前 Word 布局验证仍见各轮原报告。

字体链引入验证见[前轮报告](../build/font-stack-20261106/REPORT.html)；当前默认字体、授权、九处对齐和包体证据见[本轮报告](../build/stix-alignment-20261107/REPORT.html)。
