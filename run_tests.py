"""Run regression tests using disposable databases inside build/t only."""
from pathlib import Path
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent

def backend(pattern='test_*.py'):
    scratch = ROOT/'build/t'
    scratch.mkdir(parents=True, exist_ok=True)
    tempfile.tempdir = str(scratch)
    os.environ.update(TEMP=str(scratch), TMP=str(scratch), PYTHONDONTWRITEBYTECODE='1')
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
    def protect_database(event, args):
        if event != 'sqlite3.connect':
            return
        value = os.fsdecode(args[0])
        if value == ':memory:' or value.startswith('file::memory:'):
            return
        if value.startswith('file:'):
            value = unquote(value[5:].split('?', 1)[0])
            if os.name == 'nt' and value.startswith('///'):
                value = value[3:]
        if not Path(value).resolve().is_relative_to(ROOT/'build'):
            raise RuntimeError('Regression tests may access only databases inside build/')
    sys.addaudithook(protect_database)
    suite = unittest.defaultTestLoader.discover(str(ROOT/'tests'), pattern=pattern)
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1

def frontend():
    node = shutil.which('node')
    if not node:
        raise SystemExit('Install Node.js to run the frontend tests.')
    files = sorted((ROOT/'tests').glob('*.cjs')) + sorted((ROOT/'tests').glob('test_*.js'))
    return subprocess.call([node, '--test', *[str(p) for p in files]], cwd=ROOT)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('suite', choices=['all', 'backend', 'frontend'], nargs='?', default='all')
    parser.add_argument('--pattern', default='test_*.py', help='Backend test filename pattern')
    args = parser.parse_args()
    os.chdir(ROOT)
    statuses = []
    if args.suite in ('all', 'backend'):
        statuses.append(backend(args.pattern))
    if args.suite in ('all', 'frontend'):
        statuses.append(frontend())
    return int(any(statuses))

if __name__ == '__main__':
    raise SystemExit(main())
