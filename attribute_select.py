"""Narrow literal class-setting edits using observed and static attribute readers."""
import ast
import copy
from functools import lru_cache

def literal_assignment(tree, lines):
    hits=[]
    for cls in ast.walk(tree):
        if not isinstance(cls,ast.ClassDef):continue
        for stmt in cls.body:
            if isinstance(stmt,(ast.Assign,ast.AnnAssign)):
                targets=stmt.targets if isinstance(stmt,ast.Assign) else [stmt.target]
                if len(targets)!=1 or not isinstance(targets[0],ast.Name):continue
                if not lines or not all(stmt.lineno<=n<=stmt.end_lineno for n in lines):continue
                try:ast.literal_eval(stmt.value)
                except (ValueError,TypeError,SyntaxError):continue
                hits.append((stmt,targets[0].id))
    return hits[0] if len(hits)==1 else None

@lru_cache(maxsize=4)
def indirect_index(root):
    # Scan source once per process, not once for every edited setting.
    found={}
    for p in root.rglob('*.py'):
        if '.git' in p.parts:continue
        try:tree=ast.parse(p.read_text())
        except (SyntaxError,UnicodeError):continue
        for n in ast.walk(tree):
            if isinstance(n,ast.Constant) and isinstance(n.value,str) and n.value.isidentifier() and n.value.isupper():
                found.setdefault(n.value,[]).append((p.relative_to(root).as_posix(),n.lineno))
    return found

def indirect_readers(root,name):
    return indirect_index(root).get(name,[])

def choose_attribute(before,after,lines,module,qualname,source,deps):
    if deps.get('attribute_map_complete') is not True:
        return None
    if not set(deps.get('collected',[])).issubset(deps.get('attribute_collected',[])):
        return None
    a=literal_assignment(before,lines)
    if not a:return None
    old,name=a
    if not name.isupper():return None
    # Both versions must have an existing same-named simple literal setting.
    # No definitions, new overrides, deletion, descriptors or arbitrary calls.
    candidates=[n for n in ast.walk(after) if isinstance(n,type(old)) and
        ((isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id==name) or
         (isinstance(n,ast.AnnAssign) and isinstance(n.target,ast.Name) and n.target.id==name))]
    if len(candidates)!=1:return None
    replacement=copy.copy(candidates[0])
    replacement.value=old.value
    if ast.dump(replacement,include_attributes=False)!=ast.dump(old,include_attributes=False):return None
    try:ast.literal_eval(candidates[0].value)
    except (ValueError,TypeError,SyntaxError):return None
    key=module+':'+qualname+':'+name
    if key in deps.get('attribute_import_reads',[]):return None
    reads=deps.get('attribute_reads',{}).get(key)
    if reads is None:return None
    selected=set(reads)
    indirect=deps.get('attribute_indirect_reads')
    refs=indirect.get(name,[]) if indirect is not None else indirect_readers(source,name)
    for path,line in refs:
        contexts=deps['lines'].get(path,{}).get(str(line),[])
        if not contexts:return None
        selected.update(contexts)
    # Shared class setup context cannot be attributed only to its first test.
    # Keep class setup consumers by explicit mapping when available.
    for file in deps.get('attribute_shared_reads',{}).get(key,[]):
        selected.update(t for t in deps['collected'] if t.split('::')[0]==file)
    return selected
