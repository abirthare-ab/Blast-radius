"""Source-derived coverage selection and exact worker-overhead optimization.

No patch identifiers, mutation signatures, or sample answers are used.
"""
import ast
from refine import changed_lines
from attribute_select import choose_attribute
import gzip
import json
import os
import re
import sys
import io
import tokenize
import subprocess
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = Path(os.environ.get('BLAST_DATA', '/data'))
SOURCE = Path(os.environ.get('BLAST_SOURCE', '/opt/sqlglot'))
MAP = Path(os.environ.get('BLAST_MAP', str(HERE / 'dependencies.json.gz')))

@lru_cache(maxsize=256)
def source_tree(path):
    original = (SOURCE / path).read_text()
    return original, ast.parse(original)

@lru_cache(maxsize=256)
def static_class_readers(name, files):
    pattern = re.compile(r'\b' + re.escape(name) + r'\b')
    return {file for file in files if pattern.search((SOURCE / file).read_text())}

def class_scope(tree, line):
    def walk(node, names):
        if isinstance(node, ast.ClassDef):
            names = names + [node.name]
            if node.lineno <= line <= node.end_lineno:
                found.append((node, '.'.join(names)))
        for child in ast.iter_child_nodes(node):
            walk(child, names)
    found = []
    walk(tree, [])
    return min(found, key=lambda pair: pair[0].end_lineno - pair[0].lineno) if found else None

def import_time_shape(tree):
    # Function headers are evaluated while the module/class is initialized.
    # A new required argument or a raising default/decorator must invalidate
    # callers even when no body line would be reached after the edit.
    return [ast.dump(ast.FunctionDef(name=n.name, args=n.args, body=[],
                    decorator_list=n.decorator_list, returns=n.returns,
                    type_params=getattr(n, 'type_params', [])), include_attributes=False)
            for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))] + [
                ('lambda', ast.dump(n.args, include_attributes=False))
                for n in ast.walk(tree) if isinstance(n, ast.Lambda)]

