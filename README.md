# Corporium

Corporium 是面向中文用户的本地语言学语料工作区。当前源码版本为 **0.9.01024**，桌面版主要面向 Windows x64。

支持文本语料与独立例句、逐词和语素标注、词典及语素库、词形变化表、多部分形式与重叠形态、语法标签、语料检索与分析、时间轴及媒体关联、语法调查、附加标注层、撤销重做和项目备份。

词典关联支持默认继承释义和本句覆盖；文本支持 Typst、Excel 与标准 DOCX 交换。DOCX 长例句可以跨表格，导入前可预览、合并和拆分，详见 [DOCX 格式约定](docs/DOCX_TEXT_FORMAT.md)。

## 从源码运行

建议使用 Windows 10/11 x64、Python 3.12 和 Microsoft Edge WebView2 Runtime。在本目录打开 PowerShell：

```powershell
python -m venv .desktop-venv
.\.desktop-venv\Scripts\python.exe -m pip install -r requirements.txt
.\.desktop-venv\Scripts\python.exe -B desktop.py --dev
```

也可以在安装依赖后双击 `Open-Corporium-Dev.cmd`。首次运行会显示项目选择界面，可以在源码目录以外新建项目或打开已有项目；下次启动会尝试恢复上次打开的项目。开发版使用独立的桌面配置目录。

若只调试浏览器界面，运行 `start.ps1`，或用上述环境执行 `python -B server.py`，然后访问 `http://localhost:8765/`。此方式使用本目录下的 `data/`，请不要把运行产生的项目数据提交到仓库。

## 示例与测试

`packaging/examples/Telira.corporium` 是虚构的 Tëlira 示例语言，不含录音或视频。在应用的语言选项中导入内置示例即可使用；不会自动导入到既有项目。

测试使用临时数据库和合成输入，不需要个人语料。前端测试需要安装 Node.js（建议 22 或更新版本），不需要额外的 npm 包。

```powershell
.\.desktop-venv\Scripts\python.exe -B run_tests.py backend
.\.desktop-venv\Scripts\python.exe -B run_tests.py frontend
.\.desktop-venv\Scripts\python.exe -B tools/test_materials.py generate --profile smoke --sentences 100 --output build/smoke/corpus.sqlite3
```

`run_tests.py` 默认运行两组测试，并将后端数据库访问限制在本副本的 `build/` 中。更大的测试材料可以用 `ordinary`、`dense`、`research` 或 `reduplication` 配置生成，句数范围为 1–50000。合成媒体由生成器创建，不依赖外部录音。开发说明见 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)。

本源码副本的实际核对结果见 [验证记录](docs/VERIFICATION.md)。

## 构建安装包

构建方法和外部工具要求见 [packaging/README.md](packaging/README.md)。安装包支持选择安装位置，构建输出位于 `release/`。源码目录不包含安装包、第三方开发环境或构建工具。

## 发布目录与许可

此目录包含运行源码、前端资源、回归测试、合成材料生成器、Windows 构建配置、第三方许可、四款 Junicode 字体及 Tëlira 示例。个人项目、备份、原始媒体、研究工作表和内部开发记录未包含在内。公开更新记录见 [CHANGELOG.md](CHANGELOG.md)。

Corporium 当前许可见 [LICENSE](LICENSE)，内容沿用现有版本的使用许可；本源码副本没有另行选定 MIT、GPL 等标准开源协议。公开源码不等于已经授予标准开源协议中的全部权利；如计划按某种开源协议发布，需由作者另行确定。第三方组件遵循 `packaging/licenses/` 中的各自许可，Junicode 遵循 `font/Junicode/OFL.txt`。
