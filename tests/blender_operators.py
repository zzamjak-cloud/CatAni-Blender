"""UI 연산자와 미확정 저장·등록 해제의 복원을 검사한다."""
from pathlib import Path
import bpy
import bl_ext.user_default.catani as addon

root = Path(__file__).resolve().parents[1]
bpy.ops.wm.open_mainfile(filepath=str(root / "Blender/Player_Animation_01.blend"))
rig = bpy.data.objects["Amature_Player"]
for obj in bpy.context.selected_objects:
    obj.select_set(False)
rig.select_set(True)
bpy.context.view_layer.objects.active = rig
bpy.context.view_layer.update()
if bpy.context.mode != "OBJECT":
    bpy.ops.object.mode_set(mode="OBJECT")
originals = set(bpy.data.objects)
original_visibility = {o.name: (o.hide_get(), o.hide_render) for o in originals}
assert bpy.ops.catani.inspect_rig() == {"FINISHED"}
bpy.context.scene.catani_settings.recipe = "wave"
assert bpy.ops.catani.preview() == {"FINISHED"}
assert addon.engine.get_session() is not None
assert bpy.ops.catani.cancel() == {"FINISHED"}
assert set(bpy.data.objects) == originals
assert {o.name: (o.hide_get(), o.hide_render) for o in originals} == original_visibility
assert bpy.ops.catani.preview() == {"FINISHED"}
bpy.ops.wm.save_as_mainfile(filepath=str(root / "artifacts/CatAni_Cancel_Check.blend"))
assert addon.engine.get_session() is None
assert set(bpy.data.objects) == originals
assert {o.name: (o.hide_get(), o.hide_render) for o in originals} == original_visibility
assert bpy.ops.catani.preview() == {"FINISHED"}
addon.unregister()
assert addon.engine.get_session() is None
assert set(bpy.data.objects) == originals
assert not hasattr(bpy.types.Scene, "catani_settings")
addon.register()
assert hasattr(bpy.types.Scene, "catani_settings")
assert addon.engine.inspect_rig(bpy.data.objects["Player_Base"])
print("CATANI_PASS UI 연산자·저장 자동취소·등록 해제·재등록·미지원 입력")
