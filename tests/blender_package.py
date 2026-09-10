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
# 폴더를 직접 지정하지 않는다. 설치본이 동봉 예제를 스스로 찾아야 한다.
bundled = addon.bundled_library_path()
assert bundled == repository_path / "catani" / "motions", f"동봉 모션 경로가 틀렸습니다: {bundled}"
assert (bundled / "demo" / "friendly_wave.bvh").is_file(), "동봉 예제 BVH가 없습니다"
settings.motion_query = "데모"
assert bpy.ops.catani.motion_refresh() == {"FINISHED"}
local = [item for item in settings.motions if item.available]
assert local, "설치본이 동봉 예제 모션을 찾지 못했습니다"
assert len(local) == 1 and local[0].path == str(bundled / "demo" / "friendly_wave.bvh"), [item.path for item in local]
settings.motion_query = ""
# 기본 목록은 비상업 출처를 뺀다. 설치본이 카탈로그 전체를 담았는지 보려면 토글을 켠다.
settings.include_noncommercial = True
assert bpy.ops.catani.motion_refresh() == {"FINISHED"}
assert len(settings.motions) == len(addon.source_catalog.CATALOG) + 1, len(settings.motions)
settings.include_noncommercial = False
assert bpy.ops.catani.motion_refresh() == {"FINISHED"}
free = sum(1 for entry in addon.source_catalog.CATALOG if entry.commercial_use)
assert len(settings.motions) == free + 1, (len(settings.motions), free)
settings.motion_active = next(index for index, item in enumerate(settings.motions) if item.available)
before = set(bpy.data.objects)
assert bpy.ops.catani.motion_import() == {"FINISHED"}, settings.motion_status
created = set(bpy.data.objects) - before
source = next(obj for obj in created if obj.type == "ARMATURE" and obj.animation_data and obj.animation_data.action)

# ZIP만 설치한 상태에서도 리타게팅 경로가 살아 있는지 확인한다.
armature = bpy.data.armatures.new("ZIP_검사_리그")
target = bpy.data.objects.new("ZIP_검사_리그", armature)
bpy.context.scene.collection.objects.link(target)
bpy.context.view_layer.objects.active = target
bpy.ops.object.mode_set(mode="EDIT")
for name, head, tail, parent in (("Hips", (0, 0, 0), (0, 0, 1), None), ("Spine", (0, 0, 1), (0, 0, 2), "Hips")):
    bone = armature.edit_bones.new(name)
    bone.head, bone.tail = head, tail
    if parent:
        bone.parent = armature.edit_bones[parent]
bpy.ops.object.mode_set(mode="OBJECT")
try:
    addon.retarget.build_pairs(source, target)
except ValueError as error:
    assert "지원 규격" in str(error), str(error)
else:
    raise AssertionError("본 2개짜리 리그가 최소 매핑 조건을 통과했습니다")
addon.unregister()
print("CATANI_PASS 배포 ZIP 독립 등록·Agent 제외·합성 예제 가져오기·리타게팅 모듈 포함·등록 해제")
