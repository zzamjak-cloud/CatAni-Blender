"""CI 전용 공식 Blender 바이너리를 검증하고 설치한다."""

import hashlib
import os
from pathlib import Path
import platform
import subprocess
import tarfile
import urllib.request
import zipfile


def main():
    version = "5.2.0"
    system = platform.system()
    suffix = {"Linux": "linux-x64.tar.xz", "Windows": "windows-x64.zip"}[system]
    name = f"blender-{version}-{suffix}"
    base = "https://download.blender.org/release/Blender5.2/"
    target = Path(os.environ["RUNNER_TEMP"]) / "catani-blender"
    target.mkdir(parents=True, exist_ok=True)
    archive = target / name
    checksums = urllib.request.urlopen(base + f"blender-{version}.sha256", timeout=60).read().decode()
    matches = [line.split()[0] for line in checksums.splitlines() if line.split()[-1].lstrip("*") == name]
    if len(matches) != 1:
        raise RuntimeError("공식 체크섬에서 Blender 파일을 찾지 못했습니다.")
    urllib.request.urlretrieve(base + name, archive)
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
