"""Attribute dependency map from the pristine suite; no submitted patches."""
import os,sys,json,gzip,concurrent.futures,pickle
from pathlib import Path
import pytest
import attrtrace

def main():
    root=Path(sys.argv[1]).resolve()
    out=Path(sys.argv[2]).resolve()
    os.chdir(root)
    sys.path.insert(0,str(root))
    os.environ['SKIP_INTEGRATION']='0'
    os.environ['PATH']=str(Path(sys.executable).parent)+os.pathsep+os.environ['PATH']
    class Pool(concurrent.futures.Executor):
        def __init__(self,*args,initializer=None,initargs=(),**kwargs):
            if initializer:initializer(*initargs)
        def submit(self,fn,*args,**kwargs):
            f=concurrent.futures.Future()
            try:
                args,kwargs=pickle.loads(pickle.dumps((args,kwargs)))
                f.set_result(pickle.loads(pickle.dumps(fn(*args,**kwargs))))
            except BaseException as e:f.set_exception(e)
            return f
        def shutdown(self,wait=True,**kwargs):pass
    concurrent.futures.ProcessPoolExecutor=Pool
    current=''
    collected=[]
    class Plugin:
        @pytest.hookimpl(hookwrapper=True)
        def pytest_runtest_setup(self,item):
            # Pytest's unittest adapter invokes setUpClass/setUpModule here.
            # Treat all setup reads as shared with the source file, safely
            # over-including ordinary per-test fixtures and setup methods.
            with attrtrace.shared_setup_scope():
                yield
        def pytest_collection_finish(self,session):
            collected.extend(item.nodeid for item in session.items)
        @pytest.hookimpl(hookwrapper=True)
        def pytest_runtest_protocol(self,item,nextitem):
            nonlocal current
            current=item.nodeid
            yield
            current=''
    attrtrace.install(lambda:current)
    status=pytest.main(['tests','-q','--tb=short','--timeout=600'],plugins=[Plugin()])
    result={'attribute_map_complete':int(status)==0,
            'attribute_collected':sorted(set(collected)),
            'attribute_reads':{k:sorted(v) for k,v in attrtrace.reads.items()},
            'attribute_import_reads':sorted(attrtrace.import_reads),
            'attribute_shared_reads':{k:sorted(v) for k,v in attrtrace.shared_reads.items()},
            'pytest_status':int(status)}
    with gzip.open(out,'wt') as f:json.dump(result,f,separators=(',',':'))
    print('STATUS',status,flush=True)
if __name__=='__main__':main()
