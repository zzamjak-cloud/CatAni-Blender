"""배포 버전, 테스트 입력과 양쪽 개발 실행기의 기본 계약을 확인한다."""

import argparse
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import tomllib


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_FILES = (
    "__init__.py", "core.py", "engine.py", "motion_library.py", "motion_import.py",
    "source_catalog.py", "motion_downloader.py",
    "blender_manifest.toml",
)


def validate(root=ROOT, tag=None):
    """Blender 없이 검사할 수 있는 배포 조건을 확인하고 매니페스트를 반환한다."""
    manifest = tomllib.loads((root / "catani/blender_manifest.toml").read_text(encoding="utf-8"))
    version = manifest["version"]
    if manifest["id"] != "catani" or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("CatAni ID 또는 버전 형식이 잘못되었습니다.")
    if tag is not None and tag != f"v{version}":
        raise ValueError(f"태그 {tag}와 매니페스트 v{version}가 일치하지 않습니다.")
    core = runpy.run_path(str(root / "catani/core.py"))
    if json.loads(core["MotionSpec"]().to_json())["engine_version"] != version:
        raise ValueError("MotionSpec 엔진 버전과 매니페스트가 다릅니다.")
    for name in RUNTIME_FILES:
        if not (root / "catani" / name).is_file():
            raise ValueError(f"필수 런타임 파일이 없습니다: {name}")
    for name in ("LICENSE", "README.md", "Blender/Player_Animation_01.blend",
                 "scripts/dev_bootstrap.py",
                 "motions/motions.json", "motions/demo/friendly_wave.bvh"):
        if not (root / name).is_file():
            raise ValueError(f"배포 검사 입력이 없습니다: {name}")
    powershell = (root / "scripts/dev_run.ps1").read_bytes()
    if not powershell.startswith(b"\xef\xbb\xbf"):
        raise ValueError("Windows PowerShell 실행기에는 UTF-8 BOM이 필요합니다.")
    ps_text = powershell.decode("utf-8-sig")
    bat_text = (root / "scripts/dev_run.bat").read_bytes().decode("ascii")
    shell_text = (root / "scripts/dev_run.sh").read_text(encoding="utf-8")
    for token in ("@args", "ReparsePoint", "BLENDER_USER_RESOURCES", "--python-exit-code 1", "finally"):
        if token not in ps_text:
            raise ValueError(f"Windows 실행기 계약 누락: {token}")
    if "%*" not in bat_text or "%errorlevel%" not in bat_text.lower():
        raise ValueError("BAT 인자 또는 종료 코드 전달이 없습니다.")
    for token in ('"$@"', "BLENDER_USER_RESOURCES", "--python-exit-code 1"):
        if token not in shell_text:
            raise ValueError(f"셸 실행기 계약 누락: {token}")
    readme = (root / "README.md").read_text(encoding="utf-8")
    for token in ("dev_run.sh", "dev_run.ps1", "dev_run.bat"):
        if token not in readme:
            raise ValueError(f"README 실행법 누락: {token}")
    if shutil.which("bash"):
        subprocess.run(["bash", "-n", str(root / "scripts/dev_run.sh")], check=True)
    print(json.dumps({"check": "release_static", "status": "pass", "version": version}, ensure_ascii=False))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    default_tag = os.environ.get("GITHUB_REF_NAME") if os.environ.get("GITHUB_REF_TYPE") == "tag" else None
    parser.add_argument("--tag", default=default_tag, help="릴리스 태그(예: v0.3.0); GitHub 태그 실행 시 자동 감지")
    args = parser.parse_args()
    validate(tag=args.tag)


if __name__ == "__main__":
    main()
