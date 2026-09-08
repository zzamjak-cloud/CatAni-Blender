"""공식 Blender CLI로 허용된 런타임 파일만 Extension ZIP에 묶는다."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

from validate_release import ROOT, RUNTIME_FILES, validate

MOTION_SAMPLE_FILES = (
    Path("motions/motions.json"),
    Path("motions/demo/friendly_wave.bvh"),
)


def resolve_blender(value=None):
    candidate = value or os.environ.get("BLENDER_BINARY") or shutil.which("blender")
    if not candidate and os.name != "nt":
        candidate = "/Applications/Blender.app/Contents/MacOS/Blender"
    if not candidate or not Path(candidate).is_file():
        raise ValueError("--blender 또는 BLENDER_BINARY로 Blender 실행 파일을 지정하세요.")
    return str(Path(candidate).resolve())


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
