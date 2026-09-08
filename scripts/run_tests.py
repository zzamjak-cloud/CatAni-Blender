"""일상 프로필과 로컬 산출물을 건드리지 않고 회귀 검사를 실행한다."""

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

from package import resolve_blender, run_checked
from validate_release import ROOT, RUNTIME_FILES, validate


BOOTSTRAP = '''
import os
from pathlib import Path
import addon_utils
import bpy
profile = Path(os.environ["BLENDER_USER_RESOURCES"]).resolve()
if Path(bpy.utils.resource_path("USER")).resolve() != profile:
    raise RuntimeError("테스트 프로필 격리가 적용되지 않았습니다.")
directory = os.environ["CATANI_TEST_ROOT"]
repos = bpy.context.preferences.extensions.repos
repo = next((r for r in repos if r.module == "user_default"), None)
if repo is None:
    repo = repos.new(name="CatAni 회귀 검사", module="user_default", custom_directory=directory)
repo.use_custom_directory = True
repo.custom_directory = directory
if Path(repo.directory).resolve() != Path(directory).resolve():
    raise RuntimeError("테스트 Extension 저장소가 일치하지 않습니다.")
if addon_utils.enable("bl_ext.user_default.catani", default_set=True, persistent=True) is None:
    raise RuntimeError("CatAni 테스트 활성화에 실패했습니다.")
print("CATANI_TEST_PROFILE", profile)
'''

BLENDER_TESTS = (
    ("blender_smoke.py", None),
    ("blender_reload.py", "CatAni_Wave_Demo.blend"),
    ("blender_curves.py", None),
    ("blender_ui_contract.py", None),
    ("blender_motion_library.py", None),
    ("blender_operators.py", None),
)

HOST_TESTS = ("test_motion_library.py", "test_motion_download.py")


def run_suite(blender):
    validate()
    with tempfile.TemporaryDirectory(prefix="catani-tests-") as temporary:
        root = Path(temporary)
        (root / "catani").mkdir()
        for name in RUNTIME_FILES:
            shutil.copy2(ROOT / "catani" / name, root / "catani" / name)
        shutil.copytree(ROOT / "tests", root / "tests", ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*_live.py"))
        (root / "Blender").mkdir()
        shutil.copy2(ROOT / "Blender/Player_Animation_01.blend", root / "Blender/Player_Animation_01.blend")
        (root / "artifacts").mkdir()
        bootstrap = root / "bootstrap.py"
        bootstrap.write_text(BOOTSTRAP, encoding="utf-8")
        env = dict(os.environ, BLENDER_USER_RESOURCES=str(root / "CatAniDev" / "profile"), CATANI_TEST_ROOT=str(root))
        env.pop("CATANI_DEMO_NAME", None)
        for filename in HOST_TESTS:
            run_checked([sys.executable, str(root / "tests" / filename)], env, filename.removesuffix(".py"), root)
        for filename, demo_name in BLENDER_TESTS:
            test_env = dict(env)
            if demo_name:
                test_env["CATANI_DEMO_NAME"] = demo_name
            label = filename.removesuffix(".py") + (f":{demo_name}" if demo_name else "")
            run_checked([blender, "--background", "--factory-startup", "--disable-autoexec", "--python-exit-code", "1",
                         "--python", str(bootstrap), "--python", str(root / "tests" / filename)], test_env, label, root)
    print(json.dumps({"suite": "catani_local", "status": "pass", "checks": len(BLENDER_TESTS) + len(HOST_TESTS), "network_download": False}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", help="Blender 실행 파일 경로")
    args = parser.parse_args()
    run_suite(resolve_blender(args.blender))


if __name__ == "__main__":
    main()
