# Windows 构建

源码版本：0.9.01024。推荐 Windows 10/11 x64、Python 3.12。

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

程序输出在 `release/app/Corporium/`，安装包在 `release/Corporium-0.9.01024-Windows-x64-Setup.exe`。这些目录由构建产生，已被忽略，不应作为源码提交。安装向导允许选择位置；项目数据由用户另行选择。

`prepare_example.py` 只验证附带的虚构示例包，不连接个人数据库。`Corporium.spec` 仅收集程序资源、四款 Junicode 字体、许可和示例，不会收集用户项目或媒体。

发布前运行根目录的两组回归测试，再在隔离项目中验证安装、创建项目、重启恢复项目和卸载。源码自检与已打包程序自检不能替代实际安装验证。
