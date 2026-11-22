"""Focused regressions for AST and attribute dependency narrowing."""
import ast
import difflib
import tempfile
import unittest
import types
from pathlib import Path
import selector
import attrtrace
from attribute_select import choose_attribute
from refine import changed_lines

class PrecisionTests(unittest.TestCase):
    def select(self,before,after,lines):
        tests=[{'id':name,'file':'tests/'+name+'.py','number':i,'seconds':.1}
               for i,name in enumerate(['one','two'])]
        patch='diff --git a/x.py b/x.py\n'+''.join(difflib.unified_diff(
            before.splitlines(True),after.splitlines(True),fromfile='a/x.py',tofile='b/x.py'))
        with tempfile.TemporaryDirectory() as tmp:
            previous=selector.SOURCE;selector.SOURCE=Path(tmp)
            (selector.SOURCE/'x.py').write_text(before);selector.source_tree.cache_clear()
            try:return {t['id'] for t in selector.choose(patch,tests,{'collected':['one','two'],'lines':{'x.py':lines}})}
            finally:selector.SOURCE=previous;selector.source_tree.cache_clear()

    def test_lambda_body_still_narrows(self):
        self.assertEqual(self.select('f = lambda x: x + 1\n','f = lambda x: x + 2\n',{'1':['one']}),{'one'})

    def test_lambda_raising_default_invalidates_importers(self):
        self.assertEqual(self.select('f = lambda x=1: x\n','f = lambda x=1/0: x\n',{'1':['one']}),{'one','two'})

    def test_lambda_added_required_argument_is_conservative(self):
        self.assertEqual(self.select('f = lambda x: x\n','f = lambda x,y: x\n',{'1':['one']}),{'one','two'})

    def test_short_circuit_operator_keeps_guard_reachers(self):
        before='def f(a,b):\n    if (a\n        and b):\n        return 1\n    return 0\n'
        after=before.replace('and b','or b')
        precise=changed_lines(ast.parse(before),ast.parse(after))
        self.assertTrue({2,3}.issubset(precise))
        self.assertEqual(self.select(before,after,{'2':['one','two'],'3':['one'],'4':['one'],'5':['two']}),{'one','two'})

    def test_attribute_maps_must_be_complete(self):
        before=ast.parse('class C:\n    FLAG = 1\n');after=ast.parse('class C:\n    FLAG = 2\n')
        with tempfile.TemporaryDirectory() as tmp:
            deps={'collected':['one','two'],'lines':{},'attribute_reads':{'sqlglot.x:C:FLAG':['one']}}
            args=(before,after,{2},'sqlglot.x','C',Path(tmp),deps)
            self.assertIsNone(choose_attribute(*args))
            deps.update(attribute_map_complete=True,attribute_collected=['one'])
            self.assertIsNone(choose_attribute(*args))
            deps['attribute_collected']=['one','two']
            self.assertEqual(choose_attribute(*args),{'one'})
            deps['attribute_import_reads']=['sqlglot.x:C:FLAG']
            self.assertIsNone(choose_attribute(*args))

    def test_shared_and_import_reads_after_ordinary_read(self):
        old=attrtrace.current
        attrtrace.reads.clear();attrtrace.shared_reads.clear();attrtrace.import_reads.clear();attrtrace.cache.clear()
        class C: FLAG=1
        C.__module__='sqlglot.synthetic';key='sqlglot.synthetic:'+C.__qualname__+':FLAG'
        attrtrace.current=lambda:'tests/a.py::TestA::test_one'
        try:
            attrtrace.observe(C,'FLAG')
            with attrtrace.shared_setup_scope():
                attrtrace.observe(C,'FLAG')
            self.assertEqual(attrtrace.shared_reads[key],{'tests/a.py'})
            with attrtrace.import_scope():
                attrtrace.observe(C,'FLAG')
            self.assertIn(key,attrtrace.import_reads)
        finally:attrtrace.current=old

    def test_phase_flags_restore_after_nested_exceptions(self):
        self.assertEqual((attrtrace.import_depth,attrtrace.shared_setup_depth),(0,0))
        with attrtrace.import_scope(),attrtrace.shared_setup_scope():
            self.assertEqual((attrtrace.import_depth,attrtrace.shared_setup_depth),(1,1))
            with self.assertRaises(ValueError):
                with attrtrace.import_scope(),attrtrace.shared_setup_scope():
                    self.assertEqual((attrtrace.import_depth,attrtrace.shared_setup_depth),(2,2))
                    raise ValueError('nested failure')
            self.assertEqual((attrtrace.import_depth,attrtrace.shared_setup_depth),(1,1))
        self.assertEqual((attrtrace.import_depth,attrtrace.shared_setup_depth),(0,0))

    def test_loader_restores_import_flag_after_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'example.py'
            path.write_text("raise RuntimeError('import failed')\n")
            loader=attrtrace.Loader('sqlglot.synthetic',str(path))
            with self.assertRaises(RuntimeError):
                loader.exec_module(types.ModuleType('sqlglot.synthetic'))
            self.assertEqual(attrtrace.import_depth,0)

if __name__=='__main__':unittest.main()
