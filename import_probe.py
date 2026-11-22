"""Check an import-time edit without changing the read-only source checkout."""
import importlib
import importlib.abc
import importlib.machinery
import json
import sys
from pathlib import Path

request = json.load(sys.stdin)
root = Path(request['root'])
target = root / request['path']

class Loader(importlib.machinery.SourceFileLoader):
    def get_code(self, fullname):
        return compile(request['source'], str(target), 'exec')

class Finder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname != request['module']:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is not None:
            spec.loader = Loader(fullname, str(root / request['path']))
        return spec

sys.path.insert(0, str(root))
sys.meta_path.insert(0, Finder())
importlib.import_module(request['module'])
