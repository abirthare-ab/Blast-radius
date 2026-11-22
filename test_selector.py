"""Safety checks for patch parsing, invalidation, and worker overhead."""
import difflib
import tempfile
import unittest
from pathlib import Path

import selector

class SelectorTests(unittest.TestCase):
    def test_hunks_at_file_start_and_end(self):
        before = 'a = 1\nb = 2\n'
        after = 'intro = 0\na = 1\nb = 2\ntail = 3\n'
        patch = 'diff --git a/x.py b/x.py\n' + ''.join(difflib.unified_diff(
            before.splitlines(True), after.splitlines(True), fromfile='a/x.py', tofile='b/x.py', n=0))
        self.assertEqual(selector.apply(before, selector.changes(patch)[0]['hunks']), after)

    def test_bad_context_is_not_applied(self):
        with self.assertRaises(ValueError):
            selector.apply('a = 1\n', [(1, 1, ['-different\n', '+a = 2\n'])])

    def test_import_time_default_change_invalidates_all(self):
        before = 'def f(x):\n    return x + 1\n'
        after = 'def f(x=1/0):\n    return x + 1\n'
        patch = 'diff --git a/x.py b/x.py\n' + ''.join(difflib.unified_diff(
            before.splitlines(True), after.splitlines(True), fromfile='a/x.py', tofile='b/x.py'))
        tests = [{'id': 'one', 'file': 'tests/a.py', 'number': 0, 'seconds': .1},
                 {'id': 'two', 'file': 'tests/b.py', 'number': 1, 'seconds': .1}]
        with tempfile.TemporaryDirectory() as temp:
            old_source = selector.SOURCE
            selector.SOURCE = Path(temp)
            (selector.SOURCE / 'x.py').write_text(before)
            selector.source_tree.cache_clear()
            try:
                self.assertEqual(selector.choose(patch, tests, {}), tests)
            finally:
                selector.SOURCE = old_source
                selector.source_tree.cache_clear()

    def test_overhead_prefers_single_worker_for_tiny_tests(self):
        tests = [{'number': i, 'seconds': .01} for i in range(20)]
        workers = selector.schedule(tests)
        self.assertEqual(len(workers), 1)
        self.assertEqual(set(workers[0]), set(range(20)))
        self.assertEqual(selector.schedule([]), [])

    def test_unmeasured_source_reader_survives_comment_edit(self):
        before = 'x = 1\n'
        after = '# changed text\nx = 1\n'
        patch = 'diff --git a/x.py b/x.py\n' + ''.join(difflib.unified_diff(
            before.splitlines(True), after.splitlines(True), fromfile='a/x.py', tofile='b/x.py'))
        tests = [{'id': 'known', 'file': 'tests/a.py', 'number': 0, 'seconds': .1},
                 {'id': 'new', 'file': 'tests/b.py', 'number': 1, 'seconds': .1}]
        with tempfile.TemporaryDirectory() as temp:
            old_source = selector.SOURCE
            selector.SOURCE = Path(temp)
            (selector.SOURCE / 'x.py').write_text(before)
            selector.source_tree.cache_clear()
            try:
                chosen = selector.choose(patch, tests, {'collected': ['known']})
                self.assertEqual([test['id'] for test in chosen], ['new'])
            finally:
                selector.SOURCE = old_source
                selector.source_tree.cache_clear()

if __name__ == '__main__':
    unittest.main()
