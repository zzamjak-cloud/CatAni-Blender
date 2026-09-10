"""공식 Blender CLI로 허용된 런타임 파일만 Extension ZIP에 묶는다."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import string
import subprocess
import tempfile
import tomllib
import zipfile

from validate_release import ROOT, RUNTIME_FILES, validate

MOTION_SAMPLE_FILES = (
    Path("motions/motions.json"),
    Path("motions/demo/friendly_wave.bvh"),
)


def minimum_blender():
    """매니페스트가 요구하는 최소 Blender 버전."""
    manifest = tomllib.loads((ROOT / "catani/blender_manifest.toml").read_text(encoding="utf-8"))
    parts = str(manifest.get("blender_version_min", "0")).split(".")
    return tuple(int(value) for value in (parts + ["0", "0", "0"])[:3])


def blender_version(path):
    """실행 파일에서 실제 버전을 읽는다. 폴더 이름은 실제 버전과 다를 수 있다."""
    try:
        result = subprocess.run([str(path), "--version"], text=True, encoding="utf-8", errors="replace",
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=180)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode:
        return None
    match = re.search(r"Blender (\d+)\.(\d+)(?:\.(\d+))?", result.stdout)
    if match is None:
        return None
    return tuple(int(value) if value else 0 for value in match.groups())


def blender_candidates():
    """PATH와 흔한 설치 위치에서 Blender 실행 파일 후보를 모은다."""
    found = []
    located = shutil.which("blender.exe" if os.name == "nt" else "blender")
    if located:
        found.append(located)
    roots = []
    if os.name == "nt":
        program_x86 = os.environ.get("ProgramFiles(x86)")
        for base in (os.environ.get("ProgramFiles"), program_x86,
                     os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
            if base:
                roots.append(Path(base) / "Blender Foundation")
        if program_x86:
            roots.append(Path(program_x86) / "Steam/steamapps/common")
        # 압축을 풀어 쓰는 포터블 설치는 드라이브 상단이나 도구 폴더에 놓이는 경우가 많다.
        drives = os.listdrives() if hasattr(os, "listdrives") else [f"{letter}:\\" for letter in string.ascii_uppercase]
        for drive in drives:
            base = Path(drive)
            roots.extend([base, base / "Tools", base / "Apps", base / "Programs", base / "Program Files"])
    else:
        roots.extend([Path("/Applications"), Path.home() / "Applications", Path("/opt"), Path("/usr/local")])
    for root in roots:
        try:
            children = sorted(root.glob("[Bb]lender*"))
        except OSError:
            continue
        for child in children:
            for relative in ("blender.exe", "blender", "Contents/MacOS/Blender", "Blender.app/Contents/MacOS/Blender"):
                candidate = child / relative
                if candidate.is_file():
                    found.append(str(candidate))
    return list(dict.fromkeys(found))


def resolve_blender(value=None):
    """명시 경로가 없으면 최소 버전을 만족하는 가장 높은 버전을 스스로 찾는다.

    4.3과 5.2가 함께 깔린 환경에서 PATH나 탐색 순서로 낮은 버전이 먼저 잡히면
    애드온이 로드되지 않으므로, 후보를 모두 모은 뒤 실제 버전으로 비교한다.
    """
    candidate = value or os.environ.get("BLENDER_BINARY")
    if candidate:
        if not Path(candidate).is_file():
            raise ValueError(f"지정한 Blender 실행 파일이 없습니다: {candidate}")
        return str(Path(candidate).resolve())
    minimum = minimum_blender()
    best = None
    too_old = []
    for path in blender_candidates():
        version = blender_version(path)
        if version is None:
            continue
        if version < minimum:
            too_old.append(f"{path} ({'.'.join(str(part) for part in version)})")
            continue
        if best is None or version > best[0]:
            best = (version, path)
    if best is not None:
        return str(Path(best[1]).resolve())
    wanted = ".".join(str(part) for part in minimum)
    if too_old:
        raise ValueError(f"Blender {wanted} 이상이 필요합니다. 찾은 설치: {', '.join(too_old)}. "
                         "--blender 또는 BLENDER_BINARY로 지정하세요.")
    raise ValueError("Blender 실행 파일을 찾지 못했습니다. --blender 또는 BLENDER_BINARY로 지정하세요.")


def run_checked(command, env, label, cwd=ROOT):
    result = subprocess.run(command, env=env, cwd=cwd, text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode:
        print(result.stdout, end="")
        raise RuntimeError(f"{label} 실패: 종료 코드 {result.returncode}")
    print(json.dumps({"check": label, "status": "pass"}, ensure_ascii=False), flush=True)


def build(blender, output_dir, tag=None):
    manifest = validate(tag=tag)
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"catani-v{manifest['version']}.zip"
    with tempfile.TemporaryDirectory(prefix="catani-package-") as temporary:
        work = Path(temporary)
        source = work / "source"
        source.mkdir()
        for name in RUNTIME_FILES:
            shutil.copy2(ROOT / "catani" / name, source / name)
        for name in MOTION_SAMPLE_FILES:
            sample_destination = source / name
            sample_destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, sample_destination)
        # 개발 중 내려받은 모션 기록이 ZIP 인덱스에 섞이지 않게 동봉 파일만 남긴다.
        index_path = source / "motions/motions.json"
        document = json.loads(index_path.read_text(encoding="utf-8"))
        shipped = {name.relative_to("motions").as_posix() for name in MOTION_SAMPLE_FILES if name.suffix != ".json"}
        document["motions"] = [item for item in document.get("motions", []) if item.get("file") in shipped]
        if len(document["motions"]) != len(shipped):
            raise ValueError(f"동봉할 예제 모션 정보가 motions.json에 없습니다: {shipped}")
        index_path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        shutil.copy2(ROOT / "LICENSE", source / "LICENSE")
        # 체크아웃 시각이나 운영체제 권한 차이가 ZIP 메타데이터에 섞이지 않게 한다.
        for path in source.rglob("*"):
            if path.is_dir():
                continue
            path.chmod(0o644)
            os.utime(path, (946684800, 946684800))
        # ZIP은 로컬 시간대로 시각을 기록한다. TZ를 고정하지 않으면 같은 소스라도
        # 빌드 기계의 시간대에 따라 아카이브 바이트가 달라진다.
        env = dict(os.environ, BLENDER_USER_RESOURCES=str(work / "profile"), TZ="UTC")
        prefix = [blender, "--background", "--factory-startup", "--disable-autoexec", "--python-exit-code", "1", "--command", "extension"]
        run_checked(prefix + ["validate", str(ROOT / "catani")], env, "extension_source")
        run_checked(prefix + ["validate", str(source)], env, "extension_staging")
        archive = work / destination.name
        run_checked(prefix + ["build", "--source-dir", str(source), "--output-filepath", str(archive)], env, "extension_build")
        with zipfile.ZipFile(archive) as package:
            names = package.namelist()
            expected = set(RUNTIME_FILES) | {"LICENSE"} | {name.as_posix() for name in MOTION_SAMPLE_FILES}
            if set(names) != expected or len(names) != len(expected):
                raise ValueError(f"ZIP 파일 목록이 허용 목록과 다릅니다: {names}")
            if package.testzip() is not None:
                raise ValueError("ZIP 무결성 검사에 실패했습니다.")
        run_checked(prefix + ["validate", str(archive)], env, "extension_zip")
        repository_path = work / "acceptance"
        with zipfile.ZipFile(archive) as package:
            package.extractall(repository_path / "catani")
        acceptance_env = dict(os.environ, BLENDER_USER_RESOURCES=str(work / "acceptance-profile"),
                              CATANI_PACKAGE_ROOT=str(repository_path))
        run_checked([blender, "--background", "--factory-startup", "--disable-autoexec", "--python-exit-code", "1",
                     "--python", str(ROOT / "tests/blender_package.py")], acceptance_env, "extension_zip_runtime")
        shutil.copy2(archive, destination)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    checksum = destination.with_suffix(destination.suffix + ".sha256")
    checksum.write_text(f"{digest}  {destination.name}\n", encoding="ascii")
    print(json.dumps({"artifact": str(destination), "sha256": digest, "checksum": str(checksum)}, ensure_ascii=False))
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", help="Blender 실행 파일 경로")
    parser.add_argument("--output-dir", default=str(ROOT / "dist"))
    parser.add_argument("--tag", help="매니페스트와 비교할 v 접두사 태그")
    args = parser.parse_args()
    build(resolve_blender(args.blender), args.output_dir, args.tag)


if __name__ == "__main__":
    main()
