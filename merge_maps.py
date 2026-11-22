"""Merge separately validated pristine line and attribute coverage maps."""
import gzip,json,sys

def main():
    with gzip.open(sys.argv[1],'rt') as f:base=json.load(f)
    with gzip.open(sys.argv[2],'rt') as f:attrs=json.load(f)
    if base.get('pytest_status')!=0 or attrs.get('pytest_status')!=0 or not attrs.get('attribute_map_complete'):
        raise SystemExit('Refusing incomplete dependency maps')
    if not set(base['collected']).issubset(attrs['attribute_collected']):
        raise SystemExit('Attribute run omitted baseline tests')
    base.update({k:v for k,v in attrs.items() if k.startswith('attribute_')})
    if len(sys.argv)>4:
        from pathlib import Path
        from attribute_select import indirect_index
        base['attribute_indirect_reads']=indirect_index(Path(sys.argv[4]).resolve())
    with gzip.open(sys.argv[3],'wt') as f:json.dump(base,f,separators=(',',':'))
if __name__=='__main__':main()
