"""Download official public releases. If BLS returns HTTP 403, download manually from BLS tables.
Usage: python scripts/download_sources.py
"""
from pathlib import Path
import requests
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
DOWNLOADS = ROOT / "data" / "downloads"
RAW = ROOT / "data" / "raw"
SOURCES = {
    "bls_2025_metro": "https://www.bls.gov/oes/special-requests/oesm25ma.zip",
    "onet_31_0_csv": "https://www.onetcenter.org/dl_files/database/db_31_0_csv.zip",
}


def fetch(name, url):
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    target = DOWNLOADS / f"{name}.zip"
    if not target.exists():
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (academic research; 95-815 project)"}, timeout=180)
        resp.raise_for_status()
        target.write_bytes(resp.content)
    if not zipfile.is_zipfile(target):
        raise ValueError(f"Not a valid ZIP file: {target}")
    out = RAW / name
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target) as z:
        for member in z.infolist():
            p = Path(member.filename)
            if p.is_absolute() or ".." in p.parts:
                raise ValueError(f"Unsafe ZIP member: {member.filename}")
        # Never overwrite an acquired source, even on an ordinary repeat run.
        for member in z.infolist():
            destination = out / member.filename
            if member.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            if destination.exists():
                checksum = 0
                with destination.open('rb') as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        checksum = zlib.crc32(block, checksum)
                if destination.stat().st_size != member.file_size or checksum != member.CRC:
                    raise ValueError(f'Existing raw file differs from archive: {destination}; preserve both versions.')
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with z.open(member) as source, destination.open('xb') as target_file:
                import shutil
                shutil.copyfileobj(source, target_file)
    files = [str(p.relative_to(ROOT)) for p in out.rglob("*") if p.is_file()]
    print(f"{name}: {target.stat().st_size:,} bytes, {len(files)} extracted files")
    print("\n".join(files[:15]))


if __name__ == "__main__":
    for name, url in SOURCES.items():
        try:
            fetch(name, url)
        except requests.RequestException as exc:
            print(f"Download failed for {name}: {exc}\nDownload from official webpage manually and extract to data/raw/{name}/")
