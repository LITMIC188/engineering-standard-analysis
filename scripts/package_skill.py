"""Build a deterministic local skill ZIP from maintained source, excluding user runs."""
import argparse
import hashlib
from pathlib import Path
import zipfile

def package(out):
    root=Path(__file__).resolve().parents[1];out=Path(out)
    if out.exists():raise FileExistsError('Choose a new release output; existing packages are preserved')
    paths=[root/'SKILL.md',root/'README.md']
    for folder in ('agents','assets','references','scripts','schemas','tests','docs'):
        paths.extend(p for p in (root/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc','.tmp'))
    out.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(out,'x',compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(paths,key=lambda p:p.relative_to(root).as_posix()):
            info=zipfile.ZipInfo('engineering-standard-analysis/'+path.relative_to(root).as_posix(),date_time=(2026,10,11,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o644<<16
            archive.writestr(info,path.read_bytes())
    sha=hashlib.sha256(out.read_bytes()).hexdigest()
    out.with_suffix(out.suffix+'.sha256').write_text(sha+'  '+out.name+'\n',encoding='utf-8')
    return sha

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',required=True);a=p.parse_args();print(package(a.out))
