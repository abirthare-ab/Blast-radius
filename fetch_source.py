"""Fetch only the competition's permitted, immutable upstream revision."""
import io
import tarfile
import urllib.request
from pathlib import Path

PIN = 'eb11aec4be8cb2122afe713a4816662c3f0fb2fa'
root = Path('/opt/sqlglot')
root.mkdir(parents=True, exist_ok=True)
with urllib.request.urlopen(f'https://codeload.github.com/tobymao/sqlglot/tar.gz/{PIN}', timeout=120) as response:
    data = response.read()
with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
    for member in archive.getmembers():
        parts = Path(member.name).parts[1:]
        if not parts or member.issym() or member.islnk():
            continue
        member.name = str(Path(*parts))
        archive.extract(member, root, filter='data')
