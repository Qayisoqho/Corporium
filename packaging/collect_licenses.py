"""Collect the notices of the isolated build environment for redistribution."""
from importlib.metadata import distributions
from pathlib import Path
import shutil
import sys

root=Path(__file__).resolve().parent/'licenses'
root.mkdir(exist_ok=True)
for dist in distributions():
    for file in dist.files or ():
        if file.suffix.lower() not in {'.py','.pyc','.pyo'} and file.name.lower().startswith(('license','copying','notice','authors')):
            source=Path(dist.locate_file(file))
            if source.is_file():
                name=dist.metadata['Name']+'-'+str(file).replace('/','_').replace('\\','_')
                shutil.copyfile(source,root/name)
python_license=Path(sys.base_prefix)/'LICENSE.txt'
if python_license.exists():shutil.copyfile(python_license,root/'Python-LICENSE.txt')
# Remove only non-document artifacts emitted by the older collector.
for artifact in root.iterdir():
    if artifact.is_file() and artifact.suffix.lower() in {'.py','.pyc','.pyo'}:
        artifact.unlink()
required=('Corporium-LICENSE.txt','Microsoft-WebView2-Runtime-LICENSE.txt','THIRD-PARTY-NOTICES.txt','Junicode-OFL.txt')
for name in required:
    if not (root/name).is_file():raise RuntimeError('Missing distribution notice: '+name)
