"""Build test/line dependencies from the pristine pinned checkout, never patches."""
import builtins
import io
import json
import gzip
import os
import sys
import concurrent.futures
import pickle
from pathlib import Path

import coverage
import pytest

def main():
    ROOT = Path(sys.argv[1]).resolve()
    OUT = Path(sys.argv[2]).resolve()
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    os.environ['SKIP_INTEGRATION'] = '0'
    os.environ['PATH'] = str(Path(sys.executable).parent) + os.pathsep + os.environ['PATH']
    # Execute worker jobs synchronously during instrumentation so their source
    # lines retain the owning pytest context. Pickle arguments as the real
    # process executor does, preventing mutation of caller-owned expressions.
    class InstrumentedPool(concurrent.futures.Executor):
        def __init__(self, *args, initializer=None, initargs=(), **kwargs):
            if initializer:
                initializer(*initargs)

        def submit(self, fn, *args, **kwargs):
            future = concurrent.futures.Future()
            try:
                args, kwargs = pickle.loads(pickle.dumps((args, kwargs)))
                future.set_result(pickle.loads(pickle.dumps(fn(*args, **kwargs))))
            except BaseException as e:
                future.set_exception(e)
            return future

        def shutdown(self, wait=True, **kwargs):
            pass

    concurrent.futures.ProcessPoolExecutor = InstrumentedPool
    cov = coverage.Coverage(data_file=None, source=[str(ROOT / 'sqlglot'), str(ROOT / 'tests')])
    current = ''
    reads = {}
    shared_reads = {}
    class_uses = {}
    class_cache = {}
    collected = []
    original_open = builtins.open
    original_io_open = io.open

    def profile(frame, event, arg):
        if event != 'call' or not current:
            return
        code = frame.f_code
        if code.co_name not in ('__init__', '__new__') or not code.co_varnames:
            return
        # Constructors expose the concrete runtime type, including inherited
        # parser/tokenizer/generator classes whose constants ran at import time.
        first = code.co_varnames[0]
        if first not in ('self', 'cls'):
            return
        obj = frame.f_locals.get(first)
        cls = obj if isinstance(obj, type) else type(obj)
        keys = class_cache.get(cls)
        if keys is None:
            keys = []
            for base in cls.__mro__:
                module = base.__module__
                if module == 'sqlglot' or module.startswith('sqlglot.'):
                    keys.append(module + ':' + base.__qualname__)
            class_cache[cls] = keys
        for key in keys:
            class_uses.setdefault(key, set()).add(current)

    def track(path):
        if not current or not isinstance(path, (str, os.PathLike)):
            return
        try:
            rel = Path(path).resolve().relative_to(ROOT).as_posix()
        except (ValueError, OSError):
            return
        reads.setdefault(rel, set()).add(current)
        frame = sys._getframe(1)
        while frame:
            if frame.f_code.co_name in ('setUpClass', 'setUpModule'):
                shared_reads.setdefault(rel, set()).add(current.split('::')[0])
                break
            frame = frame.f_back

    def traced_open(path, *args, **kwargs):
        track(path)
        return original_open(path, *args, **kwargs)

    def traced_io_open(path, *args, **kwargs):
        track(path)
        return original_io_open(path, *args, **kwargs)

    class Plugin:
        def pytest_collection_modifyitems(self, items):
            collected.extend(item.nodeid for item in items)

        @pytest.hookimpl(hookwrapper=True)
        def pytest_runtest_protocol(self, item, nextitem):
            nonlocal current
            current = item.nodeid
            cov.switch_context(current)
            yield
            current = ''
            cov.switch_context('')

    cov.start()
    sys.setprofile(profile)
    builtins.open = traced_open
    io.open = traced_io_open
    status = pytest.main(['tests', '-q', '--tb=short', '--timeout=120'], plugins=[Plugin()])
    builtins.open = original_open
    io.open = original_io_open
    sys.setprofile(None)
    cov.stop()
    data = cov.get_data()
    mapping = {}
    for filename in data.measured_files():
        try:
            rel = Path(filename).relative_to(ROOT).as_posix()
        except ValueError:
            continue
        mapping[rel] = {str(line): sorted(c for c in contexts if c)
                        for line, contexts in data.contexts_by_lineno(filename).items()}
    # Only mark tests with observed execution as covered. Skipped or interrupted
    # tests remain conservatively selected by the runtime selector.
    measured = sorted(c for c in data.measured_contexts() if c)
    result = {'lines': mapping, 'reads': {p: sorted(v) for p,v in reads.items()},
              'shared_reads': {p: sorted(v) for p,v in shared_reads.items()},
              'class_uses': {p: sorted(v) for p,v in class_uses.items()},
              'collected': measured, 'pytest_status': int(status)}
    names = sorted({c for file in mapping.values() for contexts in file.values() for c in contexts})
    indices = {name: i for i, name in enumerate(names)}
    result['names'] = names
    result['lines'] = {path: {line: [indices[c] for c in contexts] for line, contexts in lines.items()}
                       for path, lines in mapping.items()}
    opener = gzip.open if OUT.suffix == '.gz' else open
    with opener(OUT, 'wt') as f:
        json.dump(result, f, separators=(',', ':'))
    print(f'Wrote {OUT}: {len(collected)} tests, pytest status {status}', file=sys.stderr)


if __name__ == "__main__":
    main()
