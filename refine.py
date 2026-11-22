import ast

def same(a,b):
    return ast.dump(a, include_attributes=False)==ast.dump(b, include_attributes=False)

def changed_lines(before, after):
    """Ignore unchanged neighbours of replacement hunks. Structural insertions fall back."""
    found=set()
    def walk(a,b):
        if same(a,b): return True
        if type(a) is not type(b):
            if hasattr(a,'lineno'):
                found.update(range(a.lineno,a.end_lineno+1));return True
            return False
        # A changed expression is evaluated only when its enclosing expression
        # is reached. Keep its whole span for short-circuit and multiline cases.
        if isinstance(a,ast.expr):
            found.update(range(a.lineno,a.end_lineno+1));return True
        for key, x in ast.iter_fields(a):
            y=getattr(b,key)
            if isinstance(x,ast.AST):
                if not walk(x,y): return False
            elif isinstance(x,list):
                if len(x)!=len(y): return False
                for u,v in zip(x,y):
                    if isinstance(u,ast.AST):
                        if not isinstance(v,ast.AST) or not walk(u,v):return False
                    elif u!=v:return False
            elif x!=y:
                if not hasattr(a,'lineno'):return False
                found.update(range(a.lineno,a.end_lineno+1))
        return True
    return found if walk(before,after) else None
