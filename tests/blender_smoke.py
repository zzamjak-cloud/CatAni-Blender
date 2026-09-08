"""실제 샘플에서 생성·취소·확정·저장을 검사한다."""
import json
import math
from pathlib import Path

import bpy
from bl_ext.user_default.catani import core, engine


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts"
OUTPUT.mkdir(exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=str(ROOT / "Blender/Player_Animation_01.blend"))
rig = bpy.data.objects["Amature_Player"]
scene = bpy.context.scene


def snapshot(obj):
    return {
        "action": obj.animation_data.action.name,
        "tracks": [(t.name, t.mute, t.is_solo) for t in obj.animation_data.nla_tracks],
        "constraints": [(p.name, c.name, c.influence, c.mute)
                        for p in obj.pose.bones for c in p.constraints],
        "pose": [list(v for row in p.matrix_basis for v in row) for p in obj.pose.bones],
        "frame": [scene.frame_start, scene.frame_end, scene.frame_current],
    }


before = snapshot(rig)
original_objects = set(bpy.data.objects)
original_actions = set(bpy.data.actions)
original_meshes = set(bpy.data.meshes)
assert not engine.inspect_rig(rig), engine.inspect_rig(rig)

recorded = {}
for recipe, side in [("idle", "R"), ("wave", "R"), ("wave", "L"), ("wave", "R")]:
    spec = core.MotionSpec(recipe=recipe, side=side, duration=2.0,
                           intensity=0.7, repeat=2, fps=60.0, start_frame=1)
    engine.begin_preview(bpy.context, rig, spec)
    previews = [o for o in bpy.data.objects if o not in original_objects and o.type == "ARMATURE"]
    assert len(previews) == 1, previews
    preview = previews[0]
    for obj in bpy.data.objects:
        if obj not in original_objects and obj.type == "MESH":
            assert obj.data not in original_meshes, "생성 메시가 원본 데이터와 공유됨"
    action = preview.animation_data.action
    assert action is not None and action not in original_actions
    positions = []
    for frame in range(1, 122):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        positions.append(tuple(preview.pose.bones[f"hand.{side}"].head))
        for bone in preview.pose.bones:
            assert all(math.isfinite(v) for row in bone.matrix for v in row)
    if recipe == "wave":
        assert max(p[2] for p in positions) - min(p[2] for p in positions) > 0.25, positions
    if (recipe, side) in recorded:
        assert positions == recorded[(recipe, side)], "동일 입력 재현 실패"
    recorded[(recipe, side)] = positions
    engine.cancel_preview(bpy.context)
    assert set(bpy.data.objects) == original_objects, "미리보기 오브젝트 누수"
    assert set(bpy.data.actions) == original_actions, "미리보기 Action 누수"
    assert set(bpy.data.meshes) == original_meshes, "미리보기 메시 데이터 누수"
    assert snapshot(rig) == before, "원본 상태 복원 실패"
    print("CATANI_PASS", recipe, side, "생성·취소·원본 복원")

spec = core.MotionSpec(recipe="wave", side="R", duration=3.0,
                       intensity=0.8, repeat=2, fps=60.0, start_frame=1)
engine.begin_preview(bpy.context, rig, spec)
confirmed = engine.confirm_preview(bpy.context)
assert confirmed.use_fake_user, "확정 Action 보존 표시 없음"
results = [o for o in bpy.data.objects if o not in original_objects and o.type == "ARMATURE"]
assert len(results) == 1, "확정 결과 리그 필요"
result = results[0]
assert result.animation_data.action == confirmed
assert rig.animation_data.action.name == before["action"]
expected = {}
for frame in [1, 46, 91, 136, 181]:
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    expected[str(frame)] = {p.name: [v for row in p.matrix for v in row]
                            for p in result.pose.bones}
scene["catani_verification"] = json.dumps({"rig": result.name, "poses": expected})
scene.frame_set(70)
bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT / "CatAni_Wave_Demo.blend"))
print("CATANI_PASS", "확정·저장", confirmed.name, result.name)
