"""Blender 안에서 모션 라이브러리 UI 흐름을 검사한다."""

from pathlib import Path
import tempfile
import bpy
import bl_ext.user_default.catani as addon


BVH_TEXT = """HIERARCHY
ROOT Hips
{
    OFFSET 0.00 0.00 0.00
    CHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation
    End Site
    {
        OFFSET 0.00 1.00 0.00
    }
}
MOTION
Frames: 2
Frame Time: 0.0416667
0.00 0.00 0.00 0.00 0.00 0.00
0.00 0.00 0.00 5.00 0.00 0.00
"""


root = Path(__file__).resolve().parents[1]
bpy.ops.wm.open_mainfile(filepath=str(root / "Blender/Player_Animation_01.blend"))
temporary = tempfile.TemporaryDirectory(prefix="catani-motion-ui-")
library = Path(temporary.name)
(library / "friendly_wave.bvh").write_text(BVH_TEXT, encoding="utf-8")
(library / "motions.json").write_text(
    '{"motions":[{"file":"friendly_wave.bvh","name":"테스트 손 인사","tags":["wave","greeting","friendly"],"description":"테스트용 최소 BVH"}]}',
    encoding="utf-8",
)

settings = bpy.context.scene.catani_settings
settings.motion_library_path = str(library)
settings.motion_query = "wave friendly"
assert bpy.ops.catani.motion_refresh() == {"FINISHED"}
assets = addon.assets_from_json(settings.motion_index_json)
assert len(assets) == 1
assert assets[0].name == "테스트 손 인사"
assert settings.motion_selected_id == assets[0].identifier

before = set(bpy.data.objects)
source = bpy.data.objects["Amature_Player"]
source_action = source.animation_data.action
source_visibility = {obj.name: (obj.hide_get(), obj.hide_render) for obj in before}
assert bpy.ops.catani.motion_import() == {"FINISHED"}
created = [obj for obj in bpy.data.objects if obj not in before]
assert any(obj.type == "ARMATURE" for obj in created), "BVH 가져오기 아마추어 없음"
assert any(obj.animation_data and obj.animation_data.action for obj in created), "BVH 가져오기 Action 없음"
assert any(obj.get("catani_motion_source") for obj in created), "모션 출처 속성 없음"
assert any(collection.name.startswith("CatAni 모션 원본") for collection in bpy.data.collections)
assert source.animation_data.action == source_action, "가져오기가 원본 Action을 변경했습니다"
assert {obj.name: (obj.hide_get(), obj.hide_render) for obj in before} == source_visibility
assert before.issubset(set(bpy.data.objects)), "가져오기가 기존 오브젝트를 제거했습니다"


def expect_cancelled(operator, **kwargs):
    """ERROR 보고가 Python 호출에서는 RuntimeError로 전달되는 경로도 확인한다."""
    try:
        assert operator(**kwargs) == {"CANCELLED"}
    except RuntimeError:
        pass


after_import = set(bpy.data.objects)
assert bpy.ops.catani.motion_pick(asset_id=assets[0].identifier) == {"FINISHED"}
expect_cancelled(bpy.ops.catani.motion_pick, asset_id="없는모션")
assert settings.motion_selected_id == assets[0].identifier
settings.motion_query = "없는검색어"
assert bpy.ops.catani.motion_refresh() == {"FINISHED"}
assert addon.assets_from_json(settings.motion_index_json) == []
assert settings.motion_selected_id == ""
expect_cancelled(bpy.ops.catani.motion_import)
assert set(bpy.data.objects) == after_import

settings.motion_query = "wave"
assert bpy.ops.catani.motion_refresh() == {"FINISHED"}
(library / "friendly_wave.bvh").unlink()
expect_cancelled(bpy.ops.catani.motion_import)
assert set(bpy.data.objects) == after_import, "사라진 모션 파일이 장면에 잔여 객체를 남겼습니다"
(library / "motions.json").write_text("{broken", encoding="utf-8")
expect_cancelled(bpy.ops.catani.motion_refresh)
assert set(bpy.data.objects) == after_import

addon.unregister()
addon.register()
temporary.cleanup()
print("CATANI_PASS 모션 라이브러리 목록·검색·선택·합성 BVH 가져오기·원본 보존·실패 경로")
