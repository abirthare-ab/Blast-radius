"""Record source-derived class-attribute readers on the pristine baseline."""
import ast, builtins, importlib.abc, importlib.machinery
from pathlib import Path
import sys
from contextlib import contextmanager

reads={}
import_reads=set()
shared_reads={}
original_getattr=getattr
current=lambda: ''
cache={}
import_depth=0
shared_setup_depth=0

@contextmanager
def import_scope():
    global import_depth
    import_depth+=1
    try:yield
    finally:import_depth-=1

@contextmanager
def shared_setup_scope():
    global shared_setup_depth
    shared_setup_depth+=1
    try:yield
    finally:shared_setup_depth-=1

def observe(obj, name, *default):
    cls=obj if isinstance(obj,type) else type(obj)
    key=(cls,name)
    owner=cache.get(key)
    if owner is None:
        owner=''
        for base in cls.__mro__:
            if name in vars(base):
                if base.__module__.startswith('sqlglot'):
                    owner=base.__module__+':'+base.__qualname__+':'+name
                break
        cache[key]=owner
    if owner:
        context=current()
        if context:
            contexts=reads.setdefault(owner,set())
            # Phase flags are checked on every access, including repeat reads
            # in one test. No per-access stack walk on hot expression paths.
            if import_depth:import_reads.add(owner)
            if shared_setup_depth:
                shared_reads.setdefault(owner,set()).add(context.split('::')[0])
            contexts.add(context)
        else: import_reads.add(owner)
    return original_getattr(obj,name,*default)

class Transform(ast.NodeTransformer):
    def visit_Call(self,node):
        self.generic_visit(node)
        if isinstance(node.func,ast.Name) and node.func.id=='getattr':
            node.func=ast.copy_location(ast.Name(id='_blast_observe_attribute',ctx=ast.Load()),node.func)
        return node
    def visit_Attribute(self,node):
        self.generic_visit(node)
        if isinstance(node.ctx,ast.Load) and (node.attr.isupper() or node.attr=='arg_types'):
            return ast.copy_location(ast.Call(func=ast.Name(id='_blast_observe_attribute',ctx=ast.Load()),args=[node.value,ast.Constant(node.attr)],keywords=[]),node)
        return node

class Loader(importlib.machinery.SourceFileLoader):
    def exec_module(self,module):
        with import_scope():
            return super().exec_module(module)
    def get_code(self,fullname):
        tree=ast.parse(self.get_data(self.path),filename=self.path)
        return compile(ast.fix_missing_locations(Transform().visit(tree)),self.path,'exec')
class Finder(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname!='sqlglot' and not fullname.startswith(('sqlglot.','tests.')):return None
        spec=importlib.machinery.PathFinder.find_spec(fullname,path)
        if spec and spec.origin and spec.origin.endswith('.py'):
            spec.loader=Loader(fullname,spec.origin)
            return spec

def install(get_current):
    global current
    current=get_current
    builtins._blast_observe_attribute=observe
    sys.meta_path.insert(0,Finder())