@lru_cache(maxsize=128)
def imports_cleanly(path, source):
    module = path.removesuffix('.py').replace('/', '.').removesuffix('.__init__')
    try:
        result = subprocess.run([sys.executable, str(HERE / 'import_probe.py')],
                                input=json.dumps({'root': str(SOURCE.resolve()), 'path': path,
                                                  'module': module, 'source': source}),
                                text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=3, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False

def split(tests, count):
    workers, loads = [[] for _ in range(count)], [0] * count
    for t in sorted(tests, key=lambda t: (-round(t['seconds'] * 1000), t['number'])):
        i = min(range(count), key=lambda i: loads[i])
        workers[i].append(t['number'])
        loads[i] += round(t['seconds'] * 1000)
    return [w for w in workers if w], max(loads, default=0) + 2000 * sum(bool(w) for w in workers)

def schedule(tests):
    if not tests:
        return []
    return min((split(tests, n) for n in range(1, min(8, len(tests)) + 1)), key=lambda p: p[1])[0]

def changes(text):
    files = []
    current = None
    for line in text.splitlines(keepends=True):
        if line.startswith('diff --git '):
            current = {'path': line.rstrip().split(' b/', 1)[1], 'hunks': [], 'lines': set()}
            files.append(current)
        elif line.startswith('@@ ') and current is not None:
            m = re.match(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', line)
            if not m:
                raise ValueError('unsupported diff')
            old = int(m[1])
            current['hunks'].append([old, int(m[2] or 1), []])
        elif current is not None and current['hunks'] and line[:1] in (' ', '+', '-'):
            current['hunks'][-1][2].append(line)
            if line.startswith('-'):
                current['lines'].add(old)
                old += 1
            elif line.startswith('+'):
                current['lines'].update((max(1, old - 1), old))
            else:
                old += 1
    return files

def apply(original, hunks):
    old = original.splitlines(keepends=True)
    out, offset = [], 0
    for start, count, body in hunks:
        index = start - 1 if count else start
        if index < offset:
            raise ValueError('overlapping hunks')
        out.extend(old[offset:index])
        cursor = index
        for line in body:
            if line[0] in ' -':
                if cursor >= len(old) or old[cursor].rstrip('\n') != line[1:].rstrip('\n'):
                    raise ValueError('context mismatch')
                cursor += 1
            if line[0] in ' +':
                out.append(line[1:])
        if cursor - index != count:
            raise ValueError('hunk length mismatch')
        offset = cursor
    out.extend(old[offset:])
    return ''.join(out)

def choose(patch, tests, dependencies):
    all_ids = {t['id'] for t in tests}
    # New, skipped-in-instrumentation, or otherwise unmeasured tests may inspect
    # source/fixtures even when the Python AST is unchanged.
    selected = all_ids - set(dependencies.get('collected', []))
    files = changes(patch)
    if not files:
        return tests
    for change in files:
        path = change['path']
        if Path(path).is_absolute() or '..' in Path(path).parts:
            return tests
        # Reads catch fixture data as well as source-inspection tests.
        readers = set(dependencies.get('reads', {}).get(path, []))
        selected.update(readers)
        source = SOURCE / path
        if not source.is_file() or not change['hunks']:
            return tests
        if not path.endswith('.py'):
            if not readers:
                return tests
            # setUpClass/session fixtures may be opened only by the first test.
            reader_files = set(dependencies.get('shared_reads', {}).get(path, []))
            selected.update(t['id'] for t in tests if t['file'] in reader_files)
            continue
        try:
            original, before = source_tree(path)
            patched = apply(original, change['hunks'])
            after = ast.parse(patched)
            if tokenize.detect_encoding(io.BytesIO(original.encode()).readline)[0] != tokenize.detect_encoding(io.BytesIO(patched.encode()).readline)[0]:
                return tests
        except (ValueError, SyntaxError, UnicodeError):
            return tests
        if ast.dump(before, include_attributes=False) == ast.dump(after, include_attributes=False):
            continue
        if import_time_shape(before) != import_time_shape(after):
            return tests
        if path.startswith('tests/'):
            own = {t['id'] for t in tests if t['file'] == path}
            if not own:
                return tests
            selected.update(own)
        line_map = dependencies.get('lines', {}).get(path)
        if not line_map:
            return tests
        functions = [n for n in ast.walk(before) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))]
        precise = changed_lines(before, after)
        for line in (precise if precise is not None else change['lines']):
            scopes = [n for n in functions if n.lineno <= line <= n.end_lineno]
            if not scopes:
                enclosing = class_scope(before, line)
                if enclosing is None or 'class_uses' not in dependencies:
                    # Module-level imports and initialization remain global.
                    return tests
                # The import probe overlays one module only. Combined edits
                # requiring this probe retain the full suite.
                if len(files) > 1 or not imports_cleanly(path, patched):
                    return tests
                cls, qualname = enclosing
                module = path.removesuffix('.py').replace('/', '.')
                module = module.removesuffix('.__init__')
                narrow = choose_attribute(before, after, precise if precise is not None else change['lines'], module, qualname, SOURCE, dependencies)
                if narrow is not None:
                    selected.update(narrow)
                    continue
                contexts = set(dependencies['class_uses'].get(module + ':' + qualname, []))
                for num in range(cls.lineno, cls.end_lineno + 1):
                    contexts.update(line_map.get(str(num), []))
                readers = static_class_readers(cls.name, tuple(sorted({t['file'] for t in tests})))
                contexts.update(t['id'] for t in tests if t['file'] in readers)
                if not contexts:
                    return tests
                selected.update(contexts)
                continue
            scope = min(scopes, key=lambda n: n.end_lineno - n.lineno)
            # A changed executable statement cannot affect a test that never
            # reaches it. Definitions and untraced lines use the whole function.
            statements = [n for n in ast.walk(scope) if isinstance(n, ast.stmt)
                          and not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                          and n.lineno <= line <= n.end_lineno]
            statement = min(statements, key=lambda n: n.end_lineno - n.lineno) if statements else scope
            contexts = set()
            for num in range(statement.lineno, statement.end_lineno + 1):
                contexts.update(line_map.get(str(num), []))
            if not contexts:
                for num in range(scope.lineno, scope.end_lineno + 1):
                    contexts.update(line_map.get(str(num), []))
            if not contexts:
                return tests
            selected.update(contexts)
        # Unmeasured tests must never be silently excluded.
        selected.update(all_ids - set(dependencies.get('collected', [])))
    return [t for t in tests if t['id'] in selected]

def main():
    tests = json.loads((DATA / 'tests.json').read_text())['tests']
    with gzip.open(MAP, 'rt') as f:
        dependencies = json.load(f)
    if 'names' in dependencies:
        names = dependencies['names']
        dependencies['lines'] = {path: {line: [names[i] for i in contexts] for line, contexts in lines.items()}
                                 for path, lines in dependencies['lines'].items()}
    for patch in sorted((DATA / 'commits').glob('*.patch')):
        try:
            chosen = choose(patch.read_text(), tests, dependencies)
        except Exception as e:
            print(f'{patch.stem}: conservative fallback: {type(e).__name__}', file=sys.stderr)
            chosen = tests
        print(json.dumps({'commit': patch.stem, 'workers': schedule(chosen)}, separators=(',', ':')))

if __name__ == '__main__':
    main()
