# Build from an isolated environment; only the approved example data is included.
from pathlib import Path
root=Path(SPECPATH).parent
datas=[(str(root/'packaging'/'Corporium.ico'),'packaging'),(str(root/'web'),'web'),(str(root/'packaging'/'licenses'),'licenses')]
for name in ('Junicode.ttf','Junicode-Italic.ttf','Junicode-Bold.ttf','Junicode-BoldItalic.ttf'):
    datas.append((str(root/'font'/'Junicode'/name),'font/Junicode'))
datas.append((str(root/'packaging'/'licenses'/'Junicode-OFL.txt'),'font/Junicode'))
datas.append((str(root/'packaging'/'examples'/'Telira.corporium'),'packaging/examples'))
datas.append((str(root/'packaging'/'examples'/'README.txt'),'packaging/examples'))
a=Analysis([str(root/'desktop.py')],pathex=[str(root)],binaries=[],datas=datas,
    hiddenimports=['webview.platforms.winforms','webview.platforms.edgechromium','clr_loader','pythonnet'],
    excludes=['PyQt5','PyQt6','PySide2','PySide6','tkinter'],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='Corporium',debug=False,strip=False,upx=False,console=False,icon=str(root/'packaging'/'Corporium.ico'),version=str(root/'packaging'/'version.txt'))
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='Corporium')
