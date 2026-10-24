"""Read-only access to the notices shipped beside the application assets."""
from pathlib import Path
import app_info

ROOT = Path(__file__).resolve().parent
APP_LICENSE = 'Corporium-LICENSE.txt'
RUNTIME_LICENSE = 'Microsoft-WebView2-Runtime-LICENSE.txt'
NOTICES = 'THIRD-PARTY-NOTICES.txt'
ASSET_PATHS = {'/licenses', '/license-notices.js', '/license-notices.css',
               '/licenses/catalog', '/licenses/document', '/licenses/developer-font', '/style.css'}


def directory():
    bundled = ROOT / 'licenses'
    return bundled if bundled.is_dir() else ROOT / 'packaging' / 'licenses'


def documents():
    root = directory().resolve()
    return {p.name: p for p in root.iterdir()
            if p.is_file() and p.resolve().parent == root
            and p.suffix.lower() not in {'.py', '.pyc', '.pyo'}
            and p.stat().st_size <= 2 * 1024 * 1024}


def catalog():
    titles = {APP_LICENSE: 'Corporium 使用许可', RUNTIME_LICENSE: 'Microsoft WebView2 许可',
              NOTICES: '第三方组件与隐私说明'}
    names = documents()
    order = [n for n in (APP_LICENSE, NOTICES, RUNTIME_LICENSE) if n in names]
    order += sorted(set(names) - set(order), key=str.casefold)
    return {'about': app_info.about(), 'items': [{'id': n, 'title': titles.get(n, n),
                       'group': 'app' if n == APP_LICENSE else 'third_party'} for n in order]}


def document(name):
    path = documents().get(name)
    if path is None:
        raise ValueError('未找到这份许可文件')
    raw = path.read_bytes()
    encoding = 'utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
    return {'id': name, 'text': raw.decode(encoding, errors='replace')}
