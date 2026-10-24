"""Double-click launcher: reuse a running corpus or start it without a console."""
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import webbrowser
import ctypes

ROOT = Path(__file__).resolve().parent
URL = 'http://localhost:8765/'


def ready():
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(URL, timeout=1) as response:
            return 'Corporium' in response.read().decode('utf-8')
    except Exception:
        return False


def main():
    if not ready():
        (ROOT/'data').mkdir(exist_ok=True)
        with (ROOT/'data'/'launcher.log').open('ab') as log:
            process = subprocess.Popen(
                [sys.executable, str(ROOT/'server.py')],
                cwd=ROOT, stdout=log, stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        for _ in range(40):
            if ready():
                break
            if process.poll() is not None:
                # Another launcher may have won the race to bind the port.
                if not ready():
                    raise RuntimeError('启动失败，请查看 data/launcher.log。端口 8765 可能被其他程序占用。')
                break
            time.sleep(.25)
        else:
            raise RuntimeError('服务启动超时，请查看 data/launcher.log。')
    webbrowser.open(URL)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        ctypes.windll.user32.MessageBoxW(None, str(exc), 'Corporium 启动失败', 0x10)
