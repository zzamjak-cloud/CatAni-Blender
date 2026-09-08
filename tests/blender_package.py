"""ZIP만 풀어 설치한 독립 프로필에서 등록과 모션 가져오기를 확인한다."""

import os
from pathlib import Path

import addon_utils
import bpy


repository_path = Path(os.environ["CATANI_PACKAGE_ROOT"]).resolve()
profile_path = Path(os.environ["BLENDER_USER_RESOURCES"]).resolve()
assert Path(bpy.utils.resource_path("USER")).resolve() == profile_path
repo = next((item for item in bpy.context.preferences.extensions.repos if item.module == "user_default"), None)
if repo is None:
    repo = bpy.context.preferences.extensions.repos.new(name="CatAni ZIP 검증", module="user_default", custom_directory=str(repository_path))
repo.use_custom_directory = True
repo.custom_directory = str(repository_path)
addon = addon_utils.enable("bl_ext.user_default.catani", default_set=True, persistent=True)
assert addon is not None
assert Path(addon.__file__).resolve().parent == repository_path / "catani"
for name in ("agent_bridge.py", "agent_plan.py", "natural.py"):
    assert not (repository_path / "catani" / name).exists(), f"제외할 런타임이 ZIP에 포함되었습니다: {name}"
for suffix in ("agent_generate", "agent_cancel", "plan_default", "plan_import", "plan_export"):
    assert bpy.types.Operator.bl_rna_get_subclass_py(f"CATANI_OT_{suffix}") is None
settings = bpy.context.scene.catani_settings
settings.motion_library_path = str(repository_path / "catani" / "motions")
settings.motion_query = ""
assert bpy.ops.catani.motion_refresh() == {"FINISHED"}
assert addon.assets_from_json(settings.motion_index_json), "ZIP의 합성 예제 모션을 찾지 못했습니다"
before = set(bpy.data.objects)
assert bpy.ops.catani.motion_import() == {"FINISHED"}
created = set(bpy.data.objects) - before
assert any(obj.type == "ARMATURE" and obj.animation_data and obj.animation_data.action for obj in created)
addon.unregister()
print("CATANI_PASS 배포 ZIP 독립 등록·Agent 제외·합성 예제 가져오기·등록 해제")
