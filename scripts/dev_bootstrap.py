"""프로젝트 전용 프로필에서 저장소의 CatAni Extension을 활성화한다."""

import os
from pathlib import Path

import addon_utils
import bpy


def bootstrap():
    profile_value = os.environ.get("BLENDER_USER_RESOURCES")
    source_value = os.environ.get("CATANI_DEV_SOURCE")
    if not profile_value or not source_value:
        raise RuntimeError("전용 dev_run 실행기를 사용하세요.")
    profile = Path(profile_value).resolve()
    source = Path(source_value).resolve()
    expected_source = Path(__file__).resolve().parents[1] / "catani"
    if source != expected_source or "CatAniDev" not in profile.parts:
        raise RuntimeError("CatAni 전용 개발 프로필과 소스 경로를 확인하세요.")
    actual_profile = Path(bpy.utils.resource_path("USER")).resolve()
    if actual_profile != profile:
        raise RuntimeError(f"사용자 프로필 격리가 적용되지 않았습니다: {actual_profile}")
    extension_root = profile / "extensions" / "user_default"
    if (extension_root / "catani").resolve() != source:
        raise RuntimeError("개발 Extension 링크가 저장소 소스를 가리키지 않습니다.")
    print(f"CatAni 개발 프로필 확인: {actual_profile}", flush=True)
    repositories = bpy.context.preferences.extensions.repos
    repository = next((repo for repo in repositories if repo.module == "user_default"), None)
    if repository is None:
        repository = repositories.new(
            name="CatAni 개발", module="user_default", custom_directory=str(extension_root)
        )
        repository.use_custom_directory = True
    if Path(repository.directory).resolve() != extension_root.resolve():
        raise RuntimeError("user_default 저장소가 전용 개발 프로필 밖을 가리킵니다.")
    module_name = "bl_ext.user_default.catani"
    first_enable = module_name not in bpy.context.preferences.addons
    module = addon_utils.enable(module_name, default_set=True, persistent=True)
    if module is None or not addon_utils.check(module_name)[1]:
        raise RuntimeError("CatAni Extension 활성화에 실패했습니다.")
    if first_enable:
        bpy.ops.wm.save_userpref()
    print(f"CatAni 개발 소스 활성화: {source}", flush=True)


bootstrap()
