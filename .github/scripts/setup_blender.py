"""CI 전용 공식 Blender 바이너리를 검증하고 설치한다."""

import hashlib
import os
from pathlib import Path
import platform
import subprocess
import shutil
import tarfile
from urllib.request import Request, urlopen
import zipfile

# download.blender.org는 기본 Python-urllib User-Agent를 403으로 거부한다.
HEADERS = {"User-Agent": "CatAni-CI/1.0 (+https://github.com/zzamjak-cloud/CatAni-Blender)"}


def fetch(url, destination=None):
    """destination이 없으면 본문을 돌려주고, 있으면 그 파일로 스트리밍한다."""
    with urlopen(Request(url, headers=HEADERS), timeout=180) as response:
        if response.status != 200:
            raise RuntimeError(f"{url} 응답이 200이 아닙니다: {response.status}")
        if destination is None:
            return response.read()
        with open(destination, "wb") as stream:
            shutil.copyfileobj(response, stream)
    return None


def main():
    version = "5.2.0"
    system = platform.system()
    suffix = {"Linux": "linux-x64.tar.xz", "Windows": "windows-x64.zip"}[system]
    name = f"blender-{version}-{suffix}"
    base = "https://download.blender.org/release/Blender5.2/"
    target = Path(os.environ["RUNNER_TEMP"]) / "catani-blender"
    target.mkdir(parents=True, exist_ok=True)
    archive = target / name
    checksums = fetch(base + f"blender-{version}.sha256").decode("utf-8")
    matches = [line.split()[0] for line in checksums.splitlines() if line.split()[-1].lstrip("*") == name]
    if len(matches) != 1:
        raise RuntimeError("공식 체크섬에서 Blender 파일을 찾지 못했습니다.")
    fetch(base + name, archive)
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != matches[0]:
        raise RuntimeError("Blender 다운로드 SHA256이 일치하지 않습니다.")
    if system == "Windows":
        with zipfile.ZipFile(archive) as package:
            package.extractall(target)
        binary = target / f"blender-{version}-windows-x64" / "blender.exe"
    else:
        with tarfile.open(archive) as package:
            package.extractall(target, filter="data")
        binary = target / f"blender-{version}-linux-x64" / "blender"
    subprocess.run([str(binary), "--version"], check=True)
    with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as stream:
        stream.write(f"BLENDER_BINARY={binary}\n")


if __name__ == "__main__":
    main()
