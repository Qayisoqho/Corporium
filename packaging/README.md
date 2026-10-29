# Windows 构建

源码版本：0.9.01030。推荐 Windows 10/11 x64、Python 3.12。

本次0.9.01030同号重建已纳入项目选择页Docoid／顶部中英语言选择，以及重叠词格完成下划线修正。开发与公开副本各76项相关后端、509项完整前端通过；冻结程序自检及中英无项目首屏、首次／恢复项目启动通过。当前安装包SHA-256：`CBD0114EC04691E4F08048B13522EBF7C35E2B265126F0BD623D8A7728F4C2A1`。完整范围见[验证说明](../docs/VERIFICATION.md)。

## 准备

1. 安装 Python，以及 Inno Setup 6（需能找到 `ISCC.exe`）。
2. 从 Microsoft 官方渠道取得 WebView2 Evergreen Standalone Installer 的 x64 版本，保存为根目录下 `build-tools/MicrosoftEdgeWebView2RuntimeInstallerX64.exe`。构建脚本会核对有效的 Microsoft 数字签名。
3. 保留 `packaging/licenses/`、`font/Junicode/` 和 `packaging/examples/`。所需的 Tëlira 包已包含在源码中，无需任何本地个人项目。

官方入口：[Python](https://www.python.org/downloads/)、[Inno Setup](https://jrsoftware.org/isdl.php)、[WebView2](https://developer.microsoft.com/microsoft-edge/webview2/)。外部构建工具不随源码提供。

## 构建

在源码根目录运行，将编译器路径改成自己安装的位置：

```powershell
powershell -ExecutionPolicy Bypass -File packaging/build-windows.ps1 -Python python -Iscc 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
```

脚本创建独立的 `.desktop-venv`，安装固定版本依赖，验证内置示例，收集当前构建环境的第三方许可，再生成程序和安装包。已安装依赖时可以加 `-SkipDependencies`。

程序输出在 `release/app-0.9.01030/Corporium/`，安装包在 `release/Corporium-0.9.01030-Windows-x64-Setup.exe`。这些目录由构建产生，已被忽略，不应作为源码提交。安装向导允许选择位置；项目数据由用户另行选择。

`prepare_example.py` 只验证附带的虚构示例包，不连接个人数据库。`Corporium.spec` 仅收集程序资源、四款 Junicode 字体、许可和示例，不会收集用户项目或媒体。

发布前运行根目录的两组回归测试，再在隔离项目中验证安装、创建项目、重启恢复项目和卸载。源码自检与已打包程序自检不能替代实际安装验证。

## 当前构建约定

同一个安装包和安装向导支持中文／English，语言文件在`packaging/languages/`，保留目录选择和项目恢复。只有作者明确更新版本号时，才同步修改`app_info.py`、`Corporium.iss`和`version.txt`；其他修正保持版本，覆盖同名输出并重新核对校验和。

现场录音原件在用户项目`media/recordings`，与data、font并列；试音不自动落盘。不要把用户项目放在安装目录中，也不要将这些目录加入构建资源。

公开副本只携带已清理来源路径的虚构示例，`prepare_example.py`继续只验证该包，不依赖开发者的测试项目。公开源码验证与某次开发目录的安装包验证是不同证据，详见[当前验证](../docs/VERIFICATION.md)。

2026-10-27时的0.9.01026.4同号修订：自定义层／指定书写类型查找替换；自动关联成功后保留并更新其余候选，放大及窄窗底栏对齐。构建仍覆盖同名产物。

2026-10-30发布0.9.01030：收录全部近期源码更新，Windows数值版本0.9.1030.0。新版本输出使用新文件名，保留旧包；本地构建环境与打包程序检查范围见[验证说明](../docs/VERIFICATION.md)。
