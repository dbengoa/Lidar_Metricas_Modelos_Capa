"""Build the single deterministic QGIS installer; no third-party build packages."""
from pathlib import Path
import hashlib
import configparser
import zipfile
root=Path(__file__).resolve().parents[1]
package=root/'lidar_forestal_integrado'
metadata=configparser.ConfigParser();metadata.read(package/'metadata.txt',encoding='utf-8')
output=root/'dist';output.mkdir(exist_ok=True)
archive=output/('lidar_forestal_integrado-'+metadata['general']['version']+'-experimental.zip')
with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
    for path in sorted(package.rglob('*')):
        if not path.is_file() or '__pycache__' in path.parts or path.suffix=='.pyc':continue
        item=zipfile.ZipInfo(path.relative_to(root).as_posix(),date_time=(2026,11,1,0,0,0))
        item.compress_type=zipfile.ZIP_DEFLATED;item.external_attr=0o100644<<16
        z.writestr(item,path.read_bytes())
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    assert 'lidar_forestal_integrado/metadata.txt' in z.namelist()
    assert 'lidar_forestal_integrado/lidar_core/engine.py' in z.namelist()
    assert not any('/_inventory/' in name for name in z.namelist())
checksum=hashlib.sha256(archive.read_bytes()).hexdigest()
archive.with_suffix('.zip.sha256').write_text(checksum+'  '+archive.name+'\n')
print(archive);print(checksum)
